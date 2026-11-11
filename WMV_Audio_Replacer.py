#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WMV Audio Replacer
==================
Cambia la pista de audio de un video .wmv/.asf por tu propio .wav, conservando el video SIN recodificar.

Cómo funciona (por cada video):
  1. ffprobe lee el audio original: códec (WMA Pro / WMA estándar), canales, sample rate, bitrate, duración.
  2. ffmpeg adapta tu .wav a los canales y sample rate del original (y lo rellena con silencio / recorta a la
     duración original, si lo dejás activado).
  3. WMAEncodeRS.exe lo codifica con el MISMO códec que tenía el video (WMA Pro 6 canales, etc.).
  4. ffmpeg junta el video original (copia directa) con el audio nuevo en un .wmv nuevo.
  El video original nunca se toca: el resultado sale como <nombre>_new.wmv (o en la carpeta de salida).

Requisitos: Windows, ffmpeg + ffprobe y WMAEncodeRS.exe en la carpeta assets/ (o junto a este script / en el PATH).
Este archivo funciona solo (python WMV_Audio_Replacer.py) y tambien como modulo: DP_Audio_Studio.py lo importa
para su pestana «Videos». Sin dependencias de pip (solo tkinter).

Modo carpeta: cada video se empareja con el .wav que tenga el mismo nombre (video01.wmv <-> video01.wav).
"""
import json
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))          # True cuando corre como .exe (PyInstaller)
NOWIN = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
VALID_BITRATES = (20, 32, 48, 64, 96, 160, 192)       # los que usa el flujo WMAEncodeRS del Studio


def _app_dir():
    """Como .exe de un solo archivo, HERE es una carpeta temporal: los ajustes y las herramientas sueltas
    (ffmpeg.exe / ffprobe.exe) se buscan junto al ejecutable."""
    if not FROZEN:
        return HERE
    d = Path(sys.executable).resolve().parent
    try:
        t = d / ".wmv_write_test"
        t.write_text("x")
        t.unlink()
        return d
    except OSError:
        base = Path(os.environ.get("APPDATA") or Path.home()) / "WMV_Audio_Replacer"
        base.mkdir(parents=True, exist_ok=True)
        return base


APP_DIR = _app_dir()
SETTINGS = APP_DIR / "wmv_audio_replacer.json"
VIDEO_EXTS = (".wmv", ".asf")


# ----------------------------------------------------------------------------------------------
#  Herramientas externas
# ----------------------------------------------------------------------------------------------
def find_tool(names, extra=""):
    if extra and Path(extra).is_file():
        return str(extra)
    for d in (APP_DIR, APP_DIR / "assets", APP_DIR / "tools", HERE, HERE / "assets", HERE / "tools"):
        for n in names:
            if (d / n).is_file():
                return str(d / n)
    for n in names:
        w = shutil.which(n)
        if w:
            return w
    return None


def run(cmd, timeout=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, errors="replace",
                       timeout=timeout, creationflags=NOWIN)
    return r


def probe(ffprobe, path):
    """Devuelve dict con el audio (primer stream), cantidad de streams de video y duración."""
    r = run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path], timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe falló con {Path(path).name}:\n{r.stderr.strip()}")
    j = json.loads(r.stdout or "{}")
    streams = j.get("streams", [])
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [s for s in streams if s.get("codec_type") == "video"]

    def num(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    info = {"videos": len(video), "audios": len(audio), "duration": num(j.get("format", {}).get("duration")),
            "audio": None, "order": [s.get("codec_type") for s in streams]}
    if video:
        info["vcodec"] = video[0].get("codec_name")
    if audio:
        a = audio[0]
        info["audio"] = {"codec": a.get("codec_name"), "channels": int(a.get("channels") or 0),
                         "rate": int(num(a.get("sample_rate"))), "bitrate": int(num(a.get("bit_rate"))),
                         "duration": num(a.get("duration"), info["duration"]) or info["duration"],
                         "layout": a.get("channel_layout")}
    return info


def describe(info):
    a = info["audio"]
    v = f"video {info.get('vcodec', '?')}" if info["videos"] else "SIN video"
    if not a:
        return f"{v} · SIN audio · {info['duration']:.1f} s"
    return (f"{v} · audio {a['codec']} · {a['channels']} canal(es) ({a['layout'] or '?'}) · {a['rate']} Hz · "
            f"{a['bitrate'] // 1000} kbps · {a['duration']:.2f} s · {info['audios']} pista(s) de audio")


def peak_db(ffmpeg, path):
    """Nivel pico (dB) del primer audio ya decodificado. -999 = silencio total; None = no se pudo medir."""
    r = run([ffmpeg, "-v", "info", "-i", path, "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
            timeout=600)
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf)\s*dB", r.stderr or "")
    if not m:
        return None
    return -999.0 if m.group(1) == "-inf" else float(m.group(1))


# ---- cabecera ASF: lectura y corrección del WAVEFORMATEX -------------------------------------------
G_HEADER = bytes.fromhex("3026B2758E66CF11A6D900AA0062CE6C")
G_STREAM = bytes.fromhex("9107DCB7B7A9CF118EE600C00C205365")
G_AUDIO = bytes.fromhex("409E69F84D5BCF11A8FD00805F5C442B")
G_VIDEO = bytes.fromhex("C0EF19BC4D5BCF11A8FD00805F5C442B")
G_FILEPROPS = bytes.fromhex("A1DCAB8C47A9CF118EE400C00C205365")


def _asf_header(path):
    with open(path, "rb") as f:
        head = f.read(30)
        if len(head) < 30 or head[:16] != G_HEADER:
            raise RuntimeError(f"{Path(path).name} no es un ASF/WMV válido.")
        hsz = struct.unpack_from("<Q", head, 16)[0]
        f.seek(0)
        return bytearray(f.read(hsz)), hsz


def _asf_objects(buf, start, end):
    off = start
    while off + 24 <= end:
        size = struct.unpack_from("<Q", buf, off + 16)[0]
        if size < 24:
            break
        yield bytes(buf[off:off + 16]), off, size
        off += size


def asf_streams(path):
    """Lista de streams de la cabecera ASF: número, tipo y (si es audio) el WAVEFORMATEX."""
    buf, hsz = _asf_header(path)
    out = []
    for gid, off, size in _asf_objects(buf, 30, hsz):
        if gid != G_STREAM:
            continue
        kind = bytes(buf[off + 24:off + 40])
        ts_len = struct.unpack_from("<I", buf, off + 64)[0]
        num = struct.unpack_from("<H", buf, off + 72)[0] & 0x7F
        d = {"num": num, "type": "audio" if kind == G_AUDIO else "video" if kind == G_VIDEO else "otro"}
        if kind == G_AUDIO and ts_len >= 18:
            tag, ch, sr, avg, blk, bits, cb = struct.unpack_from("<HHIIHHH", buf, off + 78)
            d.update(tag=tag, ch=ch, rate=sr, avg=avg, block=blk, bits=bits, cb=cb)
        out.append(d)
    return out


def asf_packet_size(path):
    """Tamaño de paquete de datos ASF (min/max de las propiedades del archivo); 0 si no se pudo leer."""
    buf, hsz = _asf_header(path)
    for gid, off, size in _asf_objects(buf, 30, hsz):
        if gid == G_FILEPROPS:
            mn, mx = struct.unpack_from("<II", buf, off + 92)
            return mx if mn == mx else 0
    return 0


def describe_asf(path):
    parts = []
    for d in asf_streams(path):
        if d["type"] == "audio" and "tag" in d:
            parts.append(f"#{d['num']} audio tag=0x{d['tag']:x} {d['ch']}ch {d['rate']}Hz "
                         f"avg={d['avg'] * 8 // 1000}kbps blockalign={d['block']} cbSize={d['cb']}")
        else:
            parts.append(f"#{d['num']} {d['type']}")
    return " | ".join(parts)


def fix_asf_audio_format(path):
    """ffmpeg escribe el audio multicanal como WAVE_FORMAT_EXTENSIBLE (tag 0xFFFE, cbSize 40). Los WMV de
    origen usan el formato clásico (tag 0x162 / 0x161 + 18 bytes). Esto lo vuelve a la forma clásica.
    Devuelve True si cambió algo."""
    buf, hsz = _asf_header(path)
    fileprops = None
    target = None
    for gid, off, size in _asf_objects(buf, 30, hsz):
        if gid == G_FILEPROPS:
            fileprops = off
        elif gid == G_STREAM and bytes(buf[off + 24:off + 40]) == G_AUDIO:
            target = (off, size)
    if not target:
        return False
    off, size = target
    ts_len, ec_len = struct.unpack_from("<II", buf, off + 64)
    ts_off = off + 78
    tag, ch, sr, avg, blk, bits, cb = struct.unpack_from("<HHIIHHH", buf, ts_off)
    if tag != 0xFFFE or cb < 22 or ts_len < 18 + cb:
        return False
    sub = struct.unpack_from("<I", buf, ts_off + 18 + 6)[0]
    if sub not in (0x160, 0x161, 0x162, 0x163):
        return False
    extra = bytes(buf[ts_off + 18 + 22:ts_off + 18 + cb])
    new_ts = struct.pack("<HHIIHHH", sub, ch, sr, avg, blk, bits, len(extra)) + extra
    delta = len(new_ts) - ts_len
    obj_end = off + size
    new_obj = (bytes(buf[off:off + 64]) + struct.pack("<II", len(new_ts), ec_len) + bytes(buf[off + 72:ts_off]) +
               new_ts + bytes(buf[ts_off + ts_len:obj_end]))
    new_obj = bytearray(new_obj)
    struct.pack_into("<Q", new_obj, 16, size + delta)
    head = bytearray(buf[:off]) + new_obj + bytearray(buf[obj_end:hsz])
    struct.pack_into("<Q", head, 16, hsz + delta)
    if fileprops is not None:           # tamaño total del archivo en el objeto de propiedades
        fsz = struct.unpack_from("<Q", head, fileprops + 40)[0]
        struct.pack_into("<Q", head, fileprops + 40, fsz + delta)
    tmp = Path(str(path) + ".fix")
    with open(path, "rb") as src, open(tmp, "wb") as dst:
        dst.write(head)
        src.seek(hsz)
        shutil.copyfileobj(src, dst, 1 << 20)
    os.replace(tmp, path)
    return True


def snap_bitrate(bps):
    kb = max(1, bps // 1000)
    return min(VALID_BITRATES, key=lambda b: abs(b - kb))


# ----------------------------------------------------------------------------------------------
#  Núcleo
# ----------------------------------------------------------------------------------------------
def replace_audio(video, wav, out, ffmpeg, ffprobe, wma_exe, bitrate=None, fit=True, keep=False, log=print):
    video, wav, out = Path(video), Path(wav), Path(out)
    if out.resolve() == video.resolve():
        raise ValueError("La salida no puede ser el mismo archivo que el video original.")
    info = probe(ffprobe, video)
    log(f"  Original: {describe(info)}")
    try:
        log(f"  Cabecera ASF original: {describe_asf(video)}")
    except Exception as ex:
        log(f"  (no se pudo leer la cabecera ASF original: {ex})")
    a = info["audio"]
    if not info["videos"]:
        raise RuntimeError("El archivo no tiene pista de video.")
    if not a:
        raise RuntimeError("El video no tiene audio del cual copiar los parámetros.")
    codec = {"wmapro": "pro", "wmav2": "standard", "wmav1": "standard"}.get(a["codec"])
    if codec is None:
        raise RuntimeError(f"Códec de audio no soportado: {a['codec']} (solo WMA Pro y WMA estándar).")
    ch, rate = a["channels"], a["rate"]
    br = int(bitrate) if bitrate else snap_bitrate(a["bitrate"] or 192000)
    if not bitrate and a["bitrate"] and a["bitrate"] // 1000 > max(VALID_BITRATES):
        log(f"  Aviso: el original usa ~{a['bitrate'] // 1000} kbps; se usa {br} kbps (máximo de la lista). "
            f"Podés escribir otro valor en «Bitrate».")
    with tempfile.TemporaryDirectory(prefix="wmvrep_", dir=str(out.parent)) as tmp:
        tmp = Path(tmp)
        pcm, wma = tmp / "in.wav", tmp / "new.wma"
        # 1) adaptar el wav a canales / sample rate / duración del original
        cmd = [ffmpeg, "-y", "-v", "error", "-i", wav]
        if fit and a["duration"]:
            cmd += ["-af", "apad", "-t", f"{a['duration']:.3f}"]
        cmd += ["-ac", ch, "-ar", rate, "-c:a", "pcm_s16le", pcm]
        r = run(cmd)
        if r.returncode != 0 or not pcm.is_file():
            raise RuntimeError(f"ffmpeg no pudo preparar el wav:\n{r.stderr.strip()}")
        pi = probe(ffprobe, pcm)["audio"]
        if pi:
            log(f"  Tu audio adaptado: {pi['channels']} canal(es) · {pi['rate']} Hz · {pi['duration']:.2f} s")
        pk = peak_db(ffmpeg, pcm)
        log(f"  Nivel pico de tu audio adaptado: {pk if pk is not None else '?'} dB")
        if pk is not None and pk < -80:
            raise RuntimeError("Tu audio adaptado está en silencio (revisá el wav de entrada).")
        # 2) codificar con el mismo códec
        if wma_exe:
            cmd = [wma_exe, pcm, wma, "-c", codec, "-b", br, "-s", "--out-channels", ch, "--out-samplerate", rate]
            log(f"  WMAEncodeRS: -c {codec} -b {br} · {ch} canal(es) · {rate} Hz")
            r = run(cmd, timeout=600)
            if r.returncode != 0 or not wma.is_file():
                raise RuntimeError(f"WMAEncodeRS falló (código {r.returncode}):\n{(r.stderr or r.stdout).strip()}")
        elif codec == "standard" and ch <= 2:
            log("  Sin WMAEncodeRS.exe: se usa el encoder WMA estándar de ffmpeg.")
            r = run([ffmpeg, "-y", "-v", "error", "-i", pcm, "-c:a", "wmav2", "-b:a", f"{br}k", wma])
            if r.returncode != 0 or not wma.is_file():
                raise RuntimeError(f"ffmpeg no pudo codificar WMA:\n{r.stderr.strip()}")
        else:
            raise RuntimeError("Hace falta WMAEncodeRS.exe para codificar WMA Pro / multicanal "
                               "(ffmpeg no puede). Ponelo junto a este script o indicá su ruta.")
        wi = probe(ffprobe, wma)["audio"]
        if wi:
            log(f"  WMA generado: {wi['codec']} · {wi['channels']} canal(es) · {wi['rate']} Hz · "
                f"{wi['bitrate'] // 1000} kbps · {wi['duration']:.2f} s")
            if wi["codec"] != a["codec"] or wi["channels"] != ch:
                raise RuntimeError(f"El WMA generado no coincide con el original ({wi['codec']}, "
                                   f"{wi['channels']} canal(es)).")
        else:
            raise RuntimeError("El WMA generado no contiene audio.")
        pk = peak_db(ffmpeg, wma)
        log(f"  Nivel pico del WMA generado (decodificado): {pk if pk is not None else '?'} dB")
        if pk is not None and pk < -80:
            raise RuntimeError("El WMA generado suena en silencio: falló la codificación con WMAEncodeRS.")
        if keep:
            shutil.copy2(pcm, out.with_name(out.stem + "_wav_adaptado.wav"))
            shutil.copy2(wma, out.with_name(out.stem + "_audio.wma"))
            log(f"  Intermedios guardados: {out.stem}_wav_adaptado.wav y {out.stem}_audio.wma")
        # 3) juntar video original (copia) + audio nuevo
        tmp_out = out.with_name(out.stem + ".tmp" + out.suffix)
        # mismo orden de streams que el original (así conservan el mismo número de stream en el ASF)
        maps, vi, ai = [], 0, 0
        for t in info["order"]:
            if t == "video":
                maps += ["-map", f"0:v:{vi}"]
                vi += 1
            elif t == "audio" and ai == 0:
                maps += ["-map", "1:a:0"]
                ai += 1
        # Tamaño de paquete: igual al del original, y siempre lo bastante grande para que cada bloque de audio
        # entre ENTERO en un paquete (con 3200 el bloque se parte y el lector de Windows Media falla: 0xC00D002F).
        try:
            orig_pkt = asf_packet_size(video)
            new_blk = next((d["block"] for d in asf_streams(wma) if d["type"] == "audio" and "block" in d), 0)
        except Exception:
            orig_pkt, new_blk = 0, 0
        if orig_pkt and orig_pkt >= new_blk + 28:
            pkt = orig_pkt                         # el bloque entra entero (28 bytes de cabeceras bastan)
        else:
            pkt = min(65536, max(new_blk + 40, 3200))
        log(f"  Tamaño de paquete ASF: {pkt} (original {orig_pkt or '?'}, bloque de audio nuevo {new_blk or '?'})")
        cmd = [ffmpeg, "-y", "-v", "error", "-i", video, "-i", wma, *maps,
               "-map_metadata", "0", "-c", "copy", "-packet_size", pkt, "-f", "asf", tmp_out]
        r = run(cmd)
        if r.returncode != 0 or not tmp_out.is_file():
            tmp_out.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg no pudo juntar video y audio:\n{r.stderr.strip()}")
    # 4) corregir el formato de audio de la cabecera, verificar y mover
    try:
        if fix_asf_audio_format(tmp_out):
            log("  Cabecera ASF: audio vuelto al formato clásico (como el original).")
        chk = probe(ffprobe, tmp_out)
        ca = chk["audio"]
        if not ca or ca["codec"] != a["codec"] or ca["channels"] != ch:
            raise RuntimeError(f"Verificación fallida: {describe(chk)}")
        log(f"  Resultado: {describe(chk)}")
        log(f"  Cabecera ASF resultado: {describe_asf(tmp_out)}")
        pk = peak_db(ffmpeg, tmp_out)
        log(f"  Nivel pico del audio del resultado (decodificado): {pk if pk is not None else '?'} dB")
        if pk is None or pk < -80:
            log("  AVISO: el audio del resultado no se decodifica o está en silencio.")
        if info["audios"] > 1:
            log(f"  Aviso: el original tenía {info['audios']} pistas de audio; solo queda la nueva.")
        os.replace(tmp_out, out)
    except Exception:
        tmp_out.unlink(missing_ok=True)
        raise
    return out


def out_path_for(video, out_dir):
    video = Path(video)
    name = video.stem + "_new" + (video.suffix if video.suffix.lower() in VIDEO_EXTS else ".wmv")
    return (Path(out_dir) if out_dir else video.parent) / name


def pair_folder(video_dir, wav_dir):
    pairs, missing = [], []
    wavs = {p.stem.lower(): p for p in Path(wav_dir).iterdir() if p.suffix.lower() == ".wav"}
    for v in sorted(Path(video_dir).iterdir()):
        if v.suffix.lower() in VIDEO_EXTS:
            w = wavs.get(v.stem.lower())
            (pairs if w else missing).append((v, w) if w else v)
    return pairs, missing


# ----------------------------------------------------------------------------------------------
#  Ventana
# ----------------------------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    try:
        st = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        st = {}

    root = tk.Tk()
    root.title("WMV Audio Replacer")
    root.geometry("860x640")
    root.minsize(640, 480)
    BG, FG, ENT = "#1a1010", "#e9e1d1", "#2a1818"
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=FG, fieldbackground=ENT)
    style.configure("TButton", background="#6b1010", foreground=FG, padding=5)
    style.map("TButton", background=[("active", "#a01818")])
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.configure("TRadiobutton", background=BG, foreground=FG)
    style.configure("TEntry", fieldbackground=ENT, foreground=FG)
    style.configure("TCombobox", fieldbackground=ENT, foreground=FG)

    mode = tk.StringVar(value="one")
    v_video, v_wav, v_out = tk.StringVar(), tk.StringVar(), tk.StringVar()
    def _saved(key):      # una ruta guardada que ya no existe (otra PC, carpeta movida) se ignora
        v = st.get(key, "") or ""
        return v if v and Path(v).is_file() else ""
    v_wma = tk.StringVar(value=_saved("wma") or (find_tool(("WMAEncodeRS.exe", "WMAEncodeRS")) or ""))
    v_ff = tk.StringVar(value=_saved("ffmpeg"))
    v_br = tk.StringVar(value="auto")
    v_fit = tk.BooleanVar(value=True)
    v_keep = tk.BooleanVar(value=True)
    q = queue.Queue()
    busy = [False]

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    def row(r, label, var, browse):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 6))
        ttk.Entry(frm, textvariable=var).grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Button(frm, text="Examinar…", command=browse).grid(row=r, column=2, padx=(6, 0), pady=3)

    mf = ttk.Frame(frm)
    mf.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
    ttk.Radiobutton(mf, text="Un video + un wav", variable=mode, value="one").pack(side="left", padx=(0, 14))
    ttk.Radiobutton(mf, text="Carpeta de videos + carpeta de wavs (mismo nombre)", variable=mode,
                    value="dir").pack(side="left")

    def b_video():
        if mode.get() == "one":
            p = filedialog.askopenfilename(title="Video", filetypes=[("Video WMV/ASF", "*.wmv *.asf"), ("Todos", "*.*")])
        else:
            p = filedialog.askdirectory(title="Carpeta de videos")
        if p:
            v_video.set(p)

    def b_wav():
        if mode.get() == "one":
            p = filedialog.askopenfilename(title="Tu audio", filetypes=[("Audio", "*.wav *.flac *.mp3 *.ogg *.m4a"),
                                                                       ("Todos", "*.*")])
        else:
            p = filedialog.askdirectory(title="Carpeta de wavs")
        if p:
            v_wav.set(p)

    def b_out():
        p = filedialog.askdirectory(title="Carpeta de salida")
        if p:
            v_out.set(p)

    def b_exe(var, title, types):
        def f():
            p = filedialog.askopenfilename(title=title, filetypes=types)
            if p:
                var.set(p)
        return f

    row(1, "Video / carpeta:", v_video, b_video)
    row(2, "Tu audio / carpeta:", v_wav, b_wav)
    row(3, "Salida (vacío = junto al original):", v_out, b_out)
    row(4, "WMAEncodeRS.exe:", v_wma, b_exe(v_wma, "WMAEncodeRS.exe", [("Ejecutable", "*.exe"), ("Todos", "*.*")]))
    row(5, "ffmpeg.exe (vacío = PATH):", v_ff, b_exe(v_ff, "ffmpeg.exe", [("Ejecutable", "*.exe"), ("Todos", "*.*")]))

    of = ttk.Frame(frm)
    of.grid(row=6, column=0, columnspan=3, sticky="w", pady=6)
    ttk.Label(of, text="Bitrate (kbps):").pack(side="left")
    ttk.Combobox(of, textvariable=v_br, width=8, values=["auto"] + [str(b) for b in VALID_BITRATES]).pack(
        side="left", padx=(6, 16))
    ttk.Checkbutton(of, text="Ajustar la duración del audio a la del original (rellena con silencio / recorta)",
                    variable=v_fit).pack(side="left")
    ttk.Checkbutton(of, text="Guardar el .wma y el wav adaptado", variable=v_keep).pack(side="left", padx=(14, 0))

    bf = ttk.Frame(frm)
    bf.grid(row=7, column=0, columnspan=3, sticky="ew", pady=6)
    btn_info = ttk.Button(bf, text="Ver info del video")
    btn_go = ttk.Button(bf, text="Reemplazar audio")
    btn_info.pack(side="left")
    btn_go.pack(side="right")

    logw = tk.Text(frm, bg="#0d0707", fg=FG, insertbackground=FG, relief="flat", wrap="word", font=("Consolas", 10))
    logw.grid(row=8, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(8, weight=1)
    sb = ttk.Scrollbar(frm, command=logw.yview)
    sb.grid(row=8, column=3, sticky="ns")
    logw.configure(yscrollcommand=sb.set, state="disabled")

    def log(msg):
        q.put(msg)

    def pump():
        try:
            while True:
                m = q.get_nowait()
                if m is None:
                    busy[0] = False
                    btn_go.state(["!disabled"])
                    btn_info.state(["!disabled"])
                    continue
                logw.configure(state="normal")
                logw.insert("end", m + "\n")
                logw.see("end")
                logw.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(100, pump)

    def tools():
        ff = find_tool(("ffmpeg.exe", "ffmpeg"), v_ff.get().strip())
        fp = None
        if ff:
            cand = Path(ff).with_name("ffprobe.exe" if ff.lower().endswith(".exe") else "ffprobe")
            fp = str(cand) if cand.is_file() else find_tool(("ffprobe.exe", "ffprobe"))
        else:
            fp = find_tool(("ffprobe.exe", "ffprobe"))
        wm = v_wma.get().strip()
        wm = wm if wm and Path(wm).is_file() else None
        return ff, fp, wm

    def start(target):
        if busy[0]:
            return
        ff, fp, wm = tools()
        if not ff or not fp:
            messagebox.showerror("Falta ffmpeg", "No encuentro ffmpeg y ffprobe (PATH, junto al script o en el campo).")
            return
        SETTINGS.write_text(json.dumps({"wma": v_wma.get().strip(), "ffmpeg": v_ff.get().strip()}), encoding="utf-8")
        busy[0] = True
        btn_go.state(["disabled"])
        btn_info.state(["disabled"])

        def work():
            try:
                target(ff, fp, wm)
            except Exception as ex:
                log(f"ERROR: {ex}")
                if not isinstance(ex, (RuntimeError, ValueError)):
                    log(traceback.format_exc())
            finally:
                q.put(None)

        threading.Thread(target=work, daemon=True).start()

    def do_info(ff, fp, wm):
        p = v_video.get().strip()
        files = [Path(p)] if mode.get() == "one" else sorted(
            x for x in Path(p).iterdir() if x.suffix.lower() in VIDEO_EXTS) if p and Path(p).is_dir() else []
        if not files:
            log("Elegí un video (o una carpeta con videos) primero.")
            return
        for f in files:
            log(f"{f.name}: {describe(probe(fp, f))}")
            log(f"   cabecera ASF: {describe_asf(f)}")

    def do_go(ff, fp, wm):
        vp, wp, od = v_video.get().strip(), v_wav.get().strip(), v_out.get().strip()
        if not vp or not wp:
            log("Indicá el video y tu audio primero.")
            return
        br = v_br.get().strip()
        bitrate = None if br.lower() in ("", "auto") else int(br)
        if mode.get() == "one":
            pairs = [(Path(vp), Path(wp))]
        else:
            pairs, missing = pair_folder(vp, wp)
            for m in missing:
                log(f"Sin wav para {m.name}: se omite.")
            if not pairs:
                log("No hay ningún video con un wav del mismo nombre.")
                return
        if od:
            Path(od).mkdir(parents=True, exist_ok=True)
        ok = bad = 0
        for v, w in pairs:
            log(f"{v.name}  +  {w.name}")
            dest = out_path_for(v, od)
            try:
                replace_audio(v, w, dest, ff, fp, wm, bitrate=bitrate, fit=v_fit.get(), keep=v_keep.get(), log=log)
                log(f"  OK -> {dest}")
                ok += 1
            except Exception as ex:
                log(f"  ERROR: {ex}")
                bad += 1
        log(f"Terminado: {ok} bien, {bad} con error.")

    btn_info.configure(command=lambda: start(do_info))
    btn_go.configure(command=lambda: start(do_go))
    log("Elegí el video y tu audio. El video original no se modifica: sale un archivo nuevo (_new).")
    if not find_tool(("WMAEncodeRS.exe", "WMAEncodeRS"), v_wma.get().strip()):
        log("Aviso: no encuentro WMAEncodeRS.exe (necesario para WMA Pro / 6 canales).")
    pump()
    root.mainloop()


if __name__ == "__main__":
    try:
        run_gui()
    except Exception:
        print(traceback.format_exc())
        try:
            input("Enter para cerrar...")
        except EOFError:
            pass
