"""
dp2_panel.py - Soporte de audio para Deadly Premonition 2: A Blessing in Disguise
(Unity 2018.4.16f1; AudioClips FSB5 en .resource/.resS).

Se usa de dos formas:
  * Integrado en DP Audio Studio (selector de juego):  from dp2_panel import DP2Panel
  * Suelto:  python dp2_panel.py

Requisitos:  pip install customtkinter UnityPy
Herramientas externas (en assets\\, en tools\\, junto al programa o en el PATH):
  ffmpeg, vgmstream-cli y (opcional, para importar en Vorbis) fsbankcl.exe + libfsbvorbis.dll + Qt5Core.dll
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import wave
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
import UnityPy

FREQS = {8000: 1, 11000: 2, 11025: 3, 16000: 4, 22050: 5,
         24000: 6, 32000: 7, 44100: 8, 48000: 9}
FORMATS = ["WAV", "OGG", "MP3", "FSB (crudo)"]
CODECS = ["PCM16 (sin dependencias)", "Vorbis (requiere fsbankcl)"]
AUDIO_EXT = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus")
NOWIN = 0x08000000 if os.name == "nt" else 0
HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = None


# ----------------------------------------------------------------- rutas y herramientas
def set_app_dir(path):
    """El programa anfitrión indica su carpeta de datos (la misma de sus ajustes y de assets\\)."""
    global _APP_DIR
    _APP_DIR = str(path)


def app_dir():
    """Carpeta escribible junto al programa (o al .exe empaquetado)."""
    if _APP_DIR:
        return _APP_DIR
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return HERE


def tool_dirs():
    base = app_dir()
    dirs = [base, os.path.join(base, "assets"), os.path.join(base, "tools")]
    mp = getattr(sys, "_MEIPASS", None)  # contenido empaquetado por PyInstaller
    if mp:
        dirs += [mp, os.path.join(mp, "assets"), os.path.join(mp, "tools")]
    dirs += [HERE, os.path.join(HERE, "assets"), os.path.join(HERE, "tools")]
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def find_tool(name):
    for d in tool_dirs():
        for cand in (os.path.join(d, name + ".exe"), os.path.join(d, name)):
            if os.path.isfile(cand):
                return cand
    return shutil.which(name)


def tools_status():
    """Texto de estado de las herramientas externas y si todo está completo."""
    parts, ok = [], True
    for name, label in (("ffmpeg", "ffmpeg"), ("vgmstream-cli", "vgmstream"), ("fsbankcl", "fsbankcl")):
        have = find_tool(name) is not None
        parts.append(f"{label}: {'OK' if have else 'falta'}")
        ok = ok and have
    fb = find_tool("fsbankcl")
    if fb and os.name == "nt":
        d = os.path.dirname(os.path.abspath(fb))
        for dll in ("Qt5Core.dll", "libfsbvorbis.dll"):
            have = os.path.isfile(os.path.join(d, dll))
            parts.append(f"{dll}: {'OK' if have else 'falta'}")
            ok = ok and have
    return "  ·  ".join(parts), ok


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, creationflags=NOWIN, cwd=cwd)


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


# ----------------------------------------------------------------- FSB5 y conversión de audio
def build_fsb5_pcm16(pcm, channels, rate):
    """FSB5 mínimo con un solo subsonido PCM16 (mono/estéreo, frecuencias de la tabla)."""
    samples = len(pcm) // (2 * channels)
    sh = (FREQS[rate] << 1) | ((channels - 1) << 5) | (0 << 6) | (samples << 34)
    data = pcm + b"\x00" * ((-len(pcm)) % 32)
    header = struct.pack("<4sIIIIII", b"FSB5", 1, 1, 8, 0, len(data), 2)
    header += b"\x00" * 8 + b"\x00" * 16 + b"\x00" * 8
    return header + struct.pack("<Q", sh) + data


def probe_audio(src):
    """(frecuencia, canales) del audio de origen leyendo la salida de ffmpeg, o None."""
    ff = find_tool("ffmpeg")
    if not ff:
        return None
    r = run([ff, "-hide_banner", "-i", src])
    txt = r.stderr.decode(errors="ignore")
    m = re.search(r"Audio:.*?(\d+) Hz, ([^,\n]+)", txt)
    if not m:
        return None
    rate = int(m.group(1))
    layout = m.group(2).strip().lower()
    if layout.startswith("mono"):
        ch = 1
    elif "channels" in layout:
        ch = int(re.match(r"(\d+)", layout).group(1))
    else:
        ch = 2
    return rate, ch


def nearest_rate(rate):
    return rate if rate in FREQS else min(FREQS, key=lambda f: abs(f - rate))


def to_wav_pcm16(src, rate, channels):
    ff = find_tool("ffmpeg")
    if not ff:
        raise RuntimeError("No se encontró ffmpeg (ponlo en assets\\, en el PATH o junto al programa).")
    if os.path.getsize(src) == 0:
        raise RuntimeError(f"El archivo de entrada está vacío: {os.path.basename(src)}")
    out = tempfile.mktemp(suffix=".wav")
    cmd = [ff, "-y", "-i", src, "-vn", "-ac", str(channels), "-ar", str(rate),
           "-c:a", "pcm_s16le", out]
    try:
        r = run(cmd)
        if r.returncode != 0 or not os.path.isfile(out):
            raise RuntimeError("ffmpeg: " + r.stderr.decode(errors="ignore")[-400:])
        try:
            with wave.open(out, "rb") as w:
                pcm = w.readframes(w.getnframes())
        except (wave.Error, EOFError) as e:
            raise RuntimeError(f"WAV convertido inválido ({e}). ffmpeg: "
                               + r.stderr.decode(errors="ignore")[-300:])
    finally:
        if os.path.isfile(out):
            os.remove(out)
    if not pcm:
        raise RuntimeError("El audio convertido quedó vacío (¿archivo dañado o sin audio?): "
                           + os.path.basename(src))
    return pcm


def encode_vorbis(pcm, ch, rate, quality, loop):
    """Codifica con fsbankcl (FMOD) -> FSB5 Vorbis con codebooks que FMOD reconoce."""
    fb = find_tool("fsbankcl")
    if not fb:
        raise RuntimeError("Falta fsbankcl.exe (junto con libfsbvorbis.dll y Qt5Core.dll) "
                           "en assets\\, tools\\ o el PATH.")
    tmp = tempfile.mkdtemp()
    try:
        wav = os.path.join(tmp, "in.wav")
        out = os.path.join(tmp, "out.fsb")
        with wave.open(wav, "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        # Comando mínimo (menos argumentos = menos puntos de fallo)
        cmd = [fb] + ([] if loop else ["-no_loop"]) + [
            "-format", "vorbis", "-quality", str(int(quality)), "-o", out, wav]
        r = run(cmd, cwd=os.path.dirname(os.path.abspath(fb)))
        if not os.path.isfile(out):
            if (r.returncode & 0xFFFFFFFF) == 0xC0000135:
                raise RuntimeError("fsbankcl no arranca: faltan DLL junto a fsbankcl.exe "
                                   "(Qt5Core.dll, libfsbvorbis.dll) o el Visual C++ 2012 x86.")
            msg = (r.stdout + r.stderr).decode(errors="ignore")[-500:]
            raise RuntimeError(f"fsbankcl falló (código {r.returncode} = {r.returncode & 0xFFFFFFFF:#x}). "
                               f"Comando: {' '.join(cmd)} | Salida: {msg or '(vacía)'}")
        with open(out, "rb") as f:
            data = f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if data[:4] != b"FSB5":
        raise RuntimeError("fsbankcl no generó un FSB5 válido.")
    return data


# ----------------------------------------------------------------- Unity
BAD_EXT = {".ress", ".resource", ".dll", ".bak", ".json", ".txt", ".xml", ".exe", ".log"}


def cache_path():
    return os.path.join(app_dir(), "dp2_clips_cache.json")


def is_serialized(fn):
    low = fn.lower()
    if os.path.splitext(low)[1] in BAD_EXT:
        return False
    return (low == "globalgamemanagers" or low.endswith(".assets")
            or re.fullmatch(r"level\d+", low) is not None)


def parse_audioclip(buf):
    """Posiciones de los campos de un AudioClip serializado (Unity 2018.4, little-endian)."""
    n = struct.unpack_from("<i", buf, 0)[0]
    if not 0 <= n < 512:
        raise RuntimeError("Cabecera de AudioClip inválida (posición del objeto incorrecta).")
    name = bytes(buf[4:4 + n]).decode("utf-8", "replace")
    p = 4 + n
    p += (-p) % 4
    q = p + 24                       # tras 5 campos de 4 bytes + bools alineados
    q += 4 + 4                       # m_SubsoundIndex + (3 bools alineados)
    slen = struct.unpack_from("<i", buf, q)[0]
    if not 0 <= slen < 512:
        raise RuntimeError("m_Source inválido: el layout del AudioClip no coincide.")
    src = bytes(buf[q + 4:q + 4 + slen]).decode("utf-8", "replace")
    r = q + 4 + slen
    r += (-r) % 4
    off, size = struct.unpack_from("<QQ", buf, r)
    return {"name": name, "p": p, "sub": p + 24, "res": r, "comp": r + 16, "src": src,
            "ch": struct.unpack_from("<i", buf, p + 4)[0],
            "freq": struct.unpack_from("<i", buf, p + 8)[0], "off": off, "size": size}


class Project:
    """Escanea solo los archivos serializados (no los .resource/.resS enormes)
    y guarda un índice en caché: la segunda vez abre al instante."""

    def __init__(self, data_dir, progress=lambda t: None):
        self.data_dir = data_dir
        self.opts = {}
        files = sorted(f for f in os.listdir(data_dir)
                       if is_serialized(f) and os.path.isfile(os.path.join(data_dir, f)))
        sig = {f: [os.path.getsize(os.path.join(data_dir, f)),
                   int(os.path.getmtime(os.path.join(data_dir, f)))] for f in files}
        self.sig = sig
        self.clips = self._load_cache(sig)
        if self.clips is None:
            self.clips = []
            for i, f in enumerate(files, 1):
                progress(f"Escaneando {f} ({i}/{len(files)}) - {len(self.clips)} clips")
                try:
                    env = UnityPy.load(os.path.join(data_dir, f))
                    for obj in env.objects:
                        if obj.type.name != "AudioClip":
                            continue
                        d = obj.read()
                        r = d.m_Resource
                        self.clips.append({
                            "name": d.m_Name or f"clip_{obj.path_id}", "file": f,
                            "pid": obj.path_id, "ch": d.m_Channels, "freq": d.m_Frequency,
                            "src": r.m_Source if r else "", "off": r.m_Offset if r else 0,
                            "size": r.m_Size if r else 0,
                            "bs": obj.byte_start, "bsz": obj.byte_size,
                            "len": float(getattr(d, "m_Length", 0) or 0),
                            "comp": int(getattr(d, "m_CompressionFormat", -1))})
                except Exception as e:
                    progress(f"Saltado {f}: {e}")
            self.clips.sort(key=lambda c: c["name"].lower())
            self._save_cache()

    def _load_cache(self, sig):
        try:
            with open(cache_path(), "r", encoding="utf-8") as fh:
                c = json.load(fh)
            if c.get("v") == 3 and c.get("dir") == self.data_dir and c.get("sig") == sig:
                return c["clips"]
        except Exception:
            pass
        return None

    def _save_cache(self):
        try:
            with open(cache_path(), "w", encoding="utf-8") as fh:
                json.dump({"v": 3, "dir": self.data_dir, "sig": self.sig, "clips": self.clips}, fh)
        except Exception:
            pass

    def get_obj(self, clip):
        env = UnityPy.load(os.path.join(self.data_dir, clip["file"]))
        for o in env.objects:
            if o.path_id == clip["pid"]:
                return o
        raise RuntimeError("No se encontró el objeto en el archivo.")

    def raw_bytes(self, clip):
        if clip["size"]:
            path = os.path.join(self.data_dir, os.path.basename(clip["src"]))
            with open(path, "rb") as f:
                f.seek(clip["off"])
                return f.read(clip["size"])
        return bytes(self.get_obj(clip).read().m_AudioData)

    def extract(self, clip, out_dir, fmt="WAV"):
        raw = self.raw_bytes(clip)
        base = os.path.join(out_dir, safe(clip["name"]))
        fsb = base + ".fsb"
        with open(fsb, "wb") as f:
            f.write(raw)
        vg = find_tool("vgmstream-cli")
        if fmt.startswith("FSB") or not vg:
            return fsb
        wav = base + ".wav"
        r = run([vg, "-o", wav, fsb])
        if r.returncode != 0:
            raise RuntimeError("vgmstream: " + r.stderr.decode(errors="ignore")[-200:])
        os.remove(fsb)
        if fmt == "WAV":
            return wav
        ff = find_tool("ffmpeg")
        if not ff:
            raise RuntimeError("Falta ffmpeg para convertir a " + fmt)
        if fmt == "OGG":
            out, codec = base + ".ogg", ["-c:a", "libvorbis", "-q:a", "6"]
        else:
            out, codec = base + ".mp3", ["-c:a", "libmp3lame", "-q:a", "2"]
        r = run([ff, "-y", "-i", wav] + codec + [out])
        if r.returncode != 0:
            raise RuntimeError("ffmpeg: " + r.stderr.decode(errors="ignore")[-200:])
        os.remove(wav)
        return out

    def replace_many(self, items, progress=lambda t, v: None):
        """items: lista de (clip, ruta_audio). Parcha el AudioClip EN EL SITIO (mismo tamaño)
        y agrega el FSB nuevo al final del .resource; no reescribe el resto del .assets."""
        by_file = {}
        for clip, audio in items:
            by_file.setdefault(clip["file"], []).append((clip, audio))
        total, done, errors = len(items), 0, []
        for fname, group in by_file.items():
            path = os.path.join(self.data_dir, fname)
            if not os.path.exists(path + ".bak"):
                shutil.copy2(path, path + ".bak")
            with open(path, "r+b") as af:
                for clip, audio in group:
                    progress(f"Reemplazando {clip['name']} ({done + 1}/{total})", done / total)
                    done += 1
                    try:
                        if not clip.get("bs") or not clip["size"]:
                            raise RuntimeError("Clip sin recurso externo o índice viejo "
                                               "(borra dp2_clips_cache.json y reabre la carpeta).")
                        af.seek(clip["bs"])
                        buf = bytearray(af.read(clip["bsz"]))
                        info = parse_audioclip(buf)
                        if (info["name"], info["src"], info["off"], info["size"]) != \
                                (clip["name"], clip["src"], clip["off"], clip["size"]):
                            raise RuntimeError(f"El objeto no coincide con el índice: leído {info}")
                        rate = clip["freq"] if clip["freq"] in FREQS else 48000
                        ch = 1 if clip["ch"] == 1 else 2
                        if self.opts.get("native"):  # respetar frecuencia/canales de tu audio
                            pr = probe_audio(audio)
                            if pr:
                                rate, ch = nearest_rate(pr[0]), (1 if pr[1] == 1 else 2)
                        pcm = to_wav_pcm16(audio, rate, ch)
                        if self.opts.get("codec") == "vorbis":
                            fsb = encode_vorbis(pcm, ch, rate, self.opts.get("quality", 80),
                                                self.opts.get("loop", False))
                            comp = 1  # Vorbis
                        else:
                            fsb = build_fsb5_pcm16(pcm, ch, rate)
                            comp = 0  # PCM
                        res = os.path.join(self.data_dir, os.path.basename(clip["src"]))
                        if not os.path.exists(res + ".bak"):
                            shutil.copy2(res, res + ".bak")
                        with open(res, "ab") as rf:
                            rf.write(b"\x00" * ((-rf.tell()) % 32))
                            offset = rf.tell()
                            rf.write(fsb)
                        pp = info["p"]
                        struct.pack_into("<i", buf, pp + 4, ch)
                        struct.pack_into("<i", buf, pp + 8, rate)
                        struct.pack_into("<i", buf, pp + 12, 16)
                        struct.pack_into("<f", buf, pp + 16, (len(pcm) // (2 * ch)) / rate)
                        struct.pack_into("<i", buf, info["sub"], 0)
                        struct.pack_into("<QQ", buf, info["res"], offset, len(fsb))
                        struct.pack_into("<i", buf, info["comp"], comp)
                        af.seek(clip["bs"])
                        af.write(buf)
                        clip.update({"ch": ch, "freq": rate, "off": offset, "size": len(fsb),
                                     "len": len(pcm) / (2 * ch) / rate, "comp": comp})
                    except Exception as e:
                        errors.append(f"{clip['name']}: {type(e).__name__}: {e}")
            self.sig[fname] = [os.path.getsize(path), int(os.path.getmtime(path))]
        self._save_cache()
        progress("Listo", 1.0)
        return total - len(errors), errors


# ----------------------------------------------------------------- GUI
PAL = {"BASE": "#1e1e2e", "MANTLE": "#181825", "S0": "#313244", "S1": "#45475a",
       "TEXT": "#cdd6f4", "SUB": "#a6adc8", "ACCENT": "#cba6f7", "HOVER": "#b48ee0",
       "ON_ACCENT": "#181825", "GREEN": "#a6e3a1", "RED": "#f38ba8", "YELLOW": "#f9e2af",
       "SEL": "#6b4fa0", "HEAD": "#45475a", "HEAD_ACTIVE": "#585b70", "ROW_HOVER": "#313244"}
COMP_NAMES = {0: "PCM", 1: "Vorbis", 2: "ADPCM", 3: "MP3", 4: "VAG", 5: "HEVAG", 6: "XMA",
              7: "AAC", 8: "GCADPCM", 9: "ATRAC9"}
STACK_W = 980          # por debajo de este ancho, la lista queda arriba y el detalle abajo


def fmt_time(sec):
    m, s = divmod(int(round(max(0.0, sec))), 60)
    return f"{m}:{s:02d}"


def fmt_size(n):
    if n >= 1048576:
        return f"{n / 1048576:.1f} MB"
    return f"{max(1, n // 1024)} KB" if n else "-"


class DP2Panel(ctk.CTkFrame):
    """Panel de Deadly Premonition 2 (lista + detalle + pestañas, como el de DP1)."""

    def __init__(self, master, status_cb=None, palette=None, app_dir=None):
        if app_dir:
            set_app_dir(app_dir)
        pal = {**PAL, **(palette or {})}      # el Studio inyecta su propia paleta
        super().__init__(master, fg_color=pal["BASE"], corner_radius=0)
        self.pal = pal
        self.status_cb = status_cb
        self.proj = None
        self.visible = []          # clips mostrados (mismo orden que el Treeview; iid = indice)
        self.cur = None            # clip elegido
        self.replaced = set()      # clips reemplazados en esta sesion
        self._stacked = None
        self._resize_job = None
        self._play = {"token": 0, "backend": None, "lib": None, "start": 0.0, "playing": False, "job": None}
        self._prev_cache = {}
        self._prev_dir = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_bar()
        self.body = ctk.CTkFrame(self, fg_color=pal["BASE"], corner_radius=0)
        self.body.grid(row=1, column=0, sticky="nsew")
        self._build_list_panel()
        self._build_detail_panel()
        if self.status_cb is None:          # solo en modo suelto; dentro del Studio usa su barra de estado
            self.status = ctk.CTkLabel(self, text="Listo", anchor="w", text_color=pal["SUB"], font=self._font(11))
            self.status.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 6))
        else:
            self.status = None
        self.check_tools()
        self.bind("<Configure>", self._on_configure, add="+")
        self.after(120, self._apply_layout)

    # ---------------------------------------------------------------- utilidades de widgets
    def _font(self, size, weight="normal"):
        return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)

    def _title_font(self, size):
        return ctk.CTkFont(family="Georgia", size=size, weight="bold")

    def _btn(self, parent, text, cmd, primary=False, width=0, height=32):
        p = self.pal
        kw = {"width": width} if width else {}
        return ctk.CTkButton(parent, text=text, command=cmd, height=height, font=self._font(12, "bold"),
                             fg_color=p["ACCENT"] if primary else p["S0"],
                             hover_color=p["HOVER"] if primary else p["ROW_HOVER"],
                             border_width=0 if primary else 1, border_color=p["S1"],
                             text_color=p["ON_ACCENT"] if primary else p["TEXT"], corner_radius=6, **kw)

    def _menu(self, parent, values, var, width=150, command=None):
        p = self.pal
        return ctk.CTkOptionMenu(parent, values=values, variable=var, width=width, command=command,
                                 fg_color=p["S0"], button_color=p["ACCENT"], button_hover_color=p["HOVER"],
                                 dropdown_fg_color=p["S0"], text_color=p["TEXT"], font=self._font(12))

    def _switch(self, parent, text, var, command=None):
        p = self.pal
        return ctk.CTkSwitch(parent, text=text, variable=var, command=command, progress_color=p["HOVER"],
                             button_color=p["TEXT"], button_hover_color="#ffffff", fg_color=p["S1"],
                             text_color=p["TEXT"], font=self._font(12))

    # ---------------------------------------------------------------- construccion
    def _build_bar(self):
        p = self.pal
        self.bar = ctk.CTkFrame(self, fg_color=p["MANTLE"], corner_radius=0)
        self.bar.grid(row=0, column=0, sticky="ew")
        self.bar.grid_columnconfigure(3, weight=1)
        self._btn(self.bar, "Abrir carpeta *_Data…", self.open_dir, primary=True, width=170).grid(
            row=0, column=0, padx=(10, 4), pady=8)
        self._btn(self.bar, "Reescanear", self.rescan, width=100).grid(row=0, column=1, padx=4, pady=8)
        self.path_lbl = ctk.CTkLabel(self.bar, text="Ninguna carpeta abierta", text_color=p["SUB"], anchor="w",
                                     font=self._font(12))
        self.path_lbl.grid(row=0, column=2, columnspan=2, padx=(10, 6), sticky="w")
        self.prog_box = ctk.CTkFrame(self.bar, fg_color="transparent")
        self.prog_box.grid(row=0, column=4, padx=10, pady=6, sticky="e")
        self.prog_lbl = ctk.CTkLabel(self.prog_box, text="", text_color=p["TEXT"], font=self._font(12, "bold"))
        self.prog_lbl.pack(side="left", padx=(0, 8))
        self.bar_prog = ctk.CTkProgressBar(self.prog_box, width=150, progress_color=p["HOVER"], fg_color=p["S1"])
        self.bar_prog.set(0)
        self.bar_prog.pack(side="left")
        self.tools_lbl = ctk.CTkLabel(self.bar, text="", anchor="w", justify="left", font=self._font(11),
                                      wraplength=900)
        self.tools_lbl.grid(row=1, column=0, columnspan=5, sticky="ew", padx=12, pady=(0, 6))

    def _build_list_panel(self):
        p = self.pal
        self.list_panel = ctk.CTkFrame(self.body, fg_color=p["MANTLE"], corner_radius=10, border_width=1,
                                       border_color=p["S1"])
        lp = self.list_panel
        lp.grid_rowconfigure(1, weight=1)
        lp.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(lp, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        top.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(top, placeholder_text="Buscar por nombre o número…", fg_color=p["S0"],
                                   border_color=p["S1"], text_color=p["TEXT"], font=self._font(12))
        self.search.grid(row=0, column=0, sticky="ew")
        self.search.bind("<KeyRelease>", lambda e: self.refresh())
        self.filter_var = ctk.StringVar(value="Todos los archivos")
        self.filter_menu = self._menu(top, ["Todos los archivos"], self.filter_var, width=190,
                                      command=lambda v: self.refresh())
        self.filter_menu.grid(row=0, column=1, padx=(6, 0))

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("DP2.Treeview", background=p["S0"], fieldbackground=p["S0"], foreground=p["TEXT"],
                        rowheight=30, borderwidth=0, font=("Segoe UI", 11))
        style.configure("DP2.Treeview.Heading", background=p["HEAD"], foreground=p["TEXT"], relief="flat",
                        font=("Segoe UI", 10, "bold"))
        style.map("DP2.Treeview", background=[("selected", p["SEL"])], foreground=[("selected", "#ffffff")])
        style.map("DP2.Treeview.Heading", background=[("active", p["HEAD_ACTIVE"])])

        cols = ("idx", "name", "fmt", "ch", "freq", "dur", "size")
        self.tree = ttk.Treeview(lp, columns=cols, show="headings", selectmode="extended", style="DP2.Treeview")
        for c, title, width, stretch in (("idx", "#", 52, False), ("name", "Nombre", 240, True),
                                         ("fmt", "Códec", 72, False), ("ch", "Canales", 70, False),
                                         ("freq", "Hz", 66, False), ("dur", "Dur.", 56, False),
                                         ("size", "Tamaño", 76, False)):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=width, minwidth=40, stretch=stretch, anchor="w")
        self.tree.tag_configure("done", foreground=p["GREEN"])
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
        sb = ctk.CTkScrollbar(lp, command=self.tree.yview, fg_color=p["MANTLE"], button_color=p["S1"],
                              button_hover_color=p["ACCENT"])
        sb.grid(row=1, column=1, sticky="ns", padx=(2, 6), pady=(0, 8))
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<space>", lambda e: (self._toggle_play(), "break")[1])
        self.count_lbl = ctk.CTkLabel(lp, text="", text_color=p["SUB"], anchor="w", font=self._font(11))
        self.count_lbl.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 8))

    def _build_detail_panel(self):
        p = self.pal
        self.detail = ctk.CTkScrollableFrame(self.body, fg_color=p["MANTLE"], corner_radius=10, border_width=1,
                                             border_color=p["S1"], scrollbar_button_color=p["S1"],
                                             scrollbar_button_hover_color=p["ACCENT"])
        d = self.detail
        d.grid_columnconfigure(0, weight=1)
        self.now_title = ctk.CTkLabel(d, text="Elegí un clip", font=self._title_font(22), text_color=p["TEXT"],
                                      anchor="w", justify="left", wraplength=360)
        self.now_title.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        self.now_meta = ctk.CTkLabel(d, text="", text_color=p["SUB"], anchor="w", justify="left",
                                     font=self._font(12), wraplength=360)
        self.now_meta.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        card = ctk.CTkFrame(d, fg_color=p["S0"], corner_radius=10, border_width=1, border_color=p["S1"])
        card.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        card.grid_columnconfigure((0, 1), weight=1)
        self.btn_play = self._btn(card, "▶ Reproducir", self._toggle_play, primary=True, height=34)
        self.btn_play.grid(row=0, column=0, padx=(10, 4), pady=10, sticky="ew")
        self._btn(card, "■ Detener", self._stop, height=34).grid(row=0, column=1, padx=(4, 10), pady=10, sticky="ew")
        self.play_bar = ctk.CTkProgressBar(card, progress_color=p["HOVER"], fg_color=p["S1"])
        self.play_bar.set(0)
        self.play_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12)
        self.time_lbl = ctk.CTkLabel(card, text="0:00 / 0:00", text_color=p["SUB"], font=self._font(12))
        self.time_lbl.grid(row=2, column=0, columnspan=2, pady=(2, 8))

        self.tabs = ctk.CTkTabview(d, height=470, fg_color=p["S0"], border_width=1, border_color=p["S1"],
                                   segmented_button_fg_color=p["MANTLE"], segmented_button_selected_color=p["ACCENT"],
                                   segmented_button_selected_hover_color=p["HOVER"],
                                   segmented_button_unselected_color=p["S0"],
                                   segmented_button_unselected_hover_color=p["ROW_HOVER"], text_color=p["TEXT"])
        self.tabs.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        self._build_tab_replace(self.tabs.add("Reemplazar"))
        self._build_tab_extract(self.tabs.add("Extraer"))

    def _build_tab_replace(self, tab):
        p = self.pal
        tab.grid_columnconfigure(0, weight=1)
        self.rep_hint = ctk.CTkLabel(tab, text="Elegí un clip para ver su códec.", text_color=p["SUB"], anchor="w",
                                     justify="left", font=self._font(12), wraplength=340)
        self.rep_hint.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 8))
        self._btn(tab, "Reemplazar el audio de este clip…", self.do_replace, primary=True, height=40).grid(
            row=1, column=0, sticky="ew", padx=10, pady=4)
        self._btn(tab, "Reemplazar varios desde una carpeta (por nombre)…", self.do_replace_folder, height=36).grid(
            row=2, column=0, sticky="ew", padx=10, pady=4)
        ctk.CTkLabel(tab, text="Importar como", text_color=p["SUB"], anchor="w", font=self._font(12)).grid(
            row=3, column=0, sticky="ew", padx=12, pady=(10, 0))
        self.codec = ctk.StringVar(value=CODECS[0])
        self._menu(tab, CODECS, self.codec, width=260, command=lambda v: self._refresh_hint()).grid(
            row=4, column=0, sticky="w", padx=10, pady=4)
        self.q = ctk.IntVar(value=80)
        self.qlbl = ctk.CTkLabel(tab, text="Calidad Vorbis: 80", text_color=p["SUB"], anchor="w", font=self._font(12))
        self.qlbl.grid(row=5, column=0, sticky="ew", padx=12, pady=(6, 0))

        def on_q(v):
            self.qlbl.configure(text=f"Calidad Vorbis: {int(v)}")
            self._refresh_hint()
        ctk.CTkSlider(tab, from_=10, to=100, number_of_steps=90, variable=self.q, command=on_q,
                      progress_color=p["HOVER"], button_color=p["TEXT"], button_hover_color="#ffffff",
                      fg_color=p["S1"]).grid(row=6, column=0, sticky="ew", padx=12, pady=(2, 6))
        self.loop = ctk.BooleanVar(value=False)
        self._switch(tab, "Loop (para música de fondo)", self.loop).grid(row=7, column=0, sticky="w", padx=12, pady=3)
        self.native = ctk.BooleanVar(value=False)
        self._switch(tab, "Mantener frecuencia y canales de mi audio", self.native).grid(
            row=8, column=0, sticky="w", padx=12, pady=3)
        ctk.CTkLabel(tab, text="Antes de modificar se crean copias .bak de los .assets y .resource tocados. "
                               "El audio nuevo se agrega al final del .resource.", text_color=p["SUB"], anchor="w",
                     justify="left", font=self._font(11), wraplength=340).grid(
            row=9, column=0, sticky="ew", padx=12, pady=(8, 4))

    def _build_tab_extract(self, tab):
        p = self.pal
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text="Formato de salida", text_color=p["SUB"], anchor="w", font=self._font(12)).grid(
            row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        self.fmt = ctk.StringVar(value="WAV")
        self._menu(tab, FORMATS, self.fmt, width=200).grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self._btn(tab, "Extraer los clips seleccionados…", self.do_extract, primary=True, height=40).grid(
            row=2, column=0, sticky="ew", padx=10, pady=(10, 4))
        self._btn(tab, "Extraer todos los clips de la lista…", lambda: self.do_extract(all_=True), height=36).grid(
            row=3, column=0, sticky="ew", padx=10, pady=4)
        ctk.CTkLabel(tab, text="«Todos» respeta el buscador y el filtro de archivo. WAV, OGG y MP3 necesitan "
                               "vgmstream-cli (y ffmpeg para OGG/MP3); FSB deja el audio tal cual está en el juego.",
                     text_color=p["SUB"], anchor="w", justify="left", font=self._font(11), wraplength=340).grid(
            row=4, column=0, sticky="ew", padx=12, pady=(8, 4))

    # ---------------------------------------------------------------- layout adaptable
    def _on_configure(self, event):
        if event.widget is not self:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._apply_layout)

    def _apply_layout(self):
        self._resize_job = None
        w = max(self.winfo_width(), 100)
        stacked = w < STACK_W
        if stacked != self._stacked:
            self._stacked = stacked
            for widget in (self.list_panel, self.detail):
                widget.grid_forget()
            for c in (0, 1):
                self.body.grid_columnconfigure(c, weight=0)
            for r in (0, 1):
                self.body.grid_rowconfigure(r, weight=0)
            if stacked:
                self.list_panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
                self.detail.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
                self.body.grid_columnconfigure(0, weight=1)
                self.body.grid_rowconfigure(0, weight=3)
                self.body.grid_rowconfigure(1, weight=2)
            else:
                self.list_panel.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
                self.detail.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
                self.body.grid_columnconfigure(0, weight=3)
                self.body.grid_columnconfigure(1, weight=2)
                self.body.grid_rowconfigure(0, weight=1)
            if w < 900:
                self.prog_box.grid_configure(row=2, column=0, columnspan=5, sticky="w", padx=10)
            else:
                self.prog_box.grid_configure(row=0, column=4, columnspan=1, sticky="e", padx=10)
        wrap = max(220, (w // 3 if not stacked else w - 80) - 70)
        for lbl in (self.now_title, self.now_meta, self.rep_hint):
            lbl.configure(wraplength=wrap)
        self.tools_lbl.configure(wraplength=max(240, w - 40))

    # ---------------------------------------------------------------- estado
    def check_tools(self):
        text, ok = tools_status()
        self.tools_lbl.configure(text="Herramientas:  " + text,
                                 text_color=self.pal["GREEN"] if ok else self.pal["YELLOW"])
        if self.cur is not None:
            self._refresh_hint()

    def set_status(self, t):
        def apply():
            if self.status is not None:
                self.status.configure(text=t)
            if self.status_cb:
                self.status_cb(t)
        self.after(0, apply)

    def set_progress(self, v, text=""):
        def apply():
            self.bar_prog.set(max(0.0, min(1.0, v)))
            self.prog_lbl.configure(text=text)
        self.after(0, apply)

    def report(self, text, v):
        self.set_status(text)
        self.set_progress(v, f"{int(v * 100)} %" if 0 < v < 1 else "")

    def finish(self, title, ok, errors, out=None):
        if errors:
            try:
                with open(os.path.join(out or app_dir(), "errores_dp2.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(errors))
            except Exception:
                pass
        self.report(f"{title}: {ok} OK, {len(errors)} errores"
                    + (f" (primero: {errors[0][:120]})" if errors else ""), 1.0)

    # ---------------------------------------------------------------- carpeta y lista
    def open_dir(self):
        d = filedialog.askdirectory(title="Carpeta *_Data del juego")
        if d:
            self._load_dir(d)

    def rescan(self):
        if not self.proj:
            messagebox.showinfo("Reescanear", "Abrí primero una carpeta *_Data.")
            return
        try:
            os.remove(cache_path())
        except OSError:
            pass
        self._load_dir(self.proj.data_dir)

    def _load_dir(self, d):
        self._stop()
        self.path_lbl.configure(text=d)
        self.check_tools()
        self.set_status("Cargando assets (puede tardar)…")

        def work():
            try:
                proj = Project(d, self.set_status)
                self.proj = proj
                self.after(0, self._after_load)
                self.set_status(f"{len(proj.clips)} AudioClips encontrados")
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _after_load(self):
        srcs = sorted({os.path.basename(c["src"]) for c in self.proj.clips if c["src"]})
        self.filter_menu.configure(values=["Todos los archivos"] + srcs)
        self.filter_var.set("Todos los archivos")
        self.cur = None
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.visible = []
        if not self.proj:
            return
        q = self.search.get().strip().lower()
        src = self.filter_var.get()
        for c in self.proj.clips:
            if src != "Todos los archivos" and os.path.basename(c["src"]) != src:
                continue
            if q and q not in c["name"].lower():
                continue
            self.visible.append(c)
        for i, c in enumerate(self.visible):
            self.tree.insert("", "end", iid=str(i), tags=("done",) if self._key(c) in self.replaced else (),
                             values=(i + 1, c["name"], COMP_NAMES.get(c.get("comp"), "?"),
                                     "mono" if c["ch"] == 1 else f'{c["ch"]} canales', c["freq"],
                                     fmt_time(c.get("len", 0)) if c.get("len") else "-", fmt_size(c["size"])))
        self.count_lbl.configure(text=f"{len(self.visible)} de {len(self.proj.clips)} clips")

    @staticmethod
    def _key(clip):
        return (clip["file"], clip["pid"])

    def _selected(self):
        return [self.visible[int(i)] for i in self.tree.selection() if int(i) < len(self.visible)]

    def _on_select(self, _e=None):
        sel = self._selected()
        if not sel:
            return
        if self.cur is not sel[0]:
            self._stop()
        self.cur = sel[0]
        c = self.cur
        self.now_title.configure(text=c["name"])
        bits = ["mono" if c["ch"] == 1 else f'{c["ch"]} canales', f'{c["freq"]} Hz', fmt_size(c["size"]),
                COMP_NAMES.get(c.get("comp"), "?")]
        if c.get("len"):
            bits.append(fmt_time(c["len"]))
        extra = f"\n{os.path.basename(c['src'])}  ·  en {c['file']}" if c["src"] else f"\nen {c['file']}"
        if len(sel) > 1:
            extra += f"\n({len(sel)} clips seleccionados)"
        self.now_meta.configure(text="  ·  ".join(bits) + extra)
        self.time_lbl.configure(text=f"0:00 / {fmt_time(c.get('len', 0))}")
        self.play_bar.set(0)
        self._refresh_hint()

    def _refresh_hint(self):
        c = self.cur
        if not c:
            self.rep_hint.configure(text="Elegí un clip para ver su códec.", text_color=self.pal["SUB"])
            return
        orig = COMP_NAMES.get(c.get("comp"), "?")
        if self.codec.get().startswith("Vorbis"):
            if find_tool("fsbankcl"):
                txt, col = (f"Códec original: {orig}. Se importará como Vorbis (calidad {self.q.get()}) con "
                            f"fsbankcl: el archivo queda de tamaño parecido.", self.pal["SUB"])
            else:
                txt, col = (f"Códec original: {orig}. Falta fsbankcl: no se podrá importar en Vorbis "
                            f"(Ajustes > Dependencias).", self.pal["YELLOW"])
        else:
            txt, col = (f"Códec original: {orig}. Se importará como PCM de 16 bits (sin dependencias; "
                        f"el archivo crece).", self.pal["SUB"])
        self.rep_hint.configure(text=txt, text_color=col)

    # ---------------------------------------------------------------- reproducir (vista previa)
    def _backend(self):
        st = self._play
        if st["backend"] is None:
            try:
                import pygame
                pygame.mixer.init()
                st["backend"], st["lib"] = "pygame", pygame
            except Exception:
                try:
                    import winsound
                    st["backend"], st["lib"] = "winsound", winsound
                except Exception:
                    st["backend"] = "none"
        return st["backend"]

    def _toggle_play(self):
        if self._play["playing"]:
            self._stop()
            return
        c = self.cur
        if c is None or not self.proj:
            self.set_status("Elegí un clip para reproducir.")
            return
        if self._backend() == "none":
            self.set_status("No hay reproductor disponible (instalá pygame).")
            return
        if not find_tool("vgmstream-cli"):
            self.set_status("Falta vgmstream-cli para escuchar el clip (Ajustes > Dependencias).")
            return
        st = self._play
        st["token"] += 1
        token = st["token"]
        self.btn_play.configure(text="… preparando")

        def work():
            try:
                wav = self._preview_wav(c)
            except Exception as e:
                self.after(0, lambda: (self.btn_play.configure(text="▶ Reproducir"),
                                       self.set_status(f"No se pudo reproducir: {e}")))
                return
            self.after(0, lambda: self._start_play(c, wav, token))
        threading.Thread(target=work, daemon=True).start()

    def _preview_wav(self, clip):
        key = (clip["src"], clip["off"], clip["size"], clip["name"])
        if key in self._prev_cache and os.path.isfile(self._prev_cache[key]):
            return self._prev_cache[key]
        if self._prev_dir is None:
            self._prev_dir = tempfile.mkdtemp(prefix="dp2_prev_")
        raw = self.proj.raw_bytes(clip)
        fsb = os.path.join(self._prev_dir, f"{len(self._prev_cache)}.fsb")
        wav = fsb[:-4] + ".wav"
        with open(fsb, "wb") as f:
            f.write(raw)
        r = run([find_tool("vgmstream-cli"), "-o", wav, fsb])
        os.remove(fsb)
        if r.returncode != 0 or not os.path.isfile(wav):
            raise RuntimeError("vgmstream: " + r.stderr.decode(errors="ignore")[-200:])
        self._prev_cache[key] = wav
        return wav

    def _start_play(self, clip, wav, token):
        st = self._play
        if token != st["token"] or self.cur is not clip:
            self.btn_play.configure(text="▶ Reproducir")
            return
        try:
            if st["backend"] == "pygame":
                st["lib"].mixer.music.load(wav)
                st["lib"].mixer.music.play()
            else:
                st["lib"].PlaySound(wav, st["lib"].SND_FILENAME | st["lib"].SND_ASYNC)
        except Exception as e:
            self.btn_play.configure(text="▶ Reproducir")
            self.set_status(f"No se pudo reproducir: {e}")
            return
        st["playing"] = True
        st["start"] = time.monotonic()
        self.btn_play.configure(text="❚❚ Pausar" if False else "■ Detener")
        self._tick()

    def _tick(self):
        st = self._play
        if not st["playing"]:
            return
        total = (self.cur or {}).get("len", 0) or 0
        el = time.monotonic() - st["start"]
        busy = True
        if st["backend"] == "pygame":
            try:
                busy = bool(st["lib"].mixer.music.get_busy())
            except Exception:
                busy = False
        if (total and el >= total + 0.3) or not busy:
            self._stop()
            return
        self.play_bar.set(min(1.0, el / total) if total else 0)
        self.time_lbl.configure(text=f"{fmt_time(el)} / {fmt_time(total)}")
        st["job"] = self.after(150, self._tick)

    def _stop(self):
        st = self._play
        st["token"] += 1
        if st["job"]:
            try:
                self.after_cancel(st["job"])
            except Exception:
                pass
            st["job"] = None
        if st["playing"]:
            try:
                if st["backend"] == "pygame":
                    st["lib"].mixer.music.stop()
                elif st["backend"] == "winsound":
                    st["lib"].PlaySound(None, st["lib"].SND_PURGE)
            except Exception:
                pass
        st["playing"] = False
        try:
            self.btn_play.configure(text="▶ Reproducir")
            self.play_bar.set(0)
            total = (self.cur or {}).get("len", 0) or 0
            self.time_lbl.configure(text=f"0:00 / {fmt_time(total)}")
        except Exception:
            pass

    def destroy(self):
        self._stop()
        if self._prev_dir:
            shutil.rmtree(self._prev_dir, ignore_errors=True)
        super().destroy()

    # ---------------------------------------------------------------- acciones
    def do_extract(self, all_=False):
        if not self.proj:
            return
        clips = list(self.visible) if all_ else self._selected()
        if not clips:
            messagebox.showinfo("Extraer", "No hay clips seleccionados.")
            return
        out = filedialog.askdirectory(title="Carpeta de salida")
        if not out:
            return
        fmt = self.fmt.get()

        def one(c):
            try:
                self.proj.extract(c, out, fmt)
                return None
            except Exception as e:
                return f"{c['name']}: {e}"

        def work():
            errs, n = [], 0
            with ThreadPoolExecutor(max_workers=4) as ex:
                for r in ex.map(one, clips):
                    n += 1
                    if r:
                        errs.append(r)
                    self.report(f"Extrayendo {n}/{len(clips)}", n / len(clips))
            self.finish("Extracción", len(clips) - len(errs), errs, out)
        threading.Thread(target=work, daemon=True).start()

    def do_replace(self):
        sel = self._selected()
        if not self.proj or len(sel) != 1:
            messagebox.showinfo("Reemplazar", "Elegí un solo clip en la lista.")
            return
        f = filedialog.askopenfilename(title="Audio nuevo",
                                       filetypes=[("Audio", " ".join("*" + e for e in AUDIO_EXT)),
                                                  ("Todos", "*.*")])
        if f:
            self.run_replace([(sel[0], f)])

    def do_replace_folder(self):
        if not self.proj:
            return
        d = filedialog.askdirectory(title="Carpeta con audios (mismo nombre que el clip)")
        if not d:
            return
        files = {os.path.splitext(n)[0].lower(): os.path.join(d, n)
                 for n in os.listdir(d) if n.lower().endswith(AUDIO_EXT)}
        items = [(c, files[safe(c["name"]).lower()]) for c in self.proj.clips
                 if safe(c["name"]).lower() in files]
        if not items:
            messagebox.showinfo("Reemplazar", "Ningún archivo coincide con el nombre de un clip.")
            return
        if messagebox.askyesno("Reemplazar", f"Se reemplazarán {len(items)} clips. ¿Continuar?"):
            self.run_replace(items)

    def run_replace(self, items):
        self._stop()
        self._prev_cache.clear()
        self.proj.opts = {"codec": "vorbis" if self.codec.get().startswith("Vorbis") else "pcm",
                          "quality": self.q.get(), "loop": self.loop.get(), "native": self.native.get()}

        def work():
            try:
                ok, errs = self.proj.replace_many(items, self.report)
                bad = {e.split(":")[0] for e in errs}
                for c, _f in items:
                    if c["name"] not in bad:
                        self.replaced.add(self._key(c))
                self.finish("Reemplazo", ok, errs)
                self.after(0, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=work, daemon=True).start()


def main():
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("DP2 Audio Tool - Unity 2018.4.16f1")
    root.geometry("1100x700")
    root.minsize(520, 420)
    DP2Panel(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
