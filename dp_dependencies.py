#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descargador de dependencias de DP Audio Studio.

Los programas de terceros NO viajan con el proyecto: el usuario los baja desde Ajustes y quedan en assets\\.

  * assets.zip (MediaFire)  -> xma2encode.exe, WMAEncodeRS.exe (+ lo demas que traiga el paquete)
  * ffmpeg / ffprobe / ffplay -> build oficial de Windows (gyan.dev; BtbN en GitHub como respaldo)

Solo usa la libreria estandar. El .zip se extrae con Python puro (se detecta por el contenido, no por la extension); si algun dia el
paquete vuelve a ser .rar hace falta 7-Zip, WinRAR/UnRAR o el tar de Windows 11.
"""
import base64
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

# ----------------------------------------------------------------------------------------------
#  Origenes (cambiar aqui si cambian los enlaces)
# ----------------------------------------------------------------------------------------------
MEDIAFIRE_URL = "https://www.mediafire.com/file/2378iaje8ylk8rt/assets.zip/file"
FFMPEG_URLS = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
)
FFMPEG_FILES = ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe")
MEDIAFIRE_FILES = ("xma2encode.exe", "WMAEncodeRS.exe")      # los que usa el programa
# Deadly Premonition 2 (Unity / FSB5): fsbankcl.exe (+ sus DLL) para importar en Vorbis. Si el paquete se sube
# como .zip se descomprime sin programas extra; si es .rar hace falta 7-Zip/WinRAR (ver extract_rar).
MEDIAFIRE2_URL = "https://www.mediafire.com/file/ko8xk3pl7n9ex5k/assets2.rar/file"
DP2_FILES = ("fsbankcl.exe", "libfsbvorbis.dll", "Qt5Core.dll")
# vgmstream-cli decodifica los FSB5 (para extraer a WAV/OGG/MP3); se baja del GitHub oficial.
VGMSTREAM_URLS = (
    "https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip",
    "https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win.zip",
)
VGMSTREAM_FILES = ("vgmstream-cli.exe",)
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class DepError(Exception):
    pass


class Cancelled(Exception):
    pass


# ----------------------------------------------------------------------------------------------
#  Estado
# ----------------------------------------------------------------------------------------------
def _have(assets_dir, name):
    if (Path(assets_dir) / name).is_file():
        return True
    return bool(shutil.which(name) or shutil.which(Path(name).stem))


def missing(assets_dir):
    """{'ffmpeg', 'mediafire', 'dp2', 'vgmstream'} -> archivos que faltan (ni en assets ni en el PATH)."""
    return {"ffmpeg": [n for n in FFMPEG_FILES if not _have(assets_dir, n)],
            "mediafire": [n for n in MEDIAFIRE_FILES if not _have(assets_dir, n)],
            "dp2": [n for n in DP2_FILES if not _have(assets_dir, n)],
            "vgmstream": [n for n in VGMSTREAM_FILES if not _have(assets_dir, n)]}


def status_lines(assets_dir):
    """[(nombre, presente)] para mostrar en la interfaz."""
    return [(n, _have(assets_dir, n)) for n in FFMPEG_FILES + MEDIAFIRE_FILES + DP2_FILES + VGMSTREAM_FILES]


# ----------------------------------------------------------------------------------------------
#  Descarga
# ----------------------------------------------------------------------------------------------
def _open(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    return urllib.request.urlopen(req, timeout=timeout)


def resolve_mediafire(page_url):
    """La pagina publica de MediaFire no es un enlace directo: se lee el HTML y se saca el del boton Download."""
    with _open(page_url) as r:
        page = r.read().decode("utf-8", "replace")
    m = re.search(r'data-scrambled-url="([^"]+)"', page)          # algunas paginas lo ofuscan en base64
    if m:
        try:
            return base64.b64decode(m.group(1)).decode("utf-8")
        except Exception:
            pass
    m = re.search(r'href="(https?://download[^"\s]*mediafire\.com/[^"\s]+)"', page)
    if m:
        return html.unescape(m.group(1))
    raise DepError("MediaFire no devolvió un enlace de descarga (¿el archivo fue borrado o la página cambió?).")


def download(url, dest, progress=None, cancel=None, label=""):
    """Baja url -> dest (via .part). progress(fraccion|None, texto)."""
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    with _open(url) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            raise DepError("El servidor devolvió una página web en vez del archivo.")
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(part, "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    mb = done / 1048576
                    if total:
                        progress(done / total, f"{label} {mb:.0f} / {total / 1048576:.0f} MB")
                    else:
                        progress(None, f"{label} {mb:.0f} MB")
    if total and done < total:
        raise DepError("La descarga quedó incompleta.")
    part.replace(dest)
    return dest


# ----------------------------------------------------------------------------------------------
#  Extraccion
# ----------------------------------------------------------------------------------------------
def _kind(path):
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"PK"):
        return "zip"
    if head.startswith(b"Rar!"):
        return "rar"
    return "unknown"


def _rar_tools():
    """[(nombre, comando_base)] en orden de preferencia."""
    pf = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramW6432")]
    out, seen = [], set()

    def add(kind, exe):
        if exe and str(exe) not in seen and Path(exe).is_file():
            seen.add(str(exe))
            out.append((kind, str(exe)))

    for n in ("7z", "7zz", "7za"):
        add("7z", shutil.which(n))
    for base in filter(None, pf):
        add("7z", Path(base) / "7-Zip" / "7z.exe")
        for n in ("UnRAR.exe", "Rar.exe"):
            add("unrar", Path(base) / "WinRAR" / n)
    for n in ("unrar", "UnRAR", "rar"):
        add("unrar", shutil.which(n))
    for n in ("bsdtar", "tar"):             # tar.exe de Windows 11 (libarchive) lee .rar; el GNU tar no
        add("tar", shutil.which(n))
    return out


def extract_rar(rar, dest):
    tools = _rar_tools()
    if not tools:
        raise DepError("Para descomprimir el .rar hace falta 7-Zip o WinRAR (instalalo y volvé a probar). "
                       "Alternativa: subir el paquete como .zip, que se descomprime sin programas extra.")
    last = ""
    for kind, exe in tools:
        if kind == "7z":
            cmd = [exe, "x", "-y", f"-o{dest}", str(rar)]
        elif kind == "unrar":
            cmd = [exe, "x", "-y", "-o+", str(rar), str(dest) + os.sep]
        else:
            cmd = [exe, "-xf", str(rar), "-C", str(dest)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=600,
                               creationflags=NOWIN)
        except (OSError, subprocess.SubprocessError) as ex:
            last = str(ex)
            continue
        if r.returncode == 0 and any(Path(dest).rglob("*.exe")):
            return
        last = (r.stderr or r.stdout or "").strip()[-300:]
    raise DepError("No se pudo descomprimir el .rar con las herramientas encontradas. " + last)


def _copy_tree(src, dst):
    """Copia src -> dst; si src tiene una sola carpeta raiz (p.ej. assets/) la quita."""
    src = Path(src)
    kids = list(src.iterdir())
    if len(kids) == 1 and kids[0].is_dir():
        src = kids[0]
    n = 0
    for p in src.rglob("*"):
        if p.is_file():
            target = Path(dst) / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            n += 1
    return n


def extract_ffmpeg_zip(zip_path, assets_dir):
    got = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            base = Path(info.filename).name.lower()
            if base in FFMPEG_FILES and not info.is_dir():
                target = Path(assets_dir) / base
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                got.append(base)
    if sorted(got) != sorted(FFMPEG_FILES):
        raise DepError("El zip de ffmpeg no trae ffmpeg.exe, ffprobe.exe y ffplay.exe.")


def extract_vgmstream_zip(zip_path, assets_dir):
    """Saca vgmstream-cli.exe y las DLL de codecs (planas, en assets); ignora los plugins de reproductores."""
    got = set()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            base = Path(info.filename).name
            low = base.lower()
            if info.is_dir() or not (low == "vgmstream-cli.exe" or low.endswith(".dll")):
                continue
            if low.startswith(("in_vgmstream", "xmp-vgmstream", "foo_")):
                continue
            with z.open(info) as src, open(Path(assets_dir) / base, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            got.add(low)
    if "vgmstream-cli.exe" not in got:
        raise DepError("El zip de vgmstream no trae vgmstream-cli.exe.")


# ----------------------------------------------------------------------------------------------
#  Flujo completo (se llama desde un hilo)
# ----------------------------------------------------------------------------------------------
def install_all(assets_dir, progress=None, cancel=None, log=None):
    """Baja lo que falte. Devuelve (instalados, errores). progress(fraccion|None, texto); log(texto)."""
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    need = missing(assets_dir)
    steps = [k for k in ("mediafire", "ffmpeg", "dp2", "vgmstream") if need[k]]
    names = {"mediafire": "assets", "ffmpeg": "ffmpeg", "dp2": "assets2 (DP2)", "vgmstream": "vgmstream"}
    ok, errors = [], []
    say = log or (lambda s: None)
    for i, step in enumerate(steps):
        def prog(frac, text, i=i):
            if progress:
                progress(None if frac is None else (i + frac * 0.8) / len(steps), text)
        tmp = Path(tempfile.mkdtemp(prefix="dp_deps_"))
        try:
            if step in ("mediafire", "dp2"):
                say("MediaFire: resolviendo enlace…")
                url = resolve_mediafire(MEDIAFIRE_URL if step == "mediafire" else MEDIAFIRE2_URL)
                pkg = download(url, tmp / "assets.pkg", prog, cancel, names[step])
                kind = _kind(pkg)
                if progress:
                    progress((i + 0.85) / len(steps), "assets: descomprimiendo…")
                out = tmp / "out"
                out.mkdir()
                if kind == "zip":
                    with zipfile.ZipFile(pkg) as z:
                        z.extractall(out)
                elif kind == "rar":
                    extract_rar(pkg, out)
                else:
                    raise DepError("El archivo descargado no es ni .zip ni .rar.")
                n = _copy_tree(out, assets_dir)
                say(f"{names[step]}: {n} archivo(s) copiados.")
                if step == "dp2":
                    still = [f for f in DP2_FILES if not (assets_dir / f).is_file()]
                    if still:
                        raise DepError("el paquete no trajo: " + ", ".join(still))
                ok.append(names[step])
            elif step == "vgmstream":
                last = None
                for url in VGMSTREAM_URLS:
                    try:
                        say("vgmstream: descargando de GitHub…")
                        pkg = download(url, tmp / "vgmstream.zip", prog, cancel, "vgmstream")
                        if progress:
                            progress((i + 0.85) / len(steps), "vgmstream: descomprimiendo…")
                        extract_vgmstream_zip(pkg, assets_dir)
                        last = None
                        break
                    except Cancelled:
                        raise
                    except Exception as ex:
                        last = ex
                        say(f"vgmstream: falló ({ex}); probando otra fuente…")
                if last is not None:
                    raise last
                ok.append("vgmstream")
            else:
                last = None
                for url in FFMPEG_URLS:
                    try:
                        say("ffmpeg: descargando " + url.split("/")[2] + "…")
                        pkg = download(url, tmp / "ffmpeg.zip", prog, cancel, "ffmpeg")
                        if progress:
                            progress((i + 0.85) / len(steps), "ffmpeg: descomprimiendo…")
                        extract_ffmpeg_zip(pkg, assets_dir)
                        last = None
                        break
                    except Cancelled:
                        raise
                    except Exception as ex:
                        last = ex
                        say(f"ffmpeg: falló ({ex}); probando otra fuente…")
                if last is not None:
                    raise last
                ok.append("ffmpeg")
        except Cancelled:
            errors.append("Cancelado.")
            break
        except Exception as ex:
            errors.append(f"{names[step]}: {ex}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if progress:
        progress(1.0, "")
    return ok, errors


def run_in_thread(assets_dir, on_progress, on_log, on_done, cancel):
    """Arranca install_all en un hilo; los callbacks se llaman desde ese hilo (usar una cola en la GUI)."""
    def work():
        try:
            res = install_all(assets_dir, on_progress, cancel, on_log)
        except Exception as ex:
            res = ([], [str(ex)])
        on_done(*res)
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t
