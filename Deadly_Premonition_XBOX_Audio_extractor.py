#!/usr/bin/env python3
"""
dp_xwb_gui.py - GUI (Tkinter) para el toolkit XACT WaveBank/SoundBank de Deadly Premonition

Autores: Retr0_Nowt/ie + Dmytro Bidlov

Misma logica que dp_xwb_tool.py (CLI), embebida aca para que el archivo sea
autocontenido. Requiere ffmpeg en PATH para la pestana "Procesar".

Pestanas:
    Banco      - carga un .xwb (autodetecta el .xsb pareja), lista TODAS las entradas
                 del wavebank con su nombre de cue (editable a mano, con Aplicar/Limpiar
                 para las entradas mal nombreadas o sin cue), y extrae una o todas a .wav/.xma
    Procesar   - convierte un audio cualquiera a MS-ADPCM con ffmpeg
    Inyectar   - reemplaza una entrada del .xwb por un .wav
    Lote       - inyeccion masiva por manifiesto + recorte de audio
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
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------------------------------------------------------
# Paleta Catppuccin Mocha
# ---------------------------------------------------------------------------

BASE = "#1e1e2e"
MANTLE = "#181825"
SURFACE0 = "#313244"
SURFACE1 = "#45475a"
TEXT = "#cdd6f4"
SUBTEXT = "#a6adc8"
MAUVE = "#cba6f7"
GREEN = "#a6e3a1"
RED = "#f38ba8"
YELLOW = "#f9e2af"

# ---------------------------------------------------------------------------
# Logica de formato XACT (identica a dp_xwb_tool.py)
# ---------------------------------------------------------------------------

SEG_BANKDATA, SEG_ENTRYMETADATA, SEG_SEEKTABLES, SEG_ENTRYNAMES, SEG_ENTRYWAVEDATA = range(5)
FMT_PCM, FMT_XMA, FMT_ADPCM, FMT_WMA = range(4)
FMT_NAMES = {FMT_PCM: "PCM", FMT_XMA: "XMA", FMT_ADPCM: "ADPCM", FMT_WMA: "WMA"}

# ---------------------------------------------------------------------------
# Traducciones de la interfaz: espanol / ucraniano / ingles (solo textos
# estaticos de labels/botones/columnas/pestanas; los logs y mensajes de error
# dinamicos quedan en espanol).
# ---------------------------------------------------------------------------
TR = {
    "app_title": {"es": "DP XWB Toolkit", "uk": "DP XWB Toolkit", "en": "DP XWB Toolkit"},
    "interface_lang": {"es": "Idioma de la interfaz:", "uk": "Мова інтерфейсу:", "en": "Interface language:"},
    "tab_bank": {"es": "Banco", "uk": "Банк", "en": "Bank"},
    "tab_process": {"es": "Procesar", "uk": "Обробка", "en": "Process"},
    "tab_inject": {"es": "Inyectar", "uk": "Інʼєкція", "en": "Inject"},
    "tab_batch": {"es": "Lote", "uk": "Пакет", "en": "Batch"},
    "status_ready": {"es": "Listo.", "uk": "Готово.", "en": "Ready."},

    "xwb_label": {"es": ".xwb:", "uk": ".xwb:", "en": ".xwb:"},
    "xsb_bank_label": {"es": "Banco en el .xsb:", "uk": "Банк у .xsb:", "en": "Bank in the .xsb:"},
    "xsb_label": {"es": ".xsb (pareja):", "uk": ".xsb (пара):", "en": ".xsb (pair):"},
    "load_bank_btn": {"es": "Cargar banco", "uk": "Завантажити банк", "en": "Load bank"},
    "col_index": {"es": "Indice", "uk": "Індекс", "en": "Index"},
    "col_name": {"es": "Nombre", "uk": "Імʼя", "en": "Name"},
    "col_format": {"es": "Formato", "uk": "Формат", "en": "Format"},
    "col_duration": {"es": "Duracion", "uk": "Тривалість", "en": "Duration"},
    "selected_name_label": {"es": "Nombre de la entrada seleccionada:", "uk": "Імʼя вибраного запису:", "en": "Selected entry name:"},
    "apply_btn": {"es": "Aplicar", "uk": "Застосувати", "en": "Apply"},
    "clear_btn": {"es": "Limpiar", "uk": "Очистити", "en": "Clear"},
    "extract_selected_btn": {"es": "Extraer entrada seleccionada", "uk": "Витягти вибраний запис", "en": "Extract selected entry"},
    "extract_all_btn": {"es": "Extraer TODO el banco...", "uk": "Витягти ВЕСЬ банк...", "en": "Extract ENTIRE bank..."},
    "link_folder_btn": {"es": "Vincular carpeta (informe)...", "uk": "Зв'язати теку (звіт)...", "en": "Link folder (report)..."},
    "extract_folder_btn": {"es": "Extraer carpeta completa...", "uk": "Витягти всю теку...", "en": "Extract entire folder..."},
    "export_format_label": {"es": "Formato de extraccion:", "uk": "Формат експорту:", "en": "Export format:"},
    "export_format_raw": {"es": "Sin decodificar (mas chico)", "uk": "Без декодування (менше)", "en": "Undecoded (smallest)"},
    "export_format_wav": {"es": "WAV PCM (ffmpeg)", "uk": "WAV PCM (ffmpeg)", "en": "WAV PCM (ffmpeg)"},
    "export_format_ogg": {"es": "OGG Vorbis (chico, ffmpeg)", "uk": "OGG Vorbis (компактно, ffmpeg)", "en": "OGG Vorbis (small, ffmpeg)"},
    "export_format_mp3": {"es": "MP3 (chico, ffmpeg)", "uk": "MP3 (компактно, ffmpeg)", "en": "MP3 (small, ffmpeg)"},

    "proc_input_label": {"es": "Audio de entrada:", "uk": "Вхідний аудіофайл:", "en": "Input audio:"},
    "proc_sr_label": {"es": "Sample rate:", "uk": "Частота дискретизації:", "en": "Sample rate:"},
    "proc_ch_label": {"es": "Canales:", "uk": "Канали:", "en": "Channels:"},
    "proc_ba_label": {"es": "Block align (potencia de 2):", "uk": "Block align (степінь 2):", "en": "Block align (power of 2):"},
    "proc_convert_btn": {"es": "Convertir a MS-ADPCM...", "uk": "Конвертувати в MS-ADPCM...", "en": "Convert to MS-ADPCM..."},

    "inject_xwb_label": {"es": ".xwb original:", "uk": "Вихідний .xwb:", "en": "Original .xwb:"},
    "inject_index_label": {"es": "Indice a reemplazar:", "uk": "Індекс для заміни:", "en": "Index to replace:"},
    "inject_index_hint": {"es": "(se autocompleta si elegis una entrada en la pestana Banco)",
                           "uk": "(заповнюється автоматично при виборі запису у вкладці «Банк»)",
                           "en": "(auto-filled when you pick an entry in the Bank tab)"},
    "inject_wav_label": {"es": ".wav de reemplazo:", "uk": "Файл .wav для заміни:", "en": "Replacement .wav:"},
    "inject_use_last_btn": {"es": "Usar el ultimo procesado", "uk": "Використати останній оброблений", "en": "Use last processed"},
    "inject_convert_wma_btn": {"es": "Convertir .wma (WMAEncodeRS) a .xwma...", "uk": "Конвертувати .wma (WMAEncodeRS) в .xwma...", "en": "Convert .wma (WMAEncodeRS) to .xwma..."},
    "inject_btn": {"es": "Inyectar y guardar como...", "uk": "Інʼєктувати і зберегти як...", "en": "Inject and save as..."},
    "wma_frame_title": {"es": "Auto-encodear .wav a WMA Pro/Standard (WMAEncodeRS.exe)",
                         "uk": "Автокодування .wav у WMA Pro/Standard (WMAEncodeRS.exe)",
                         "en": "Auto-encode .wav to WMA Pro/Standard (WMAEncodeRS.exe)"},
    "wma_encoder_label": {"es": "Encoder:", "uk": "Кодувальник:", "en": "Encoder:"},
    "wma_src_label": {"es": ".wav fuente:", "uk": "Вихідний .wav:", "en": "Source .wav:"},
    "wma_codec_label": {"es": "Codec:", "uk": "Кодек:", "en": "Codec:"},
    "wma_bitrate_label": {"es": "Bitrate:", "uk": "Бітрейт:", "en": "Bitrate:"},
    "wma_auto_hint": {"es": "Canales/sample rate se toman automaticamente del indice y .xwb de arriba.",
                       "uk": "Канали/частота беруться автоматично з індексу та .xwb вище.",
                       "en": "Channels/sample rate are taken automatically from the index and .xwb above."},
    "wma_encode_btn": {"es": "Encodear y usar como reemplazo", "uk": "Закодувати і використати як заміну", "en": "Encode and use as replacement"},

    "batch_xwb_label": {"es": ".xwb original:", "uk": "Вихідний .xwb:", "en": "Original .xwb:"},
    "batch_manifest_label": {"es": "Manifiesto (.json, entryNNN -> indice N):",
                              "uk": "Маніфест (.json, entryNNN -> індекс N):",
                              "en": "Manifest (.json, entryNNN -> index N):"},
    "batch_folder_label": {"es": "Carpeta con los .wav/.xwma (entryNNN.wav):",
                            "uk": "Тека з .wav/.xwma (entryNNN.wav):",
                            "en": "Folder with .wav/.xwma (entryNNN.wav):"},
    "batch_dry_run_btn": {"es": "Simular (solo reporte, no escribe nada)",
                           "uk": "Симуляція (лише звіт, нічого не записується)",
                           "en": "Dry run (report only, writes nothing)"},
    "batch_run_btn": {"es": "Inyectar por lote y guardar como...", "uk": "Пакетна інʼєкція і зберегти як...", "en": "Batch inject and save as..."},
    "trim_frame_title": {"es": "Recortar un .wav (siempre antes de codificar a ADPCM/WMA)",
                          "uk": "Обрізати .wav (завжди перед кодуванням в ADPCM/WMA)",
                          "en": "Trim a .wav (always before encoding to ADPCM/WMA)"},
    "trim_src_label": {"es": ".wav fuente:", "uk": "Вихідний .wav:", "en": "Source .wav:"},
    "trim_start_label": {"es": "Inicio (seg):", "uk": "Початок (сек):", "en": "Start (sec):"},
    "trim_end_label": {"es": "Fin (seg):", "uk": "Кінець (сек):", "en": "End (sec):"},
    "trim_auto_check": {"es": "Recortar silencio automatico (si se dejan Inicio/Fin vacios; aproximado)",
                         "uk": "Автообрізання тиші (якщо Початок/Кінець порожні; приблизно)",
                         "en": "Auto-trim silence (if Start/End left empty; approximate)"},
    "trim_btn": {"es": "Recortar y guardar como...", "uk": "Обрізати і зберегти як...", "en": "Trim and save as..."},

    "xma_frame_title": {"es": "XMA2 (xma2encode.exe de Microsoft) para entradas XMA",
                         "uk": "XMA2 (xma2encode.exe від Microsoft) для записів XMA",
                         "en": "XMA2 (Microsoft xma2encode.exe) for XMA entries"},
    "xma_encoder_label": {"es": "xma2encode:", "uk": "xma2encode:", "en": "xma2encode:"},
    "xma_mode_label": {"es": "Modo:", "uk": "Режим:", "en": "Mode:"},
    "xma_quality_label": {"es": "Calidad:", "uk": "Якість:", "en": "Quality:"},
    "xma_block_label": {"es": "Bloque (KB):", "uk": "Блок (КБ):", "en": "Block (KB):"},
    "xma_hint": {"es": "auto = XMA2 si hay encoder, si no PCM. Tambien acepta .wav XMA2 ya codificados.",
                  "uk": "auto = XMA2 якщо є кодувальник, інакше PCM. Також приймає готові .wav XMA2.",
                  "en": "auto = XMA2 if the encoder is found, otherwise PCM. Also accepts ready-made XMA2 .wav files."},

    "browse_btn": {"es": "...", "uk": "...", "en": "..."},
}

ADPCM_BLOCKALIGN_OFFSET = 22
MS_ADPCM_COEFFS = [(256, 0), (512, -256), (0, 0), (192, 64), (240, 0), (460, -208), (392, -232)]

# Los wavebanks de STREAMING (flags bit 0 = 1, todos los bancos grandes de DP:DC:
# voice*, bgm, scnd*, stse, strse, voicese) exigen que el offset absoluto de cada
# entrada este alineado a sector de 2048 bytes: XACT3 los lee con I/O sin buffer
# (CreateStreamingWaveBank) y un offset desalineado crashea el juego. Los bancos
# originales cumplen esto (verificado: 0 entradas desalineadas en los 12 bancos);
# inyectar empaquetando las entradas "pegadas" (sin padding) era lo que rompia todo.
STREAM_ALIGN = 2048

# Tablas oficiales de xwbtool.cpp (Microsoft DirectXTK) para decodificar/codificar
# el campo wBlockAlign (8 bits) de un MINIWAVEFORMAT con wFormatTag=WMA:
#   bits 0-4 (5 bits) -> indice en WMA_BLOCK_ALIGN
#   bits 5-7 (3 bits) -> indice en WMA_AVG_BYTES_PER_SEC
WMA_BLOCK_ALIGN = [929, 1487, 1280, 2230, 8917, 8192, 4459, 5945,
                   2304, 1536, 1485, 1008, 2731, 4096, 6827, 5462, 1280]
WMA_AVG_BYTES_PER_SEC = [12000, 24000, 4000, 6000, 8000, 20000, 2500]
WAVE_FORMAT_WMAUDIO2 = 0x0161
WAVE_FORMAT_WMAUDIO3 = 0x0162
WAVE_FORMAT_XMA2 = 0x0166
AUTO_BANK_LABEL = "(automatico)"


class WaveBank:
    def __init__(self, path):
        self.path = path
        self.data = bytearray(open(path, "rb").read())
        magic = bytes(self.data[0:4])
        if magic == b"WBND":
            self.e = "<"  # PC / Director's Cut: little-endian, magic literal "WBND"
        elif magic == b"DNBW":
            self.e = ">"  # Xbox 360 original: big-endian, magic bytes reversed "DNBW"
        else:
            raise ValueError(f"{path}: firma inesperada (se esperaba 'WBND' o 'DNBW')")
        self.version, self.header_version = struct.unpack(f"{self.e}II", self.data[4:12])
        self.segments = []
        pos = 12
        for _ in range(5):
            off, length = struct.unpack(f"{self.e}II", self.data[pos:pos + 8])
            self.segments.append([off, length])
            pos += 8
        bd_off, _ = self.segments[SEG_BANKDATA]
        self.flags, self.entry_count = struct.unpack(f"{self.e}II", self.data[bd_off:bd_off + 8])
        self.bank_name = bytes(self.data[bd_off + 8:bd_off + 72]).rstrip(b"\x00").decode("ascii", "replace")
        self.elemsize, self.alignment = struct.unpack(f"{self.e}II", self.data[bd_off + 72:bd_off + 80])
        if self.elemsize != 24:
            raise ValueError(f"elemsize={self.elemsize}: solo soportado el formato no-compacto (24 bytes)")
        self.entries = self._parse_entries()

    def _parse_entries(self):
        entrymeta_off, _ = self.segments[SEG_ENTRYMETADATA]
        seek_off, seek_len = self.segments[SEG_SEEKTABLES]
        seek_table_bytes = {}
        if seek_len >= self.entry_count * 4:
            seek_offsets = struct.unpack(f"{self.e}{self.entry_count}I", self.data[seek_off:seek_off + self.entry_count * 4])
            data_start = seek_off + self.entry_count * 4
            for i, rel_off in enumerate(seek_offsets):
                abs_off = data_start + rel_off
                if abs_off + 4 > seek_off + seek_len:
                    continue
                count = struct.unpack(f"{self.e}I", self.data[abs_off:abs_off + 4])[0]
                chunk_len = 4 + count * 4
                if abs_off + chunk_len > seek_off + seek_len:
                    continue
                seek_table_bytes[i] = bytes(self.data[abs_off:abs_off + chunk_len])
        entries = []
        for i in range(self.entry_count):
            base = entrymeta_off + i * 24
            flags_dur = struct.unpack(f"{self.e}I", self.data[base:base + 4])[0]
            miniformat = struct.unpack(f"{self.e}I", self.data[base + 4:base + 8])[0]
            play_off, play_len = struct.unpack(f"{self.e}II", self.data[base + 8:base + 16])
            loop_start, loop_total = struct.unpack(f"{self.e}II", self.data[base + 16:base + 24])
            entries.append({
                "flags": flags_dur & 0xF, "duration": flags_dur >> 4,  # xact3wb.h: Flags:4 (bajos) | Duration:28 (altos)
                "miniformat": miniformat, "play_off": play_off, "play_len": play_len,
                "loop_start": loop_start, "loop_total": loop_total,
                "seek_data": seek_table_bytes.get(i, b""),
                **decode_miniformat(miniformat),
            })
        return entries

    def wave_bytes(self, entry):
        wavedata_off, _ = self.segments[SEG_ENTRYWAVEDATA]
        start = wavedata_off + entry["play_off"]
        return bytes(self.data[start:start + entry["play_len"]])


def decode_miniformat(mini):
    format_tag = mini & 0x3
    channels = (mini >> 2) & 0x7
    sample_rate = (mini >> 5) & 0x3FFFF
    blockalign_field = (mini >> 23) & 0xFF
    bits_flag = (mini >> 31) & 0x1
    extra = {}
    if format_tag == FMT_PCM:
        block_align, bits = blockalign_field, (16 if bits_flag else 8)
    elif format_tag == FMT_ADPCM:
        block_align, bits = (blockalign_field + ADPCM_BLOCKALIGN_OFFSET) * channels, 4
    elif format_tag == FMT_WMA:
        ba_idx, bps_idx = blockalign_field & 0x1F, (blockalign_field >> 5) & 0x7
        block_align = WMA_BLOCK_ALIGN[ba_idx] if ba_idx < len(WMA_BLOCK_ALIGN) else 0
        avg_bytes_per_sec = WMA_AVG_BYTES_PER_SEC[bps_idx] if bps_idx < len(WMA_AVG_BYTES_PER_SEC) else 0
        bits = 16
        extra["avg_bytes_per_sec"] = avg_bytes_per_sec
        extra["wma_tag"] = WAVE_FORMAT_WMAUDIO3 if bits_flag else WAVE_FORMAT_WMAUDIO2
    else:  # XMA: sin suficiente info en el miniformat, requiere seek table (no implementado aun)
        block_align, bits = blockalign_field, 16
    return {"format_tag": format_tag, "channels": channels, "sample_rate": sample_rate,
            "block_align": block_align, "bits": bits, **extra}


def _xsb_header(data):
    """Cabecera comun de un XSB de XACT (SDBK = PC/little-endian, KBDS = Xbox 360/big-endian)."""
    magic = data[0:4]
    if magic == b"SDBK":
        e = "<"
    elif magic == b"KBDS":
        e = ">"
    else:
        raise ValueError(f"firma inesperada (se esperaba 'SDBK' o 'KBDS', hay {magic!r})")
    off = 4 + 6 + 8 + 1
    n_simple, n_complex, _unk, _n_total = struct.unpack(f"{e}HHHH", data[off:off + 8]); off += 8
    n_banks = data[off]; off += 1 + 2          # numWaveBanks (1) + numSounds (2)
    name_table_len = struct.unpack(f"{e}I", data[off:off + 4])[0]; off += 4
    hdr = struct.unpack(f"{e}8I", data[off:off + 32])
    # orden XACT3: simpleCues, complexCues, cueNames, ?, variationTables, ?, waveBankNames, hash...
    return dict(e=e, n_simple=n_simple, n_complex=n_complex, n_banks=n_banks, name_table_len=name_table_len,
                simple_off=hdr[0], complex_off=hdr[1], cue_names_off=hdr[2], bank_names_off=hdr[6])


def xsb_bank_names(path):
    """Nombres de los wavebanks que referencia un .xsb (p.ej. bgm.xsb -> bgm, prod, scnd, scnd2).
    Devuelve [] si el archivo no es un XSB de XACT."""
    try:
        data = open(path, "rb").read()
        h = _xsb_header(data)
        off = h["bank_names_off"]
        if off == 0xFFFFFFFF or off + 64 * h["n_banks"] > len(data):
            return []
        return [data[off + i * 64: off + (i + 1) * 64].split(b"\x00")[0].decode("ascii", "replace")
                for i in range(h["n_banks"])]
    except Exception:
        return []


def _xsb_sound_bank(data, e, sound_offset):
    """Indice del wavebank al que apunta un Sound (None si no se pudo determinar)."""
    flags = data[sound_offset]
    size = struct.unpack(f"{e}H", data[sound_offset + 7:sound_offset + 9])[0]
    if not flags & 1 or size == 12:
        return data[sound_offset + 11] if sound_offset + 11 < len(data) else None
    try:
        # Sound complejo: numClips (+9); cada clip = 9 bytes (volumen, offset u32, filtro); en clipOffset
        # hay numEvents y los eventos (u32 info, u16 random, payload). Evento 1 = Play Wave:
        # flags(1) ?(1) track(u16) wavebank(u8) loops(1) pan(4)
        clip_off = struct.unpack(f"{e}I", data[sound_offset + 11:sound_offset + 15])[0]
        n_events = data[clip_off]
        p = clip_off + 1
        for _ in range(n_events):
            info = struct.unpack(f"{e}I", data[p:p + 4])[0]
            p += 6
            if info & 0x1F == 1:
                return data[p + 4]
            break  # otro tipo de evento: layout distinto, no adivinamos
    except Exception:
        pass
    return None


def parse_xsb(path, bank_name=None):
    """Devuelve ({nombre_de_cue: indice_de_track}, cantidad_de_cues_complejos).

    Un .xsb puede referenciar VARIOS wavebanks (bgm.xsb de Director's Cut: bgm, prod, scnd, scnd2) y cada
    cue guarda (track, indice_de_banco). Si se pasa `bank_name` (el nombre interno del .xwb, o el del
    archivo) y el .xsb lo lista, solo se devuelven los cues de ESE banco: asi un .xwb se vincula solo
    con los nombres correctos. Si el .xsb tiene un unico banco o `bank_name` no figura, se devuelve todo
    como antes."""
    data = open(path, "rb").read()
    try:
        h = _xsb_header(data)
    except ValueError as ex:
        raise ValueError(f"{path}: {ex}")
    e = h["e"]
    pool = data[h["cue_names_off"]:h["cue_names_off"] + h["name_table_len"]]
    names = [n.decode("ascii", "replace") for n in pool.split(b"\x00") if n]
    banks = xsb_bank_names(path)
    want = None
    if bank_name and len(banks) > 1:
        low = [b.lower() for b in banks]
        if bank_name.lower() in low:
            want = low.index(bank_name.lower())
    mapping = {}
    for i in range(h["n_simple"]):
        cue_pos = h["simple_off"] + i * 5
        sound_offset = struct.unpack(f"{e}I", data[cue_pos + 1:cue_pos + 5])[0]
        # byte[0] es el flag del registro "Sound": bit0 = 1 si es un Sound "complejo".
        # El tamano del registro es un u16 en el endianness del archivo: big-endian (Xbox 360) deja el
        # byte util en +8, little-endian (PC) en +7 (leer siempre +8 daba tamano 0 en los XSB de PC y
        # rompia los indices de los cues complejos).
        sound_size = struct.unpack(f"{e}H", data[sound_offset + 7:sound_offset + 9])[0]
        flags = data[sound_offset]
        if flags & 1:
            if sound_size == 12:
                track_off = sound_offset + 9
            else:
                track_off = sound_offset + sound_size - 8
        else:
            # Sound SIMPLE: trackIndex fijo en offset+9 (2 bytes) y wavebank en offset+11
            track_off = sound_offset + 9
        if track_off + 2 > len(data):
            continue  # registro fuera de rango / formato no reconocido: se omite en vez de inventar un indice
        track_index = struct.unpack(f"{e}H", data[track_off:track_off + 2])[0]
        if want is not None:
            bank_idx = _xsb_sound_bank(data, e, sound_offset)
            if bank_idx is not None and bank_idx != want:
                continue
        name = names[i] if i < len(names) else f"<sin nombre {i}>"
        mapping[name] = track_index
    return mapping, h["n_complex"]


def find_paired_xsb_for(xwb_path):
    """Devuelve el Path del .xsb pareja de un .xwb (o None si no se encuentra).
    Orden: 1) mismo nombre base (bgm.xwb -> bgm.xsb); 2) el .xsb de la carpeta cuya tabla de wavebanks
    lista el nombre INTERNO del .xwb (scnd2.xwb -> bgm.xsb, porque bgm.xsb referencia
    bgm/prod/scnd/scnd2); 3) nombre contenido en el otro (voice4.xwb / voice.xsb)."""
    xwb_p = Path(xwb_path)
    candidate = xwb_p.with_suffix(".xsb")
    if candidate.is_file():
        return candidate
    wanted = {xwb_p.stem.lower()}
    try:
        wanted.add(WaveBank(str(xwb_p)).bank_name.lower())
    except Exception:
        pass
    wanted.discard("")
    for sibling in sorted(xwb_p.parent.glob("*.xsb")):
        if wanted & {b.lower() for b in xsb_bank_names(sibling)}:
            return sibling
    stem_lower = xwb_p.stem.lower()
    for sibling in sorted(xwb_p.parent.glob("*.xsb")):
        s_ = sibling.stem.lower()
        if s_ in stem_lower or stem_lower in s_:
            return sibling
    return None


def parse_xsb2(path):
    """Indice 'XSB2' (carpeta sound de Director's Cut, NO es un XSB de XACT): 'XSB2', cantidad (u32) y
    registros de 44 bytes: nombre[16], offset, size, sample_rate, canales, codec, 0, 0. Los datos son el
    .xwb de al lado, concatenados. Devuelve [dict(name, offset, size, rate, channels, codec)]."""
    data = open(path, "rb").read()
    if data[:4] != b"XSB2":
        raise ValueError(f"{path}: no es un indice XSB2")
    n = struct.unpack("<I", data[4:8])[0]
    out = []
    for i in range(n):
        o = 8 + i * 44
        name = data[o:o + 16].split(b"\x00")[0].decode("ascii", "replace")
        off, size, rate, ch, codec = struct.unpack("<5I", data[o + 16:o + 36])
        out.append(dict(name=name, offset=off, size=size, rate=rate, channels=ch, codec=codec))
    return out


def split_xsb2(xsb_path, blob_path, out_dir):
    """Parte el blob del XSB2 en un archivo por nombre (.bin, sin decodificar: el codec 5 no esta
    identificado)."""
    entries = parse_xsb2(xsb_path)
    blob = open(blob_path, "rb").read()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for e in entries:
        (out_dir / (Path(e["name"]).stem + ".bin")).write_bytes(blob[e["offset"]:e["offset"] + e["size"]])
    return len(entries)


def link_report(folder):
    """Informe de vinculos de una carpeta: que .xsb referencia que bancos y con que .xwb se enlaza cada
    uno (por el nombre INTERNO del .xwb), con comprobacion de rangos de track."""
    folder = Path(folder)
    lines = []
    xwbs = {}
    for f in sorted(folder.glob("*.xwb")):
        try:
            wb = WaveBank(str(f))
            xwbs[f] = (wb.bank_name or f.stem, wb.entry_count, wb)
        except Exception as ex:
            xwbs[f] = (None, 0, None)
    used = set()
    for xsb in sorted(folder.glob("*.xsb")):
        head = open(xsb, "rb").read(4)
        if head == b"XSB2":
            entries = parse_xsb2(xsb)
            blob = xsb.with_suffix(".xwb")
            tot = sum(e["size"] for e in entries)
            size = blob.stat().st_size if blob.is_file() else None
            lines.append(f"[{xsb.name}] indice XSB2 (no es XACT): {len(entries)} entradas, "
                         f"codecs {sorted({e['codec'] for e in entries})}, {sorted({e['rate'] for e in entries})} Hz")
            if size is None:
                lines.append(f"    FALTA {blob.name} (los datos)")
            else:
                used.add(blob)
                lines.append(f"    datos: {blob.name} ({size} bytes) {'OK: suma de tamanos coincide' if size == tot else f'ATENCION: suma={tot}'}")
            continue
        banks = xsb_bank_names(xsb)
        if not banks:
            lines.append(f"[{xsb.name}] formato no reconocido")
            continue
        lines.append(f"[{xsb.name}] referencia {len(banks)} wavebank(s): {', '.join(banks)}")
        for b in banks:
            cues, _ = parse_xsb(str(xsb), b) if len(banks) > 1 else parse_xsb(str(xsb))
            tracks = sorted(cues.values())
            match = [f for f, (nm, _n, _w) in xwbs.items() if nm and nm.lower() == b.lower()]
            if not match:
                match = [f for f in xwbs if f.stem.lower() == b.lower()]
            if not match:
                lines.append(f"    {b}: {len(cues)} cues -> FALTA el .xwb de este banco")
                continue
            f = match[0]
            used.add(f)
            n = xwbs[f][1]
            ok = (not tracks) or tracks[-1] < n
            lines.append(f"    {b}: {len(cues)} cues -> {f.name} ({n} entradas)"
                         + ("" if ok else f"  ATENCION: track maximo {tracks[-1]} >= {n}"))
    for f, (nm, n, _w) in xwbs.items():
        if f not in used:
            lines.append(f"[{f.name}] banco '{nm}' ({n} entradas): ningun .xsb de la carpeta lo referencia" if nm
                         else f"[{f.name}] firma de .xwb no reconocida (no es XACT)")
    return "\n".join(lines) if lines else "No se encontraron .xsb ni .xwb en la carpeta."


def riff_chunk(tag, body):
    body = bytes(body)
    return tag + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) & 1 else b"")


def build_wav_pcm(raw, channels, sample_rate, bits):
    block_align = channels * (bits // 8)
    byte_rate = sample_rate * block_align
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits)
    body = riff_chunk(b"fmt ", fmt) + riff_chunk(b"data", raw)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


def adpcm_samples_per_block(block_align, channels):
    return ((block_align - 7 * channels) * 8) // (4 * channels) + 2


def build_wav_adpcm(raw, channels, sample_rate, block_align):
    samples_per_block = adpcm_samples_per_block(block_align, channels)
    full_blocks, remainder = divmod(len(raw), block_align)
    total_samples = full_blocks * samples_per_block
    if remainder:
        total_samples += max(0, (remainder * 8 // (4 * channels)) + 2)
    byte_rate = (sample_rate // samples_per_block) * block_align if samples_per_block else 0
    fmt_body = struct.pack("<HHIIHH", 2, channels, sample_rate, byte_rate, block_align, 4)
    fmt_body += struct.pack("<HHH", 32, samples_per_block, len(MS_ADPCM_COEFFS))
    for c1, c2 in MS_ADPCM_COEFFS:
        fmt_body += struct.pack("<hh", c1, c2)
    fact_body = struct.pack("<I", total_samples)
    body = riff_chunk(b"fmt ", fmt_body) + riff_chunk(b"fact", fact_body) + riff_chunk(b"data", raw)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


def build_wav_xwma(raw, channels, sample_rate, block_align, avg_bytes_per_sec, wma_tag, dpds_raw):
    """RIFF/XWMA reproducible por ffmpeg y por XAudio2 (fmt + dpds + data)."""
    fmt_body = struct.pack("<HHIIHHH", wma_tag, channels, sample_rate, avg_bytes_per_sec, block_align, 16, 0)
    body = riff_chunk(b"fmt ", fmt_body) + riff_chunk(b"dpds", dpds_raw) + riff_chunk(b"data", raw)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"XWMA" + body


# GUIDs del formato ASF (Microsoft [MS-ASF] / ASF spec, formato mixed-endian estandar)
ASF_HEADER_OBJECT = "75b22630-668e-11cf-a6d9-00aa0062ce6c"
ASF_FILE_PROPERTIES_OBJECT = "8cabdca1-a947-11cf-8ee4-00c00c205365"
ASF_STREAM_PROPERTIES_OBJECT = "b7dc0791-a9b7-11cf-8ee6-00c00c205365"
ASF_DATA_OBJECT = "75b22636-668e-11cf-a6d9-00aa0062ce6c"
ASF_AUDIO_MEDIA = "f8699e40-5b4d-11cf-a8fd-00805f5c442b"


def convert_wma_to_xwma(wma_path):
    """Reempaqueta un .wma (ASF, generado p.ej. con WMAEncodeRS -c pro/standard) a RIFF/XWMA
    (fmt + dpds + data) SIN transcodificar: los frames comprimidos se copian tal cual, solo se
    quita el contenedor ASF y se reconstruye la tabla de seek (dpds) a partir de los
    presentation-time de cada paquete. Validado empiricamente: el audio decodificado del xwma
    resultante es indistinguible (ffmpeg) del decode directo del .wma original.
    Limitaciones: solo soporta streams de audio con un unico payload NO comprimido por
    paquete ASF (el caso normal para WMA CBR, que es como trabaja XACT/xWMA de todos modos)."""
    import uuid as _uuid
    data = open(wma_path, "rb").read()

    def guid(off):
        return str(_uuid.UUID(bytes_le=data[off:off + 16]))

    if guid(0) != ASF_HEADER_OBJECT:
        raise ValueError(f"{wma_path}: no es un archivo ASF/.wma valido (falta ASF_Header_Object)")
    header_size = struct.unpack("<Q", data[16:24])[0]
    num_objects = struct.unpack("<I", data[24:28])[0]

    file_props, stream_props = None, None
    pos = 30
    for _ in range(num_objects):
        obj_guid, obj_size = guid(pos), struct.unpack("<Q", data[pos + 16:pos + 24])[0]
        if obj_guid == ASF_FILE_PROPERTIES_OBJECT:
            file_props = pos
        elif obj_guid == ASF_STREAM_PROPERTIES_OBJECT:
            stream_type = guid(pos + 24)
            if stream_type == ASF_AUDIO_MEDIA:
                stream_props = pos
        pos += obj_size
    if pos != header_size:
        raise ValueError(f"{wma_path}: tamano de header ASF inconsistente ({pos} != {header_size})")
    if file_props is None or stream_props is None:
        raise ValueError(f"{wma_path}: no se encontro File Properties Object o un stream de audio")

    min_pkt, max_pkt = struct.unpack("<II", data[file_props + 92:file_props + 100])
    if min_pkt != max_pkt:
        raise ValueError(f"{wma_path}: paquetes ASF de tamano variable (min={min_pkt} max={max_pkt}), "
                          f"no soportado (se espera CBR estandar de un encoder xWMA-compatible)")
    pkt_size = min_pkt

    flags = struct.unpack("<H", data[stream_props + 72:stream_props + 74])[0]
    stream_number = flags & 0x7F
    ts_len = struct.unpack("<I", data[stream_props + 64:stream_props + 68])[0]
    tsd = data[stream_props + 78:stream_props + 78 + ts_len]
    wma_tag, channels, sample_rate, avg_bytes_per_sec, block_align, bits = struct.unpack("<HHIIHH", tsd[:16])
    if wma_tag not in (WAVE_FORMAT_WMAUDIO2, WAVE_FORMAT_WMAUDIO3):
        raise ValueError(f"{wma_path}: wFormatTag=0x{wma_tag:04x} no es WMA2/WMA3 (xWMA solo soporta esos dos)")
    avg_bytes_per_sec = snap_xwma_profile(block_align, avg_bytes_per_sec)
    if encode_wma_blockalign(block_align, avg_bytes_per_sec) is None:
        raise ValueError(
            f"{wma_path}: nBlockAlign={block_align} / nAvgBytesPerSec={avg_bytes_per_sec} no coinciden con "
            f"ningun perfil xWMA estandar de XACT. Re-codifica con un bitrate CBR estandar.")

    do_off = pos
    if guid(do_off) != ASF_DATA_OBJECT:
        raise ValueError(f"{wma_path}: no se encontro el Data Object justo despues del header")
    total_packets = struct.unpack("<Q", data[do_off + 40:do_off + 48])[0]
    pkt_base = do_off + 50

    frames, pres_times = [], []
    for i in range(total_packets):
        off = pkt_base + i * pkt_size
        ec_flags = data[off]
        p = off + 1 + ((ec_flags & 0x0F) if ec_flags & 0x80 else 0)
        length_type_flags, property_flags = data[p], data[p + 1]
        p += 2
        if length_type_flags & 0x01:
            raise ValueError(f"{wma_path}: paquete {i} tiene multiples payloads, no soportado")
        seq_type = (length_type_flags >> 1) & 0x3
        pad_type = (length_type_flags >> 3) & 0x3
        pkt_len_type = (length_type_flags >> 5) & 0x3
        repl_len_type = property_flags & 0x3
        obj_off_len_type = (property_flags >> 2) & 0x3
        obj_num_len_type = (property_flags >> 4) & 0x3
        sizes = {0: 0, 1: 1, 2: 2, 3: 4}
        p += sizes[pkt_len_type]  # Packet Length (no la necesitamos, pkt_size ya es fijo)
        p += sizes[seq_type]  # Sequence (no usado)
        pad_len = int.from_bytes(data[p:p + sizes[pad_type]], "little") if pad_type else 0
        p += sizes[pad_type]
        p += 4 + 2  # Send Time + Duration
        stream_num = data[p] & 0x7F
        p += 1
        p += sizes[obj_num_len_type]  # Media Object Number (no usado)
        p += sizes[obj_off_len_type]  # Offset Into Media Object (no usado; asumimos objeto completo)
        repl_len = int.from_bytes(data[p:p + sizes[repl_len_type]], "little") if repl_len_type else 0
        p += sizes[repl_len_type]
        if repl_len == 1:
            raise ValueError(f"{wma_path}: paquete {i} usa payload comprimido (sub-payloads), no soportado")
        if repl_len < 8:
            raise ValueError(f"{wma_path}: paquete {i} con Replicated Data Length={repl_len} inesperado")
        media_obj_size = struct.unpack("<I", data[p:p + 4])[0]
        pres_time = struct.unpack("<I", data[p + 4:p + 8])[0]
        p += repl_len
        if stream_num != stream_number:
            raise ValueError(f"{wma_path}: paquete {i} pertenece a otro stream ({stream_num}), "
                              f"solo se soporta un archivo con un unico stream de audio")
        frames.append(data[p:p + media_obj_size])
        pres_times.append(pres_time)

    raw = b"".join(frames)
    bytes_per_ms = channels * (bits // 8) * sample_rate / 1000
    t0 = pres_times[0]
    dpds_vals = []
    for i in range(len(pres_times)):
        t_next = pres_times[i + 1] if i + 1 < len(pres_times) else pres_times[i] + (pres_times[i] - pres_times[i - 1])
        dpds_vals.append(round((t_next - t0) * bytes_per_ms))
    dpds_raw = struct.pack(f"<{len(dpds_vals)}I", *dpds_vals)
    return build_wav_xwma(raw, channels, sample_rate, block_align, avg_bytes_per_sec, wma_tag, dpds_raw)


WMA_ENCODER_NAMES = ("WMAEncodeRS.exe", "WMAEncodeRS")
VALID_XWMA_BITRATES = (20, 32, 48, 64, 96, 160, 192)


def tool_search_dirs():
    """Carpetas donde buscar herramientas externas (ffmpeg, xma2encode, WMAEncodeRS): junto al exe, dentro del
    exe empaquetado (PyInstaller _MEIPASS), junto al script; cada una tambien con su subcarpeta 'tools'."""
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        dirs.append(Path(mei))
    dirs.append(Path(__file__).resolve().parent)
    out = []
    for d in dirs:
        for sub in (d, d / "assets", d / "tools"):
            if sub not in out:
                out.append(sub)
    return out


def find_tool(names):
    for d in tool_search_dirs():
        for n in names:
            if (d / n).is_file():
                return d / n
    return None


def ensure_ffmpeg_on_path():
    """Si ffmpeg no esta en el PATH pero viene con la herramienta (junto al exe o empaquetado), lo agrega."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    f = find_tool(("ffmpeg.exe", "ffmpeg"))
    if f:
        os.environ["PATH"] = str(f.parent) + os.pathsep + os.environ.get("PATH", "")
        return str(f)
    return None


def find_wma_encoder():
    """Busca WMAEncodeRS.exe junto al exe / script (o dentro del exe empaquetado)."""
    return find_tool(WMA_ENCODER_NAMES)


def run_wma_encoder(exe_path, wav_path, out_wma_path, codec="pro", bitrate=192,
                     channels=None, sample_rate=None):
    """Corre WMAEncodeRS.exe <wav> <out.wma> -c <codec> -b <bitrate> [--out-channels/-samplerate].
    Solo puede ejecutarse en Windows (requiere wmvcore.dll del sistema)."""
    if bitrate not in VALID_XWMA_BITRATES:
        raise ValueError(f"bitrate {bitrate} invalido; usa uno de {VALID_XWMA_BITRATES}")
    cmd = [str(exe_path), str(wav_path), str(out_wma_path), "-c", codec, "-b", str(bitrate), "-s"]
    if channels:
        cmd += ["--out-channels", str(channels)]
    if sample_rate:
        cmd += ["--out-samplerate", str(sample_rate)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"WMAEncodeRS fallo (codigo {result.returncode}):\n{result.stderr or result.stdout}")
    if not Path(out_wma_path).is_file():
        raise RuntimeError("WMAEncodeRS termino sin error pero no genero el archivo de salida")


def auto_encode_to_xwma(exe_path, wav_path, out_xwma_path, codec="pro", bitrate=192,
                         channels=None, sample_rate=None, fallback=False):
    """Pipeline completo: .wav -> WMAEncodeRS -> .wma (temp) -> convert_wma_to_xwma -> .xwma.
    Con fallback=True, si el encoder devuelve un perfil que XACT no admite (nBlockAlign/nAvgBytesPerSec
    fuera de tabla), reintenta con los demas bitrates validos (de mas cercano a mas lejano) hasta que
    uno produzca un perfil valido."""
    tmp_wma = Path(out_xwma_path).with_suffix(".tmp.wma")
    order = [bitrate]
    if fallback:
        order += sorted((b for b in VALID_XWMA_BITRATES if b != bitrate), key=lambda b: abs(b - bitrate))
    tried = []
    try:
        for b in order:
            run_wma_encoder(exe_path, wav_path, tmp_wma, codec=codec, bitrate=b,
                             channels=channels, sample_rate=sample_rate)
            try:
                xwma_bytes = convert_wma_to_xwma(tmp_wma)
            except ValueError as e:
                if "perfil xWMA" not in str(e):
                    raise
                m = re.search(r"nBlockAlign=(\d+) / nAvgBytesPerSec=(\d+)", str(e))
                tried.append(f"{b} kbps -> blockAlign={m.group(1)}, avgBytes={m.group(2)}" if m else f"{b} kbps")
                if fallback:
                    _say(f"{Path(wav_path).name}: {tried[-1]} no es un perfil xWMA valido, probando otro bitrate...")
                continue
            if tried:
                _say(f"{Path(wav_path).name}: valido con {b} kbps (el bitrate pedido, {bitrate}, no daba perfil valido).")
            Path(out_xwma_path).write_bytes(xwma_bytes)
            return
        raise ValueError(f"WMAEncodeRS ({codec}, {channels} canales, {sample_rate} Hz) no produjo ningun perfil "
                         f"xWMA valido. Intentos: " + "; ".join(tried))
    finally:
        tmp_wma.unlink(missing_ok=True)


XMA2_BLOCK_SIZE = 2048  # tamano de bloque XMA fijo que usa XACT/xwbtool


def build_wav_xma2(raw, channels, sample_rate, samples_encoded=0, loop_start=0, loop_len=0):
    """RIFF/WAV con wFormatTag=0x0166 (XMA2), escribiendo el struct XMA2WAVEFORMATEX
    completo (34 bytes de extradata, tal como lo generan xwbtool/XACT), no solo el
    primer byte. La version anterior solo seteaba wNumStreams y dejaba el resto en
    cero: ffmpeg es tolerante y lo decodifica igual, pero decoders mas estrictos
    (foobar2000, XAudio2 real, algunos plugins de vgmstream) validan el resto de los
    campos (dwSamplesEncoded, dwBlockCount, dwChannelMask, etc.) y lo rechazan.
    Referencia del struct (Microsoft xma2defs.h):
        WAVEFORMATEX wfx;          (18 bytes, cbSize=34)
        WORD  NumStreams;
        DWORD ChannelMask;
        DWORD SamplesEncoded;
        DWORD BytesPerBlock;
        DWORD PlayBeginSample;
        DWORD PlayLengthSamples;
        DWORD LoopBeginSample;
        DWORD LoopLengthSamples;
        BYTE  LoopCount;
        BYTE  EncoderVersion;
        WORD  BlockCount;
    """
    num_streams = (channels + 1) // 2  # hasta 2 canales por stream XMA
    # mascaras de canal estandar (SPEAKER_FRONT_LEFT|RIGHT, etc.); 0 tambien es valido
    # y lo aceptan los decoders, pero completarla ayuda a reproductores estrictos.
    channel_masks = {1: 0x4, 2: 0x3, 4: 0x33, 6: 0x3F, 8: 0xFF}
    channel_mask = channel_masks.get(channels, 0)
    block_count = (len(raw) + XMA2_BLOCK_SIZE - 1) // XMA2_BLOCK_SIZE
    play_length = samples_encoded
    loop_count = 255 if loop_len else 0  # 255 = loop infinito (convencion XACT), 0 = sin loop

    wfx = struct.pack("<HHIIHHH", 0x0166, channels, sample_rate,
                       sample_rate * XMA2_BLOCK_SIZE, XMA2_BLOCK_SIZE, 16, 34)
    xma2_extra = struct.pack("<HIIIIIIIBBH",
                              num_streams, channel_mask, samples_encoded, XMA2_BLOCK_SIZE,
                              0, play_length, loop_start, loop_len,
                              loop_count, 1, block_count)
    fmt_body = wfx + xma2_extra
    body = riff_chunk(b"fmt ", fmt_body) + riff_chunk(b"data", raw)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


# ---------------------------------------------------------------------------
# Formatos de exportacion livianos (post-proceso opcional con ffmpeg)
# ---------------------------------------------------------------------------

# "raw" no esta aca: es el caso especial de no tocar nada (ver extract_entry_bytes).
# Cada entrada es (extension_salida, argumentos_extra_de_ffmpeg).
EXPORT_FORMATS = {
    "wav": (".wav", ["-c:a", "pcm_s16le"]),
    "ogg": (".ogg", ["-c:a", "libvorbis", "-q:a", "4"]),
    "mp3": (".mp3", ["-c:a", "libmp3lame", "-q:a", "4"]),
}


def ffmpeg_available():
    return ensure_ffmpeg_on_path() is not None


def transcode_with_ffmpeg(raw_bytes, in_ext, out_format):
    """Decodifica raw_bytes (ya en un contenedor RIFF valido: .wav/.xwma tal como
    devuelve extract_entry_bytes en modo 'raw') con ffmpeg al formato liviano pedido
    ('wav' = PCM sin comprimir, 'ogg'/'mp3' = comprimido con perdida, mucho mas chico).
    Devuelve (extension, bytes)."""
    out_ext, ff_args = EXPORT_FORMATS[out_format]
    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / f"in{in_ext}"
        out_path = Path(tmp) / f"out{out_ext}"
        in_path.write_bytes(raw_bytes)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(in_path), *ff_args, str(out_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not out_path.is_file():
            raise RuntimeError(f"ffmpeg fallo al convertir a {out_format}:\n{result.stderr}")
        return out_ext, out_path.read_bytes()


def extract_entry_bytes(wb, entry, out_format="raw"):
    """Devuelve (extension, bytes) listos para escribir a disco.
    out_format:
      'raw' (por defecto) - el contenedor original tal cual (XMA2/ADPCM/xWMA sin
            decodificar): es lo mas chico posible y conserva 100% la calidad, pero
            algunos reproductores no lo abren sin un decoder especifico.
      'wav' - PCM 16-bit sin comprimir, decodificado con ffmpeg (pesa mas, pero lo
            abre cualquier reproductor).
      'ogg' / 'mp3' - comprimido con perdida via ffmpeg (el mas liviano de los tres,
            ideal para escuchar/compartir, no para reinyectar despues)."""
    raw = wb.wave_bytes(entry)
    fmt_tag = entry["format_tag"]
    if fmt_tag == FMT_PCM:
        if wb.e == ">" and entry["bits"] == 16:
            raw = swap16(raw)  # PCM de Xbox 360 es big-endian
        ext, data = ".wav", build_wav_pcm(raw, entry["channels"], entry["sample_rate"], entry["bits"])
    elif fmt_tag == FMT_ADPCM:
        ext, data = ".wav", build_wav_adpcm(raw, entry["channels"], entry["sample_rate"], entry["block_align"])
    elif fmt_tag == FMT_WMA and entry["seek_data"]:
        dpds_raw = entry["seek_data"][4:]  # sin el dword de count inicial
        ext, data = ".xwma", build_wav_xwma(raw, entry["channels"], entry["sample_rate"], entry["block_align"],
                                             entry["avg_bytes_per_sec"], entry["wma_tag"], dpds_raw)
    elif fmt_tag == FMT_XMA:
        ext, data = ".wav", build_wav_xma2(raw, entry["channels"], entry["sample_rate"],
                                            samples_encoded=entry["duration"],
                                            loop_start=entry["loop_start"], loop_len=entry["loop_total"])
    else:
        ext, data = ".xma", raw

    if out_format == "raw" or out_format not in EXPORT_FORMATS:
        return ext, data
    if not ffmpeg_available():
        raise RuntimeError("No se encontro ffmpeg en el PATH; instalalo/agregalo, o usa el formato "
                            "'Sin decodificar' que no lo necesita.")
    return transcode_with_ffmpeg(data, ext, out_format)


def read_riff_wav(path):
    raw = open(path, "rb").read()
    if raw[0:4] != b"RIFF" or raw[8:12] not in (b"WAVE", b"XWMA"):
        raise ValueError(f"{path} no es un RIFF/WAVE ni RIFF/XWMA valido")
    is_xwma = raw[8:12] == b"XWMA"
    pos, fmt, data, dpds, seek, fmt_extra = 12, None, None, None, None, b""
    while pos < len(raw) - 8:
        chunk_id = raw[pos:pos + 4]
        chunk_size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        chunk_body = raw[pos + 8:pos + 8 + chunk_size]
        if chunk_id == b"fmt ":
            format_tag, channels, sample_rate, avg_bytes_per_sec, block_align, bits = \
                struct.unpack("<HHIIHH", chunk_body[:16])
            fmt = dict(format_tag=format_tag, channels=channels, sample_rate=sample_rate,
                       avg_bytes_per_sec=avg_bytes_per_sec, block_align=block_align, bits_per_sample=bits)
            fmt_extra = bytes(chunk_body[16:])
        elif chunk_id == b"data":
            data = chunk_body
        elif chunk_id == b"dpds":
            dpds = chunk_body
        elif chunk_id == b"seek":
            seek = chunk_body
        pos += 8 + chunk_size + (chunk_size & 1)
    if fmt is None or data is None:
        raise ValueError(f"{path}: no se encontraron chunks fmt/data")
    if is_xwma and dpds is None:
        raise ValueError(f"{path}: RIFF/XWMA sin chunk 'dpds' (tabla de seek obligatoria para xWMA)")
    fmt["is_xwma"] = is_xwma
    fmt["dpds"] = dpds
    fmt["xma_seek"] = None
    fmt["xma_block_bytes"] = 65536
    if fmt["format_tag"] == WAVE_FORMAT_XMA2:
        # chunk 'seek' de un .xma2: DWORDs big-endian con las muestras acumuladas al final de cada bloque
        if seek:
            n = len(seek) // 4
            fmt["xma_seek"] = list(struct.unpack(f">{n}I", seek[:n * 4]))
        # XMA2WAVEFORMATEX (cbSize=34): BytesPerBlock en el offset 28 del cuerpo del fmt
        if len(fmt_extra) >= 16 and struct.unpack("<H", fmt_extra[:2])[0] == 34:
            bpb = struct.unpack("<I", fmt_extra[12:16])[0]
            if bpb > 2048 and bpb % 2048 == 0:
                fmt["xma_block_bytes"] = bpb
    return fmt, data


def snap_xwma_profile(block_align, avg_bytes_per_sec, tol=0.01):
    """WMAEncodeRS escribe en el ASF un nAvgBytesPerSec real (p.ej. 6003) en vez del nominal del perfil
    xWMA (6000). El .xwb solo guarda el INDICE del perfil, asi que el valor nominal es el correcto:
    si esta dentro de `tol` (1%) de un perfil estandar, se normaliza a ese valor."""
    if avg_bytes_per_sec in WMA_AVG_BYTES_PER_SEC or block_align not in WMA_BLOCK_ALIGN:
        return avg_bytes_per_sec
    best = min(WMA_AVG_BYTES_PER_SEC, key=lambda v: abs(v - avg_bytes_per_sec))
    return best if abs(best - avg_bytes_per_sec) <= best * tol else avg_bytes_per_sec


def encode_wma_blockalign(block_align, avg_bytes_per_sec):
    if block_align not in WMA_BLOCK_ALIGN or avg_bytes_per_sec not in WMA_AVG_BYTES_PER_SEC:
        return None
    ba_idx = WMA_BLOCK_ALIGN.index(block_align)
    bps_idx = WMA_AVG_BYTES_PER_SEC.index(avg_bytes_per_sec)
    return ba_idx | (bps_idx << 5)


def build_mini_waveformat(fmt):
    wav_tag, channels, sample_rate, block_align, bits = (
        fmt["format_tag"], fmt["channels"], fmt["sample_rate"], fmt["block_align"], fmt["bits_per_sample"])
    if wav_tag == 1:
        format_tag, blockalign_field, bits_flag = FMT_PCM, block_align, (1 if bits == 16 else 0)
    elif wav_tag == 2:
        format_tag, blockalign_field, bits_flag = FMT_ADPCM, (block_align // channels) - ADPCM_BLOCKALIGN_OFFSET, 0
    elif wav_tag in (WAVE_FORMAT_WMAUDIO2, WAVE_FORMAT_WMAUDIO3):
        if not fmt.get("is_xwma"):
            raise ValueError("audio xWMA debe venir en un contenedor RIFF/XWMA con chunk 'dpds'")
        encoded = encode_wma_blockalign(block_align, fmt["avg_bytes_per_sec"])
        if encoded is None:
            raise ValueError(
                f"nBlockAlign={block_align} / nAvgBytesPerSec={fmt['avg_bytes_per_sec']} no son un perfil xWMA "
                f"valido de XACT. Deben coincidir exactamente con uno de los perfiles estandar "
                f"(bloques: {WMA_BLOCK_ALIGN}, bytes/seg: {WMA_AVG_BYTES_PER_SEC}). Re-codifica con un "
                f"encoder xWMA/XACT estandar (p.ej. xWMAEncode.exe).")
        format_tag, blockalign_field = FMT_WMA, encoded
        bits_flag = 1 if wav_tag == WAVE_FORMAT_WMAUDIO3 else 0
    elif wav_tag == WAVE_FORMAT_XMA2:
        if channels > 2:
            raise ValueError("XMA2 de mas de 2 canales (multi-stream) no soportado")
        # igual que las entradas XMA originales del banco: blockalign=2, 16 bits
        format_tag, blockalign_field, bits_flag = FMT_XMA, 2, 1
        block_align = 2048  # solo informativo
    else:
        raise ValueError(f"format_tag {wav_tag} no soportado (usa PCM=1, MS-ADPCM=2, xWMA=0x161/0x162 o XMA2=0x166)")
    if not (0 <= blockalign_field <= 0xFF):
        raise ValueError(f"blockalign_field fuera de rango: {blockalign_field}")
    value = format_tag & 0x3
    value |= (channels & 0x7) << 2
    value |= (sample_rate & 0x3FFFF) << 5
    value |= (blockalign_field & 0xFF) << 23
    value |= (bits_flag & 0x1) << 31
    return value, format_tag, block_align, channels


def compute_duration_samples(format_tag, data_len, block_align, channels, wb=None, entries=None, index=None, dpds_values=None):
    if format_tag == FMT_PCM:
        frame_size = block_align if block_align else channels * 2
        return data_len // frame_size
    elif format_tag == FMT_ADPCM:
        samples_per_block = adpcm_samples_per_block(block_align, channels)
        return (data_len // block_align) * samples_per_block
    elif format_tag == FMT_WMA:
        total_bytes = dpds_values[-1] if dpds_values else 0
        real_samples = total_bytes // (channels * 2) if channels else 0
        # El campo Duration del wavebank no es 1:1 con las samples reales para WMA;
        # calibramos un factor usando otra entrada WMA del mismo banco con los mismos
        # canales (empiricamente validado: es constante dentro de un mismo banco).
        factor = 1.0
        if wb is not None and entries is not None:
            for i, e in enumerate(entries):
                if i == index or e["format_tag"] != FMT_WMA or e["channels"] != channels or not e["seek_data"]:
                    continue
                count = struct.unpack(f"{wb.e}I", e["seek_data"][:4])[0]
                if not count:
                    continue
                vals = struct.unpack(f"{wb.e}{count}I", e["seek_data"][4:4 + count * 4])
                other_samples = vals[-1] // (channels * 2)
                if other_samples:
                    factor = e["duration"] / other_samples
                    break
        return round(real_samples * factor)
    raise ValueError(f"format_tag {format_tag} no soportado para calcular duracion")



def swap16(data):
    """Intercambia el orden de bytes de cada muestra de 16 bits (LE <-> BE)."""
    b = bytearray(data[:len(data) & ~1])
    b[0::2], b[1::2] = b[1::2], b[0::2]
    return bytes(b)


def pcm_for_bank(wb, wav_fmt, pcm_data):
    """El PCM de un banco Xbox 360 (big-endian) va con las muestras de 16 bits en BE.
    El .wav siempre es LE, asi que hay que intercambiarlas al inyectar."""
    if wav_fmt["format_tag"] == 1 and wav_fmt["bits_per_sample"] == 16 and wb.e == ">":
        return swap16(pcm_data)
    return pcm_data


def ffmpeg_to_pcm16(src_path, out_path, channels, sample_rate):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src_path), "-ac", str(channels),
           "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not Path(out_path).is_file():
        raise RuntimeError(f"ffmpeg fallo al convertir {src_path}:\n{r.stderr}")


CODEC_SETTINGS = {
    "policy": "same",     # same = convertir al MISMO codec que la entrada original | keep = inyectar tal cual
    "wma_exe": None,      # ruta a WMAEncodeRS.exe (None = buscar junto al script)
    "wma_bitrate": None,  # kbps; None = el perfil xWMA mas cercano al de la entrada original
}
CODEC_LOG = None          # callable(str) opcional: cuenta que conversion se hizo


def _say(msg):
    if CODEC_LOG:
        try:
            CODEC_LOG(msg)
        except Exception:
            pass


def codec_label(entry):
    """Nombre legible del codec de una entrada del banco."""
    t = entry["format_tag"]
    if t == FMT_XMA:
        return "XMA2"
    if t == FMT_WMA:
        return "WMA Pro" if entry.get("wma_tag") == WAVE_FORMAT_WMAUDIO3 else "WMA estandar"
    if t == FMT_ADPCM:
        return "ADPCM"
    if t == FMT_PCM:
        return f"PCM {entry.get('bits', 16)}b"
    return "?"


def nearest_wma_bitrate(entry):
    if CODEC_SETTINGS.get("wma_bitrate"):
        return int(CODEC_SETTINGS["wma_bitrate"])
    kbps = (entry.get("avg_bytes_per_sec") or 0) * 8 / 1000.0
    return min(VALID_XWMA_BITRATES, key=lambda b: abs(b - kbps))


def pick_adpcm_block(entry):
    """Block align (bytes, potencia de 2 dentro del rango que admite XACT) mas cercano al de la entrada."""
    ch = max(1, entry["channels"])
    cands = [2 ** k for k in range(4, 12) if 22 * ch <= 2 ** k <= 277 * ch] or [64 * ch]
    return min(cands, key=lambda c: abs(c - (entry.get("block_align") or 64)))


def encode_adpcm_ms(src_path, out_path, channels, sample_rate, block_size):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src_path), "-ar", str(sample_rate), "-ac", str(channels),
           "-acodec", "adpcm_ms", "-block_size", str(block_size), str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not Path(out_path).is_file():
        raise RuntimeError(f"ffmpeg fallo al codificar MS-ADPCM:\n{r.stderr}")


def resolve_replacement(src_path, entry, tmpdir):
    """Devuelve la ruta de un archivo listo para inyectar en `entry`, en el MISMO codec que la entrada original
    (politica 'same', por defecto):
      - XMA2     -> xma2encode.exe (sin el encoder, cae a PCM y el banco crece)
      - WMA Pro / WMA estandar -> WMAEncodeRS.exe (codec y bitrate del original) + reempaquetado xWMA
      - ADPCM    -> ffmpeg adpcm_ms con el block align del original
      - PCM      -> PCM 16-bit con los canales y el sample rate del original
    Si el archivo ya viene en ese codec se usa tal cual. Con la politica 'keep' se inyecta lo que se de."""
    src_path = Path(src_path)
    tag, ch, rate = entry["format_tag"], entry["channels"], entry["sample_rate"]
    label = codec_label(entry)
    fmt = None
    try:
        fmt, _ = read_riff_wav(src_path)
    except Exception:
        pass
    keep = CODEC_SETTINGS.get("policy") == "keep"
    if fmt is not None:
        t = fmt["format_tag"]
        same = ((tag == FMT_XMA and t == WAVE_FORMAT_XMA2)
                or (tag == FMT_ADPCM and t == 2)
                or (tag == FMT_WMA and fmt.get("is_xwma") and t == entry.get("wma_tag"))
                or (tag == FMT_PCM and t == 1 and fmt["bits_per_sample"] == 16
                    and fmt["channels"] == ch and fmt["sample_rate"] == rate))
        if same:
            _say(f"{src_path.name}: ya esta en {label}; se usa tal cual.")
            return src_path
        if keep and (t in (1, 2, WAVE_FORMAT_XMA2) or (t in (WAVE_FORMAT_WMAUDIO2, WAVE_FORMAT_WMAUDIO3) and fmt.get("is_xwma"))):
            _say(f"{src_path.name}: politica 'tal cual', se inyecta sin convertir.")
            return src_path
    if not ffmpeg_available():
        raise RuntimeError(f"{src_path.name}: hace falta ffmpeg en el PATH para convertirlo a {label}")
    pcm16 = Path(tmpdir) / (src_path.stem + "_pcm16.wav")

    if tag == FMT_XMA:
        mode = XMA_SETTINGS["mode"]
        exe = XMA_SETTINGS["exe"] or find_xma2_encoder()
        if mode != "pcm" and exe and Path(exe).is_file():
            _say(f"{src_path.name}: -> XMA2 con xma2encode (calidad {XMA_SETTINGS['quality']}, bloques {XMA_SETTINGS['block_kb']} KB)")
            return encode_to_xma2(exe, src_path, entry, tmpdir, quality=XMA_SETTINGS["quality"],
                                  block_kb=XMA_SETTINGS["block_kb"])
        if mode == "xma2":
            raise RuntimeError("modo XMA2 pero no se encontro xma2encode.exe (ponelo junto al script o indica la ruta)")
        _say(f"{src_path.name}: sin xma2encode, se inyecta como PCM 16-bit (el banco crece).")
        ffmpeg_to_pcm16(src_path, pcm16, ch, rate)
        return pcm16

    if tag == FMT_WMA:
        exe = CODEC_SETTINGS.get("wma_exe") or find_wma_encoder()
        if not exe or not Path(exe).is_file():
            raise RuntimeError(f"{src_path.name}: la entrada es {label} y hace falta WMAEncodeRS.exe para convertir "
                               "(ponelo junto al script o indicalo en Ajustes)")
        codec = "pro" if entry.get("wma_tag") == WAVE_FORMAT_WMAUDIO3 else "standard"
        bitrate = nearest_wma_bitrate(entry)
        ffmpeg_to_pcm16(src_path, pcm16, ch, rate)
        out = Path(tmpdir) / (src_path.stem + "_enc.xwma")
        _say(f"{src_path.name}: -> {label} con WMAEncodeRS ({codec}, {bitrate} kbps, {ch} canal(es), {rate} Hz)")
        auto_encode_to_xwma(exe, pcm16, out, codec=codec, bitrate=bitrate, channels=ch, sample_rate=rate,
                         fallback=True)
        return out

    if tag == FMT_ADPCM:
        block = pick_adpcm_block(entry)
        out = Path(tmpdir) / (src_path.stem + "_adpcm.wav")
        _say(f"{src_path.name}: -> MS-ADPCM con ffmpeg (block align {block}, {ch} canal(es), {rate} Hz)")
        encode_adpcm_ms(src_path, out, ch, rate, block)
        return out

    _say(f"{src_path.name}: -> PCM 16-bit ({ch} canal(es), {rate} Hz)")
    ffmpeg_to_pcm16(src_path, pcm16, ch, rate)
    return pcm16


def next_backup_path(original):
    """banco.xwb -> banco.xwb.bak (si ya existe, banco.xwb.bak2, .bak3...: nunca se pisa un backup)."""
    original = Path(original)
    bak = original.with_name(original.name + ".bak")
    n = 2
    while bak.exists():
        bak = original.with_name(f"{original.name}.bak{n}")
        n += 1
    return bak


def commit_new_bank(original, new_tmp, backup=True):
    """Pone el banco nuevo (new_tmp) en lugar del original. Con backup=True el original se RENOMBRA a .bak
    (el primer backup es siempre el original intacto). Si algo falla se restaura el original."""
    original, new_tmp = Path(original), Path(new_tmp)
    if not new_tmp.is_file():
        raise FileNotFoundError(f"no existe el banco nuevo: {new_tmp}")
    bak = None
    if original.exists():
        if backup:
            bak = next_backup_path(original)
            os.replace(original, bak)
        else:
            original.unlink()
    try:
        os.replace(new_tmp, original)
    except Exception:
        if bak is not None and not original.exists():
            os.replace(bak, original)
        raise
    return bak


def xma2_seek_table(wav_fmt, data):
    """Muestras acumuladas al final de cada bloque XMA2 (lo que XACT guarda como tabla de seek).
    Usa el chunk 'seek' del .xma2 si existe; si no, lo reconstruye leyendo las cabeceras de los
    paquetes de 2048 bytes (6 bits = frames que empiezan en el paquete, 512 muestras por frame)."""
    vals = wav_fmt.get("xma_seek")
    if vals:
        vals = list(vals)
    else:
        if wav_fmt["channels"] > 2:
            raise ValueError("XMA2 multi-stream sin chunk 'seek': no soportado")
        per_block = max(1, wav_fmt.get("xma_block_bytes", 65536) // 2048)
        n_packets = len(data) // 2048
        vals, cum = [], 0
        for p in range(n_packets):
            cum += (struct.unpack(">I", data[p * 2048:p * 2048 + 4])[0] >> 26) * 512
            if (p + 1) % per_block == 0 or p == n_packets - 1:
                vals.append(cum)
    if not vals or vals != sorted(vals) or vals[-1] <= 0:
        raise ValueError("tabla de seek XMA2 invalida o vacia")
    return vals


def pack_xma_seek(wb, vals):
    return struct.pack(f"{wb.e}I", len(vals)) + struct.pack(f"{wb.e}{len(vals)}I", *vals)


XMA2_ENCODER_NAMES = ("xma2encode.exe", "XMA2Encode.exe", "xma2encode")
XMA_SETTINGS = {"mode": "auto",       # auto = XMA2 si hay encoder, si no PCM | xma2 | pcm
                "exe": None,          # ruta a xma2encode.exe (None = buscar junto al script)
                "quality": 75,        # /Quality (el rango lo dice xma2encode /Help)
                "block_kb": 64}       # /BlockSize: los originales de voicese usan bloques de 64 KB


def find_xma2_encoder():
    return find_tool(XMA2_ENCODER_NAMES)


def run_xma2_encoder(exe_path, pcm_wav, out_path, quality=75, block_kb=64):
    """xma2encode <pcm.wav> /TargetFile <out> /BlockSize N /Quality Q /UseLoopPoints (Windows)."""
    out_path = Path(out_path)
    out_path.unlink(missing_ok=True)
    cmd = [str(exe_path), str(pcm_wav), "/TargetFile", str(out_path),
           "/BlockSize", str(block_kb), "/Quality", str(quality), "/UseLoopPoints"]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", input="y\n", timeout=300)
    if r.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError(f"xma2encode fallo (codigo {r.returncode}):\n{(r.stdout or '')}\n{(r.stderr or '')}".strip())


def encode_to_xma2(exe_path, src_path, entry, tmpdir, quality=75, block_kb=64):
    """Cualquier audio -> PCM16 (canales/rate de la entrada) -> xma2encode -> .xma2 (RIFF con fmt/seek/data)."""
    src_path = Path(src_path)
    rates = [entry["sample_rate"]] + ([48000] if entry["sample_rate"] != 48000 else [])
    last_err = None
    for rate in rates:
        pcm = Path(tmpdir) / f"{src_path.stem}_{rate}_pcm16.wav"
        out = Path(tmpdir) / f"{src_path.stem}_{rate}.xma2.wav"
        ffmpeg_to_pcm16(src_path, pcm, min(entry["channels"], 2), rate)
        try:
            run_xma2_encoder(exe_path, pcm, out, quality=quality, block_kb=block_kb)
            return out
        except RuntimeError as e:
            last_err = e
    raise last_err


def inject_entry(wb, index, wav_path, out_path):
    entries = wb.entries
    if not (0 <= index < len(entries)):
        raise ValueError(f"indice {index} fuera de rango (0..{len(entries) - 1})")
    old_entry = entries[index]
    with tempfile.TemporaryDirectory() as _tmp:
        wav_path = resolve_replacement(wav_path, old_entry, _tmp)
        wav_fmt, wav_pcm_data = read_riff_wav(wav_path)
    wav_pcm_data = pcm_for_bank(wb, wav_fmt, wav_pcm_data)
    mini_val, format_tag, block_align, channels = build_mini_waveformat(wav_fmt)

    warnings = []
    if old_entry["format_tag"] != format_tag:
        warnings.append(f"formato cambia de {FMT_NAMES.get(old_entry['format_tag'], '?')} "
                         f"a {FMT_NAMES.get(format_tag, '?')}")
    if old_entry["channels"] != channels:
        warnings.append(f"canales cambian de {old_entry['channels']} a {channels}")
    if format_tag == FMT_WMA and old_entry["format_tag"] == FMT_WMA:
        old_tag_name = "WMA Pro" if old_entry.get("wma_tag") == WAVE_FORMAT_WMAUDIO3 else "WMA Standard"
        new_tag_name = "WMA Pro" if wav_fmt["format_tag"] == WAVE_FORMAT_WMAUDIO3 else "WMA Standard"
        if old_tag_name != new_tag_name:
            warnings.append(f"variante WMA cambia de {old_tag_name} a {new_tag_name}")

    if format_tag == FMT_WMA:
        dpds_raw = wav_fmt["dpds"]
        count = len(dpds_raw) // 4
        dpds_values = struct.unpack(f"<{count}I", dpds_raw)
        new_seek_chunk = struct.pack(f"{wb.e}I", count) + dpds_raw
        duration_samples = compute_duration_samples(format_tag, len(wav_pcm_data), block_align, channels,
                                                      wb=wb, entries=entries, index=index, dpds_values=dpds_values)
    elif format_tag == FMT_XMA:
        xma_vals = xma2_seek_table(wav_fmt, wav_pcm_data)
        new_seek_chunk = pack_xma_seek(wb, xma_vals)
        duration_samples = xma_vals[-1]
    else:
        new_seek_chunk = b""
        duration_samples = compute_duration_samples(format_tag, len(wav_pcm_data), block_align, channels)

    # --- segmento ENTRYWAVEDATA (los bytes de audio en si) ---
    wavedata_off, wavedata_len = wb.segments[SEG_ENTRYWAVEDATA]
    entrymeta_off, entrymeta_len = wb.segments[SEG_ENTRYMETADATA]
    old_wave_segment = bytes(wb.data[wavedata_off:wavedata_off + wavedata_len])
    old_start = old_entry["play_off"]
    old_end = old_start + old_entry["play_len"]
    # En bancos de streaming, el delta de tamano debe ser multiplo de 2048 para que
    # las entradas posteriores (ya alineadas en el original) sigan alineadas al correrse.
    is_streaming = bool(wb.flags & 1)
    wave_pad = b""
    if is_streaming:
        wave_pad = b"\x00" * ((old_entry["play_len"] - len(wav_pcm_data)) % STREAM_ALIGN)
    new_wave_segment = old_wave_segment[:old_start] + wav_pcm_data + wave_pad + old_wave_segment[old_end:]
    size_delta = len(wav_pcm_data) + len(wave_pad) - old_entry["play_len"]

    # --- segmento SEG_SEEKTABLES (tabla de offsets + bloques count-prefijados) ---
    seek_off, seek_len = wb.segments[SEG_SEEKTABLES]
    if seek_len == 0 and format_tag not in (FMT_WMA, FMT_XMA):
        # Este banco no usa seek tables (p.ej. bancos solo-ADPCM) y no las necesitamos: no tocar el segmento.
        new_seektable_bytes = b""
    else:
        seek_chunks = [new_seek_chunk if i == index else e["seek_data"] for i, e in enumerate(entries)]
        rel_offsets, cur = [], 0
        for c in seek_chunks:
            rel_offsets.append(cur)
            cur += len(c)
        new_seektable_bytes = struct.pack(f"{wb.e}{len(seek_chunks)}I", *rel_offsets) + b"".join(seek_chunks)
        if is_streaming:
            # el cambio de tamano del seektable corre el inicio de ENTRYWAVEDATA:
            # rellenar para que el segmento de audio quede alineado igual que antes
            new_seektable_bytes += b"\x00" * ((seek_len - len(new_seektable_bytes)) % STREAM_ALIGN)
    seek_delta = len(new_seektable_bytes) - seek_len

    # --- tabla de entradas (metadatos) ---
    new_entries_bytes = bytearray()
    for i, e in enumerate(entries):
        if i == index:
            new_play_off, new_play_len = old_start, len(wav_pcm_data)
            new_miniformat, new_duration = mini_val, duration_samples & 0x0FFFFFFF
            new_flags_nibble, new_loop_start, new_loop_total = 0, 0, 0
        else:
            new_play_off = e["play_off"] + (size_delta if e["play_off"] > old_start else 0)
            new_play_len, new_miniformat, new_duration = e["play_len"], e["miniformat"], e["duration"]
            new_flags_nibble, new_loop_start, new_loop_total = e["flags"], e["loop_start"], e["loop_total"]
        flags_dur = ((new_duration & 0x0FFFFFFF) << 4) | (new_flags_nibble & 0xF)
        new_entries_bytes += struct.pack(f"{wb.e}IIIIII", flags_dur, new_miniformat,
                                          new_play_off, new_play_len, new_loop_start, new_loop_total)

    # --- ensamblado: entrymeta (tamano fijo) -> seektables (puede correr lo siguiente) -> wavedata ---
    out = bytearray(wb.data)
    out[entrymeta_off:entrymeta_off + entrymeta_len] = new_entries_bytes
    out[seek_off:seek_off + seek_len] = new_seektable_bytes  # aca se corre todo lo que viene despues

    new_wavedata_off = wavedata_off + seek_delta
    out[new_wavedata_off:new_wavedata_off + wavedata_len] = new_wave_segment

    entrynames_off, entrynames_len = wb.segments[SEG_ENTRYNAMES]
    if entrynames_len and entrynames_off > seek_off:
        entrynames_off += seek_delta

    new_segments = [list(s) for s in wb.segments]
    new_segments[SEG_SEEKTABLES][1] = len(new_seektable_bytes)
    new_segments[SEG_ENTRYNAMES][0] = entrynames_off
    new_segments[SEG_ENTRYWAVEDATA][0] = new_wavedata_off
    new_segments[SEG_ENTRYWAVEDATA][1] = len(new_wave_segment)
    seg_table = b"".join(struct.pack(f"{wb.e}II", off, length) for off, length in new_segments)
    out[12:12 + len(seg_table)] = seg_table
    Path(out_path).write_bytes(out)
    return old_entry, format_tag, len(wav_pcm_data), size_delta, warnings


ENTRY_NAME_RE = re.compile(r"(\d+)")


def load_manifest_replacements(manifest_path, wav_folder):
    """Lee un manifiesto tipo VOICE4.JSON (dict "entryNNN" -> metadata con "file") y
    devuelve {indice: ruta_wav}, mapeando entryNNN -> indice N directamente (sin .xsb).
    Si el .wav referenciado no existe en wav_folder, esa entrada se omite (se reporta)."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    wav_folder = Path(wav_folder)
    replacements, missing = {}, []
    for key, meta in manifest.items():
        m = ENTRY_NAME_RE.search(key)
        if not m:
            continue
        idx = int(m.group(1))
        wav_path = wav_folder / meta.get("file", f"{key}.wav")
        if wav_path.is_file():
            replacements[idx] = wav_path
        else:
            missing.append(str(wav_path))
    return replacements, missing


def batch_inject_entries(wb, replacements, out_path, report_path=None):
    """Inyecta muchas entradas de una sola pasada (mucho mas rapido que llamar
    inject_entry() en loop, que reescribiria el archivo completo por cada una).
    replacements: {indice: ruta_wav_o_xwma}.
    Devuelve una lista de reportes (uno por indice reemplazado) y opcionalmente
    escribe un changelog JSON en report_path para poder auditar despues que cambio."""
    entries = wb.entries
    entrymeta_off, entrymeta_len = wb.segments[SEG_ENTRYMETADATA]
    wavedata_off, wavedata_len = wb.segments[SEG_ENTRYWAVEDATA]
    seek_off, seek_len = wb.segments[SEG_SEEKTABLES]
    entrynames_off, entrynames_len = wb.segments[SEG_ENTRYNAMES]
    _tmpdir = tempfile.TemporaryDirectory()
    replacements = {i: resolve_replacement(p, entries[i], _tmpdir.name) for i, p in replacements.items()}
    uses_seektables = seek_len > 0 or any(fmt in (FMT_WMA, FMT_XMA) for fmt in
                                          (build_mini_waveformat(read_riff_wav(p)[0])[1] for p in replacements.values()))

    # bancos de streaming: cada entrada debe arrancar en un offset multiplo de 2048
    # (ver STREAM_ALIGN); en bancos in-memory se conserva el empaquetado original.
    align = STREAM_ALIGN if (wb.flags & 1) else 1
    new_wave_chunks, new_meta_rows, new_seek_chunks, report = [], [], [], []
    cur_off = 0
    for i, e in enumerate(entries):
        if align > 1 and cur_off % align:
            pad = align - cur_off % align
            new_wave_chunks.append(b"\x00" * pad)
            cur_off += pad
        if i in replacements:
            wav_path = replacements[i]
            wav_fmt, pcm_data = read_riff_wav(wav_path)
            pcm_data = pcm_for_bank(wb, wav_fmt, pcm_data)
            mini_val, format_tag, block_align, channels = build_mini_waveformat(wav_fmt)
            warnings = []
            if e["format_tag"] != format_tag:
                warnings.append(f"formato {FMT_NAMES.get(e['format_tag'], '?')} -> {FMT_NAMES.get(format_tag, '?')}")
            if e["channels"] != channels:
                warnings.append(f"canales {e['channels']} -> {channels}")
            if e["format_tag"] == FMT_ADPCM and e["block_align"] != block_align:
                warnings.append(f"block_align {e['block_align']} -> {block_align} (afecta ratio de compresion)")
            if format_tag == FMT_WMA:
                dpds_raw = wav_fmt["dpds"]
                count = len(dpds_raw) // 4
                dpds_values = struct.unpack(f"<{count}I", dpds_raw)
                seek_chunk = struct.pack(f"{wb.e}I", count) + dpds_raw
                duration = compute_duration_samples(format_tag, len(pcm_data), block_align, channels,
                                                     wb=wb, entries=entries, index=i, dpds_values=dpds_values)
            elif format_tag == FMT_XMA:
                xma_vals = xma2_seek_table(wav_fmt, pcm_data)
                seek_chunk = pack_xma_seek(wb, xma_vals)
                duration = xma_vals[-1]
            else:
                seek_chunk = b""
                duration = compute_duration_samples(format_tag, len(pcm_data), block_align, channels)
            flags_dur = (duration & 0x0FFFFFFF) << 4
            play_len = len(pcm_data)
            report.append({
                "index": i, "wav": str(wav_path),
                "old_bytes": e["play_len"], "new_bytes": play_len, "delta_bytes": play_len - e["play_len"],
                "old_format": FMT_NAMES.get(e["format_tag"], "?"), "new_format": FMT_NAMES.get(format_tag, "?"),
                "old_block_align": e["block_align"], "new_block_align": block_align,
                "warnings": warnings,
            })
        else:
            pcm_data = wb.wave_bytes(e)
            mini_val, flags_dur = e["miniformat"], ((e["duration"] & 0x0FFFFFFF) << 4) | (e["flags"] & 0xF)
            seek_chunk = e["seek_data"]
        play_off = cur_off
        play_len = len(pcm_data)
        loop_start = 0 if i in replacements else e["loop_start"]
        loop_total = 0 if i in replacements else e["loop_total"]
        new_meta_rows.append(struct.pack(f"{wb.e}IIIIII", flags_dur, mini_val, play_off, play_len, loop_start, loop_total))
        new_wave_chunks.append(pcm_data)
        new_seek_chunks.append(seek_chunk)
        cur_off += play_len

    if align > 1 and cur_off % align:
        # padding final: los bancos originales terminan en frontera de 2048 tambien
        new_wave_chunks.append(b"\x00" * (align - cur_off % align))

    new_wave_segment = b"".join(new_wave_chunks)
    new_entries_bytes = b"".join(new_meta_rows)

    if uses_seektables:
        rel_offsets, cur = [], 0
        for c in new_seek_chunks:
            rel_offsets.append(cur)
            cur += len(c)
        new_seektable_bytes = struct.pack(f"{wb.e}{len(new_seek_chunks)}I", *rel_offsets) + b"".join(new_seek_chunks)
        if align > 1:
            # mantener alineado el inicio del segmento ENTRYWAVEDATA (se corre con seek_delta)
            new_seektable_bytes += b"\x00" * ((seek_len - len(new_seektable_bytes)) % align)
    else:
        new_seektable_bytes = b""
    seek_delta = len(new_seektable_bytes) - seek_len

    out = bytearray(wb.data)
    out[entrymeta_off:entrymeta_off + entrymeta_len] = new_entries_bytes
    out[seek_off:seek_off + seek_len] = new_seektable_bytes
    new_wavedata_off = wavedata_off + seek_delta
    out[new_wavedata_off:new_wavedata_off + wavedata_len] = new_wave_segment

    new_entrynames_off = entrynames_off + seek_delta if entrynames_len and entrynames_off > seek_off else entrynames_off
    new_segments = [list(s) for s in wb.segments]
    new_segments[SEG_SEEKTABLES][1] = len(new_seektable_bytes)
    new_segments[SEG_ENTRYNAMES][0] = new_entrynames_off
    new_segments[SEG_ENTRYWAVEDATA][0] = new_wavedata_off
    new_segments[SEG_ENTRYWAVEDATA][1] = len(new_wave_segment)
    seg_table = b"".join(struct.pack(f"{wb.e}II", off, length) for off, length in new_segments)
    out[12:12 + len(seg_table)] = seg_table

    Path(out_path).write_bytes(out)
    _tmpdir.cleanup()
    if report_path:
        Path(report_path).write_text(json.dumps({
            "xwb_original_size": len(wb.data), "xwb_final_size": len(out),
            "total_delta_bytes": len(out) - len(wb.data),
            "entries_reemplazadas": len(report), "detalle": report,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def trim_wav_pcm(in_path, out_path, start_seconds=None, end_seconds=None, trim_silence=False,
                  silence_threshold_db=-40, silence_min_duration=0.1):
    """Recorta un WAV PCM (SIEMPRE trabaja sobre PCM sin comprimir, nunca sobre ADPCM ya
    codificado: cortar bloques MS-ADPCM a mitad de bloque corrompe el decoder). Usa ffmpeg.
    - start_seconds/end_seconds: recorte por tiempo explicito (exacto, recomendado).
    - trim_silence: recorta silencio de inicio/fin automaticamente (deteccion RMS). Es
      aproximado (+-100-200ms tipico segun el contenido) -- escucha el resultado antes de
      usarlo en un lote grande, no lo apliques a ciegas sobre dialogo real."""
    cmd = ["ffmpeg", "-y", "-i", str(in_path)]
    filters = []
    if start_seconds is not None or end_seconds is not None:
        if start_seconds is not None:
            cmd += ["-ss", str(start_seconds)]
        if end_seconds is not None:
            duration = end_seconds - (start_seconds or 0)
            cmd += ["-t", str(duration)]
    elif trim_silence:
        filters.append(
            f"silenceremove=start_periods=1:start_duration={silence_min_duration}:start_threshold={silence_threshold_db}dB:"
            f"detection=rms,areverse,"
            f"silenceremove=start_periods=1:start_duration={silence_min_duration}:start_threshold={silence_threshold_db}dB:"
            f"detection=rms,areverse"
        )
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += ["-v", "error", str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg fallo al recortar:\n{result.stderr}")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.lang = "es"
        self._i18n_widgets = []  # (widget, key, kind) para retraducir al vuelo

        self.geometry("880x600")
        self.configure(bg=BASE)

        self.wb = None
        self.xwb_path = None
        self.cue_mapping = {}       # nombre_cue -> indice, tal como viene del .xsb
        self.name_overrides = {}    # indice -> nombre editado a mano por el usuario

        self._setup_style()
        self._build_ui()
        self._apply_language()

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BASE, foreground=TEXT, fieldbackground=SURFACE0,
                         bordercolor=SURFACE1, lightcolor=SURFACE0, darkcolor=SURFACE0,
                         font=("Segoe UI", 10))
        style.configure("TNotebook", background=BASE, bordercolor=BASE)
        style.configure("TNotebook.Tab", background=MANTLE, foreground=SUBTEXT, padding=(14, 6))
        style.map("TNotebook.Tab", background=[("selected", SURFACE0)], foreground=[("selected", MAUVE)])
        style.configure("TFrame", background=BASE)
        style.configure("TLabel", background=BASE, foreground=TEXT)
        style.configure("Sub.TLabel", background=BASE, foreground=SUBTEXT)
        style.configure("TButton", background=SURFACE1, foreground=TEXT, padding=6, borderwidth=0)
        style.map("TButton", background=[("active", MAUVE)], foreground=[("active", MANTLE)])
        style.configure("TEntry", fieldbackground=SURFACE0, foreground=TEXT, insertcolor=TEXT)
        style.configure("Treeview", background=SURFACE0, fieldbackground=SURFACE0, foreground=TEXT,
                         rowheight=24, borderwidth=0)
        style.configure("Treeview.Heading", background=MANTLE, foreground=MAUVE, borderwidth=0)
        style.map("Treeview", background=[("selected", MAUVE)], foreground=[("selected", MANTLE)])

    # ---------------- i18n ----------------

    def tr(self, key):
        return TR.get(key, {}).get(self.lang, key)

    def _reg(self, widget, key, kind="text"):
        self._i18n_widgets.append((widget, key, kind))
        return widget

    def L(self, parent, key, **kwargs):
        """ttk.Label traducible."""
        w = ttk.Label(parent, text=self.tr(key), **kwargs)
        return self._reg(w, key, "text")

    def B(self, parent, key, command=None, **kwargs):
        """ttk.Button traducible."""
        w = ttk.Button(parent, text=self.tr(key), command=command, **kwargs)
        return self._reg(w, key, "text")

    def LF(self, parent, key, **kwargs):
        """ttk.LabelFrame traducible."""
        w = ttk.LabelFrame(parent, text=self.tr(key), **kwargs)
        return self._reg(w, key, "text")

    def _set_lang(self, lang_code):
        self.lang = lang_code
        self._apply_language()

    def _apply_language(self):
        self.title(self.tr("app_title"))
        for widget, key, kind in self._i18n_widgets:
            text = self.tr(key)
            if kind == "text":
                widget.config(text=text)
            elif kind.startswith("heading:"):
                col = kind.split(":", 1)[1]
                widget.heading(col, text=text)
            elif kind.startswith("tab:"):
                idx = int(kind.split(":", 1)[1])
                widget.tab(idx, text=text)
        # combobox de formato de extraccion: los values se regeneran a mano (no son widgets con .config(text=))
        if hasattr(self, "export_format_combo"):
            self._refresh_export_format_values()

    def _build_ui(self):
        langbar = ttk.Frame(self)
        langbar.pack(fill="x", padx=12, pady=(10, 0))
        self.L(langbar, "interface_lang").pack(side="left")
        self.lang_var = tk.StringVar(value="Español")
        lang_names = {"Español": "es", "Українська": "uk", "English": "en"}
        lang_combo = ttk.Combobox(langbar, textvariable=self.lang_var, values=list(lang_names),
                                   width=12, state="readonly")
        lang_combo.pack(side="left", padx=6)
        lang_combo.bind("<<ComboboxSelected>>",
                         lambda _e: self._set_lang(lang_names.get(self.lang_var.get(), "es")))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_bank = ttk.Frame(nb)
        self.tab_process = ttk.Frame(nb)
        self.tab_inject = ttk.Frame(nb)
        self.tab_batch = ttk.Frame(nb)
        nb.add(self.tab_bank, text=self.tr("tab_bank"))
        nb.add(self.tab_process, text=self.tr("tab_process"))
        nb.add(self.tab_inject, text=self.tr("tab_inject"))
        nb.add(self.tab_batch, text=self.tr("tab_batch"))
        self._reg(nb, "tab_bank", "tab:0")
        self._reg(nb, "tab_process", "tab:1")
        self._reg(nb, "tab_inject", "tab:2")
        self._reg(nb, "tab_batch", "tab:3")

        self._build_bank_tab()
        self._build_process_tab()
        self._build_inject_tab()
        self._build_batch_tab()

        self.status = tk.StringVar(value=self.tr("status_ready"))
        status_bar = ttk.Label(self, textvariable=self.status, style="Sub.TLabel", anchor="w")
        status_bar.pack(fill="x", padx=12, pady=(0, 8))

    def set_status(self, msg, ok=True):
        self.status.set(msg)

    # ---------------- Banco tab (Cues + Extraer, fusionadas) ----------------

    def _build_bank_tab(self):
        f = self.tab_bank
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=8)

        self.xwb_var = tk.StringVar()
        self.xsb_var = tk.StringVar()

        self.L(top, "xwb_label").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.xwb_var, width=58).grid(row=0, column=1, padx=6)
        self.B(top, "browse_btn", width=3, command=self._pick_xwb).grid(row=0, column=2)

        self.L(top, "xsb_label").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.xsb_var, width=58).grid(row=1, column=1, padx=6, pady=(6, 0))
        self.B(top, "browse_btn", width=3, command=self._pick_xsb).grid(row=1, column=2, pady=(6, 0))

        self.B(top, "load_bank_btn", command=self._load_bank).grid(row=0, column=3, rowspan=2, padx=10)
        # Banco del .xsb cuyos nombres se aplican a este .xwb (bgm.xsb lista bgm, prod, scnd, scnd2)
        self.xsb_bank_var = tk.StringVar(value=AUTO_BANK_LABEL)
        self.L(top, "xsb_bank_label").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.xsb_bank_combo = ttk.Combobox(top, textvariable=self.xsb_bank_var, values=[AUTO_BANK_LABEL],
                                           state="readonly", width=22)
        self.xsb_bank_combo.grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))
        self.xsb_auto_label = ttk.Label(top, text="", style="Sub.TLabel")
        self.xsb_auto_label.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        cols = ("index", "name", "format", "duration")
        self.bank_tree = ttk.Treeview(f, columns=cols, show="headings", height=16)
        header_keys = {"index": "col_index", "name": "col_name", "format": "col_format", "duration": "col_duration"}
        for c, w in zip(cols, (70, 220, 90, 90)):
            self.bank_tree.heading(c, text=self.tr(header_keys[c]))
            self._reg(self.bank_tree, header_keys[c], f"heading:{c}")
            self.bank_tree.column(c, width=w, anchor="w")
        self.bank_tree.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        self.bank_tree.bind("<<TreeviewSelect>>", self._on_bank_select)

        # --- edicion del nombre de la entrada seleccionada ---
        edit = ttk.Frame(f)
        edit.pack(fill="x", padx=8, pady=(0, 6))
        self.bank_name_edit_var = tk.StringVar()
        self.L(edit, "selected_name_label").pack(side="left")
        ttk.Entry(edit, textvariable=self.bank_name_edit_var, width=30).pack(side="left", padx=6)
        self.B(edit, "apply_btn", command=self._apply_name_edit).pack(side="left", padx=2)
        self.B(edit, "clear_btn", command=self._clear_name_edit).pack(side="left", padx=2)

        # --- formato de extraccion (liviano opcional via ffmpeg) ---
        fmt_row = ttk.Frame(f)
        fmt_row.pack(fill="x", padx=8, pady=(0, 4))
        self.L(fmt_row, "export_format_label").pack(side="left")
        self.export_format_var = tk.StringVar(value="raw")
        self.export_format_combo = ttk.Combobox(fmt_row, width=32, state="readonly")
        self.export_format_combo.pack(side="left", padx=6)
        self._export_format_codes = ["raw", "wav", "ogg", "mp3"]
        self._refresh_export_format_values()
        self.export_format_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self.export_format_var.set(
                self._export_format_codes[self.export_format_combo.current()]))

        btns = ttk.Frame(f)
        btns.pack(fill="x", padx=8, pady=(0, 4))
        self.B(btns, "extract_selected_btn", command=self._extract_selected).pack(side="left")
        self.B(btns, "extract_all_btn", command=self._extract_all).pack(side="left", padx=8)
        self.B(btns, "extract_folder_btn", command=self._extract_folder).pack(side="left", padx=8)
        self.B(btns, "link_folder_btn", command=self._link_folder).pack(side="left", padx=8)

        self.extract_log = tk.Text(f, bg=SURFACE0, fg=TEXT, insertbackground=TEXT, height=10, borderwidth=0)
        self.extract_log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _refresh_export_format_values(self):
        keys = ["export_format_raw", "export_format_wav", "export_format_ogg", "export_format_mp3"]
        values = [self.tr(k) for k in keys]
        self.export_format_combo["values"] = values
        current_code = self.export_format_var.get() if hasattr(self, "export_format_var") else "raw"
        idx = self._export_format_codes.index(current_code) if current_code in self._export_format_codes else 0
        self.export_format_combo.current(idx)

    def _pick_into(self, var, filetypes):
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p:
            var.set(p)

    def _pick_xwb(self):
        p = filedialog.askopenfilename(filetypes=[("WaveBank", "*.xwb")])
        if not p:
            return
        self.xwb_var.set(p)
        self._autofill_paired_xsb(p)

    def _pick_xsb(self):
        p = filedialog.askopenfilename(filetypes=[("SoundBank", "*.xsb")])
        if p:
            self.xsb_var.set(p)
            self._refresh_xsb_banks()

    def _autofill_paired_xsb(self, xwb_path):
        """Busca el .xsb pareja (mismo nombre, o el que lista el banco en su tabla de wavebanks)."""
        best = find_paired_xsb_for(xwb_path)
        if best:
            self.xsb_var.set(str(best))
            self.xsb_auto_label.config(text=f"(.xsb pareja detectado automaticamente: {best.name})")
        else:
            self.xsb_auto_label.config(text="(no se encontro un .xsb pareja en la misma carpeta; elegilo a mano)")
        self._refresh_xsb_banks()

    def _refresh_xsb_banks(self):
        """Llena el selector con los bancos que lista el .xsb y vuelve a 'automatico'."""
        banks = xsb_bank_names(self.xsb_var.get().strip()) if self.xsb_var.get().strip() else []
        self.xsb_bank_combo.configure(values=[AUTO_BANK_LABEL] + banks)
        self.xsb_bank_var.set(AUTO_BANK_LABEL)

    def _chosen_xsb_bank(self):
        v = self.xsb_bank_var.get().strip()
        return None if v in ("", AUTO_BANK_LABEL) else v

    def _load_bank(self):
        xwb = self.xwb_var.get().strip()
        xsb = self.xsb_var.get().strip()
        if not xwb:
            messagebox.showerror("Error", "Elegi un .xwb primero")
            return
        try:
            wb = WaveBank(xwb)
            self.wb = wb
            self.xwb_path = xwb
            self.name_overrides = {}
            num_complex = 0
            fuera_de_rango = 0
            if xsb:
                chosen = self._chosen_xsb_bank()
                bank_used = chosen or wb.bank_name or Path(xwb).stem
                banks = xsb_bank_names(xsb)
                no_match = len(banks) > 1 and bank_used.lower() not in [b.lower() for b in banks]
                raw_mapping, num_complex = parse_xsb(xsb, bank_used)
                self.cue_mapping = {}
                if no_match:
                    # el .xsb tiene varios bancos y ninguno coincide: mezclar nombres seria asignar mal
                    messagebox.showwarning("Banco del .xsb", f"El .xsb referencia {len(banks)} bancos "
                                           f"({', '.join(banks)}) y ninguno coincide con este .xwb.\n"
                                           "Elegi cual usar en 'Banco en el .xsb' y volve a cargar.")
                    raw_mapping = {}
                for name, idx in raw_mapping.items():
                    if idx < wb.entry_count:
                        self.cue_mapping[name] = idx
                    else:
                        fuera_de_rango += 1  # formato de Sound no reconocido: mejor omitir que asignar mal
            else:
                self.cue_mapping = {}
            self._refresh_bank_tree()
            warn = f" ({num_complex} cues complejos ignorados)" if num_complex else ""
            if fuera_de_rango:
                warn += f" ({fuera_de_rango} cues con indice fuera de rango, omitidos)"
            sin_cue = wb.entry_count - len(self.cue_mapping)
            self.set_status(
                f"Banco cargado: {wb.entry_count} entradas, {len(self.cue_mapping)} con nombre de cue{warn}"
                + (f", {sin_cue} sin nombre (entryNNN)" if sin_cue > 0 else ""))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _reverse_cue_names(self):
        """indice -> nombre de cue (si hay mas de un cue apuntando al mismo indice,
        se queda con el primero en orden alfabetico para que sea determinista)."""
        rev = {}
        for name, idx in sorted(self.cue_mapping.items()):
            rev.setdefault(idx, name)
        return rev

    def _effective_name(self, idx, reverse_cues=None):
        if idx in self.name_overrides:
            return self.name_overrides[idx], "editado"
        reverse_cues = reverse_cues if reverse_cues is not None else self._reverse_cue_names()
        if idx in reverse_cues:
            return reverse_cues[idx], "cue"
        return f"entry{idx:03d}", "sin cue"

    def _refresh_bank_tree(self):
        self.bank_tree.delete(*self.bank_tree.get_children())
        if not self.wb:
            return
        reverse_cues = self._reverse_cue_names()
        for i, e in enumerate(self.wb.entries):
            name, source = self._effective_name(i, reverse_cues)
            fmt_name = FMT_NAMES.get(e["format_tag"], "?")
            dur = "?"
            if e["sample_rate"]:
                dur = f"{e['duration'] / e['sample_rate']:.2f}s"
            display_name = name if source != "sin cue" else f"{name} (sin cue)"
            self.bank_tree.insert("", "end", iid=str(i), values=(i, display_name, fmt_name, dur))

    def _on_bank_select(self, _evt):
        sel = self.bank_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        name, _source = self._effective_name(idx)
        self.bank_name_edit_var.set(name)
        # propaga la seleccion a la pestana Inyectar
        self.inject_index_var.set(idx)
        self.inject_xwb_var.set(self.xwb_var.get())

    def _selected_bank_index(self):
        sel = self.bank_tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _apply_name_edit(self):
        idx = self._selected_bank_index()
        if idx is None:
            messagebox.showerror("Error", "Selecciona primero una entrada en la tabla")
            return
        new_name = self.bank_name_edit_var.get().strip()
        if not new_name:
            messagebox.showerror("Error", "El nombre no puede quedar vacio (usa Limpiar para revertirlo)")
            return
        self.name_overrides[idx] = new_name
        self._refresh_bank_tree()
        self.bank_tree.selection_set(str(idx))
        self.bank_tree.see(str(idx))
        self.set_status(f"Nombre de la entrada {idx} actualizado a '{new_name}'")

    def _clear_name_edit(self):
        idx = self._selected_bank_index()
        if idx is None:
            messagebox.showerror("Error", "Selecciona primero una entrada en la tabla")
            return
        self.name_overrides.pop(idx, None)
        self._refresh_bank_tree()
        self.bank_tree.selection_set(str(idx))
        self.bank_tree.see(str(idx))
        name, _source = self._effective_name(idx)
        self.bank_name_edit_var.set(name)
        self.set_status(f"Nombre de la entrada {idx} revertido a '{name}'")

    def _extract_selected(self):
        idx = self._selected_bank_index()
        if idx is None:
            messagebox.showerror("Error", "Selecciona primero una entrada en la tabla")
            return
        if not self.wb:
            messagebox.showerror("Error", "Carga un banco primero")
            return
        try:
            entry = self.wb.entries[idx]
            name, _source = self._effective_name(idx)
            ext, data = extract_entry_bytes(self.wb, entry, out_format=self.export_format_var.get())
            out = filedialog.asksaveasfilename(defaultextension=ext, initialfile=f"{name}{ext}")
            if not out:
                return
            Path(out).write_bytes(data)
            fmt_name = FMT_NAMES.get(entry["format_tag"], "?")
            self.extract_log.insert("end", f"[{idx}] {name} ({fmt_name}) -> {out}\n")
            self.extract_log.see("end")
            self.set_status(f"Extraido indice {idx}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _extract_all(self):
        if not self.wb:
            messagebox.showerror("Error", "Carga un banco primero")
            return
        try:
            outdir = filedialog.askdirectory()
            if not outdir:
                return
            reverse_cues = self._reverse_cue_names()
            outdir_p = Path(outdir)
            self.extract_log.delete("1.0", "end")
            out_format = self.export_format_var.get()
            for i, e in enumerate(self.wb.entries):
                label, _source = self._effective_name(i, reverse_cues)
                ext, data = extract_entry_bytes(self.wb, e, out_format=out_format)
                out_path = outdir_p / f"{label}{ext}"
                out_path.write_bytes(data)
                fmt_name = FMT_NAMES.get(e["format_tag"], "?")
                self.extract_log.insert("end", f"[{i}] {fmt_name} -> {out_path.name}\n")
                self.extract_log.see("end")
                self.update_idletasks()
            self.set_status(f"Extraidas {len(self.wb.entries)} entradas a {outdir}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _link_folder(self):
        folder = filedialog.askdirectory(title=self.tr("link_folder_btn"))
        if not folder:
            return
        try:
            report = link_report(folder)
        except Exception as ex:
            messagebox.showerror("Error", str(ex))
            return
        win = tk.Toplevel(self)
        win.title(self.tr("link_folder_btn"))
        win.geometry("900x520")
        win.minsize(420, 240)
        win.rowconfigure(0, weight=1)
        win.columnconfigure(0, weight=1)
        txt = tk.Text(win, wrap="word", bg=SURFACE0, fg=TEXT, insertbackground=TEXT, borderwidth=0)
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        txt.insert("1.0", report)

    def _extract_folder(self):
        """Busca todos los .xwb de una carpeta (no recursivo), les empareja su
        .xsb (misma logica que al cargar un banco individual), y extrae cada
        uno a una subcarpeta con el nombre del .xwb dentro de la carpeta de
        salida elegida (ej. voice.xwb -> <salida>/voice/*.wav)."""
        indir = filedialog.askdirectory(title=self.tr("extract_folder_btn"))
        if not indir:
            return
        outdir = filedialog.askdirectory(title=self.tr("export_format_label"))
        if not outdir:
            return
        indir_p = Path(indir)
        outdir_p = Path(outdir)
        xwb_files = sorted(indir_p.glob("*.xwb"))
        if not xwb_files:
            messagebox.showerror("Error", f"No se encontraron .xwb en {indir}")
            return
        out_format = self.export_format_var.get()
        self.extract_log.delete("1.0", "end")

        def run():
            total_ok, total_err, total_entries = 0, 0, 0
            for xwb_path in xwb_files:
                try:
                    xsb_path = find_paired_xsb_for(xwb_path)
                    wb = WaveBank(str(xwb_path))
                    cue_mapping = {}
                    if xsb_path:
                        raw_mapping, _num_complex = parse_xsb(str(xsb_path), wb.bank_name or xwb_path.stem)
                        for name, idx in raw_mapping.items():
                            if idx < wb.entry_count:
                                cue_mapping[name] = idx
                    reverse_cues = {}
                    for name, idx in sorted(cue_mapping.items()):
                        reverse_cues.setdefault(idx, name)
                    sub_out = outdir_p / xwb_path.stem
                    sub_out.mkdir(parents=True, exist_ok=True)
                    for i, e in enumerate(wb.entries):
                        label = reverse_cues.get(i, f"entry{i:03d}")
                        ext, data = extract_entry_bytes(wb, e, out_format=out_format)
                        (sub_out / f"{label}{ext}").write_bytes(data)
                    total_entries += wb.entry_count
                    total_ok += 1
                    pareja = xsb_path.name if xsb_path else "SIN .xsb pareja (nombres entryNNN)"
                    self.extract_log.insert(
                        "end", f"{xwb_path.name} ({pareja}): {wb.entry_count} entradas -> {sub_out}\n")
                except Exception as ex:
                    total_err += 1
                    self.extract_log.insert("end", f"{xwb_path.name}: ERROR - {ex}\n")
                self.extract_log.see("end")
                self.update_idletasks()
            resumen = f"Carpeta procesada: {total_ok} bancos, {total_entries} entradas -> {outdir_p}"
            if total_err:
                resumen += f" ({total_err} con error)"
            self.extract_log.insert("end", f"\n{resumen}\n")
            self.extract_log.see("end")
            self.set_status(resumen, ok=(total_err == 0))

        threading.Thread(target=run, daemon=True).start()

    # ---------------- Procesar tab ----------------

    def _build_process_tab(self):
        f = self.tab_process
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=8)

        self.proc_in_var = tk.StringVar()
        self.proc_out_var = tk.StringVar()
        self.proc_sr_var = tk.StringVar(value="48000")
        self.proc_ch_var = tk.StringVar(value="1")
        self.proc_ba_var = tk.StringVar(value="64")

        self.L(top, "proc_input_label").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.proc_in_var, width=55).grid(row=0, column=1, padx=6)
        self.B(top, "browse_btn", width=3, command=lambda: self._pick_into(self.proc_in_var, [("Audio", "*.wav *.mp3 *.flac *.ogg *.m4a")])).grid(row=0, column=2)

        self.L(top, "proc_sr_label").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.proc_sr_var, width=10).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))

        self.L(top, "proc_ch_label").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.proc_ch_var, width=10).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))

        self.L(top, "proc_ba_label").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.proc_ba_var, width=10).grid(row=3, column=1, sticky="w", padx=6, pady=(6, 0))

        self.B(top, "proc_convert_btn", command=self._process_audio).grid(row=4, column=0, pady=12, sticky="w")

        self.process_log = tk.Text(f, bg=SURFACE0, fg=TEXT, insertbackground=TEXT, height=16, borderwidth=0)
        self.process_log.pack(fill="both", expand=True, padx=8, pady=8)

    def _process_audio(self):
        inp = self.proc_in_var.get().strip()
        if not inp:
            messagebox.showerror("Error", "Elegi un archivo de entrada")
            return
        try:
            sr = int(self.proc_sr_var.get())
            ch = int(self.proc_ch_var.get())
            ba = int(self.proc_ba_var.get())
        except ValueError:
            messagebox.showerror("Error", "Sample rate / canales / block align deben ser numeros")
            return

        max_block, min_block = 277 * ch, 22 * ch
        is_pow2 = ba > 0 and (ba & (ba - 1)) == 0
        if not (min_block <= ba <= max_block and is_pow2):
            messagebox.showerror("Error", f"Block align debe ser potencia de 2 entre {min_block} y {max_block}")
            return

        out = filedialog.asksaveasfilename(defaultextension=".wav", initialfile="procesado.wav")
        if not out:
            return

        def run():
            cmd = ["ffmpeg", "-y", "-i", inp, "-ar", str(sr), "-ac", str(ch),
                   "-acodec", "adpcm_ms", "-block_size", str(ba), out]
            self.process_log.insert("end", "Ejecutando: " + " ".join(cmd) + "\n")
            self.process_log.see("end")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.process_log.insert("end", result.stderr[-2000:] + "\n")
                self.set_status("Error en ffmpeg", ok=False)
            else:
                self.process_log.insert("end", f"Listo: {out}\n")
                self.proc_out_var.set(out)
                self.set_status(f"Procesado -> {out}")
            self.process_log.see("end")

        threading.Thread(target=run, daemon=True).start()

    # ---------------- Inyectar tab ----------------

    def _build_inject_tab(self):
        f = self.tab_inject
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=8)

        self.inject_xwb_var = tk.StringVar()
        self.inject_index_var = tk.StringVar()
        self.inject_wav_var = tk.StringVar()
        self.inject_out_var = tk.StringVar()

        self.L(top, "inject_xwb_label").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.inject_xwb_var, width=55).grid(row=0, column=1, padx=6)
        self.B(top, "browse_btn", width=3, command=lambda: self._pick_into(self.inject_xwb_var, [("WaveBank", "*.xwb")])).grid(row=0, column=2)

        self.L(top, "inject_index_label").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.inject_index_var, width=10).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        self.L(top, "inject_index_hint", style="Sub.TLabel").grid(row=1, column=2, columnspan=2, sticky="w")

        self.L(top, "inject_wav_label").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.inject_wav_var, width=55).grid(row=2, column=1, padx=6, pady=(6, 0))
        self.B(top, "browse_btn", width=3, command=lambda: self._pick_into(self.inject_wav_var, [("WAV / XWMA", "*.wav *.xwma")])).grid(row=2, column=2, pady=(6, 0))
        self.B(top, "inject_use_last_btn", command=lambda: self.inject_wav_var.set(self.proc_out_var.get())).grid(row=2, column=3, padx=6, pady=(6, 0))
        self.B(top, "inject_convert_wma_btn", command=self._convert_wma).grid(row=4, column=0, columnspan=2, pady=(6, 0), sticky="w")

        self.B(top, "inject_btn", command=self._inject).grid(row=3, column=0, pady=12, sticky="w")

        # --- Auto-encode WMA (WMAEncodeRS.exe) ---
        enc = self.LF(f, "wma_frame_title")
        enc.pack(fill="x", padx=8, pady=(0, 8))

        self.wma_exe_var = tk.StringVar(value=str(find_wma_encoder() or ""))
        self.wma_src_wav_var = tk.StringVar()
        self.wma_codec_var = tk.StringVar(value="pro")
        self.wma_bitrate_var = tk.StringVar(value="192")

        self.L(enc, "wma_encoder_label").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(enc, textvariable=self.wma_exe_var, width=45).grid(row=0, column=1, padx=6)
        self.B(enc, "browse_btn", width=3, command=lambda: self._pick_into(self.wma_exe_var, [("Ejecutable", "*.exe")])).grid(row=0, column=2)
        status = "detectado" if find_wma_encoder() else "no encontrado junto a la herramienta"
        ttk.Label(enc, text=f"({status})", style="Sub.TLabel").grid(row=0, column=3, sticky="w", padx=6)

        self.L(enc, "wma_src_label").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(enc, textvariable=self.wma_src_wav_var, width=45).grid(row=1, column=1, padx=6)
        self.B(enc, "browse_btn", width=3, command=lambda: self._pick_into(self.wma_src_wav_var, [("WAV", "*.wav")])).grid(row=1, column=2)

        self.L(enc, "wma_codec_label").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(enc, textvariable=self.wma_codec_var, values=["pro", "standard"], width=10, state="readonly").grid(row=2, column=1, sticky="w", padx=6)
        self.L(enc, "wma_bitrate_label").grid(row=2, column=2, sticky="e")
        ttk.Combobox(enc, textvariable=self.wma_bitrate_var, values=[str(b) for b in VALID_XWMA_BITRATES], width=6, state="readonly").grid(row=2, column=3, sticky="w", padx=6)

        self.L(enc, "wma_auto_hint", style="Sub.TLabel").grid(row=3, column=0, columnspan=4, sticky="w", padx=6)
        self.B(enc, "wma_encode_btn", command=self._auto_encode_wma).grid(row=4, column=0, columnspan=2, pady=6, sticky="w")

        # --- XMA2 (xma2encode.exe) ---
        xf = self.LF(f, "xma_frame_title")
        xf.pack(fill="x", padx=8, pady=(0, 8))
        self.xma_exe_var = tk.StringVar(value=str(find_xma2_encoder() or ""))
        self.xma_mode_var = tk.StringVar(value="auto")
        self.xma_quality_var = tk.StringVar(value=str(XMA_SETTINGS["quality"]))
        self.xma_block_var = tk.StringVar(value=str(XMA_SETTINGS["block_kb"]))
        self.L(xf, "xma_encoder_label").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(xf, textvariable=self.xma_exe_var, width=45).grid(row=0, column=1, padx=6)
        self.B(xf, "browse_btn", width=3, command=lambda: self._pick_into(self.xma_exe_var, [("Ejecutable", "*.exe")])).grid(row=0, column=2)
        self.L(xf, "xma_mode_label").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(xf, textvariable=self.xma_mode_var, values=["auto", "xma2", "pcm"], width=8, state="readonly").grid(row=1, column=1, sticky="w", padx=6)
        self.L(xf, "xma_quality_label").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(xf, textvariable=self.xma_quality_var, width=6).grid(row=2, column=1, sticky="w", padx=6)
        self.L(xf, "xma_block_label").grid(row=2, column=1, sticky="e")
        ttk.Entry(xf, textvariable=self.xma_block_var, width=6).grid(row=2, column=2, sticky="w", padx=6)
        self.L(xf, "xma_hint", style="Sub.TLabel").grid(row=3, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 4))

        self.inject_log = tk.Text(f, bg=SURFACE0, fg=TEXT, insertbackground=TEXT, height=12, borderwidth=0)
        self.inject_log.pack(fill="both", expand=True, padx=8, pady=8)

    def _convert_wma(self):
        wma = filedialog.askopenfilename(filetypes=[("WMA (ASF)", "*.wma")])
        if not wma:
            return
        out = filedialog.asksaveasfilename(defaultextension=".xwma",
                                            initialfile=Path(wma).stem + ".xwma")
        if not out:
            return
        try:
            Path(out).write_bytes(convert_wma_to_xwma(wma))
            self.inject_wav_var.set(out)
            self.inject_log.insert("end", f"Convertido {wma} -> {out}\n\n")
            self.inject_log.see("end")
            self.set_status(f"Convertido -> {out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _auto_encode_wma(self):
        exe = self.wma_exe_var.get().strip()
        wav = self.wma_src_wav_var.get().strip()
        if not exe or not Path(exe).is_file():
            messagebox.showerror("Error", "No se encontro WMAEncodeRS.exe (indicalo manualmente)")
            return
        if not wav:
            messagebox.showerror("Error", "Falta el .wav fuente")
            return

        channels = sample_rate = None
        xwb, idx_str = self.inject_xwb_var.get().strip(), self.inject_index_var.get().strip()
        if xwb and idx_str:
            try:
                wb = WaveBank(xwb)
                e = wb.entries[int(idx_str)]
                channels, sample_rate = e["channels"], e["sample_rate"]
                self.inject_log.insert("end", f"Target detectado: {channels} canales, {sample_rate} Hz "
                                               f"(entrada {idx_str} de {Path(xwb).name})\n")
            except Exception:
                pass  # sin .xwb/indice validos, se encodea con los canales/rate originales del wav

        out = filedialog.asksaveasfilename(defaultextension=".xwma", initialfile=Path(wav).stem + ".xwma")
        if not out:
            return

        def run():
            try:
                auto_encode_to_xwma(exe, wav, out, codec=self.wma_codec_var.get(),
                                     bitrate=int(self.wma_bitrate_var.get()),
                                     channels=channels, sample_rate=sample_rate)
                self.inject_wav_var.set(out)
                self.inject_log.insert("end", f"Encodeado y convertido -> {out}\n\n")
                self.inject_log.see("end")
                self.set_status(f"Encodeado -> {out}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        threading.Thread(target=run, daemon=True).start()

    def _apply_xma_settings(self):
        try:
            XMA_SETTINGS["quality"] = int(self.xma_quality_var.get())
            XMA_SETTINGS["block_kb"] = int(self.xma_block_var.get())
        except ValueError:
            pass
        XMA_SETTINGS["mode"] = self.xma_mode_var.get() or "auto"
        exe = self.xma_exe_var.get().strip()
        XMA_SETTINGS["exe"] = exe or None

    def _inject(self):
        self._apply_xma_settings()
        xwb = self.inject_xwb_var.get().strip()
        wav = self.inject_wav_var.get().strip()
        if not xwb or not wav:
            messagebox.showerror("Error", "Falta el .xwb o el .wav de reemplazo")
            return
        try:
            idx = int(self.inject_index_var.get())
        except ValueError:
            messagebox.showerror("Error", "El indice debe ser un numero")
            return

        out = filedialog.asksaveasfilename(defaultextension=".xwb",
                                            initialfile=Path(xwb).stem + "_patched.xwb")
        if not out:
            return
        try:
            wb = WaveBank(xwb)
            old_entry, new_fmt, new_len, delta, warnings = inject_entry(wb, idx, wav, out)
            old_fmt = FMT_NAMES.get(old_entry["format_tag"], "?")
            new_fmt_name = FMT_NAMES.get(new_fmt, "?")
            self.inject_log.insert(
                "end",
                f"Indice {idx}: {old_fmt} ({old_entry['play_len']} bytes) -> "
                f"{new_fmt_name} ({new_len} bytes), delta {delta:+d}\n"
                f"Escrito: {out}\n",
            )
            for w in warnings:
                self.inject_log.insert("end", f"  ATENCION: {w}\n")
            self.inject_log.insert("end", "\n")
            self.inject_log.see("end")
            self.set_status(f"Inyectado indice {idx} -> {out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _build_batch_tab(self):
        f = self.tab_batch
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=8)

        self.batch_xwb_var = tk.StringVar()
        self.batch_manifest_var = tk.StringVar()
        self.batch_folder_var = tk.StringVar()

        self.L(top, "batch_xwb_label").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.batch_xwb_var, width=55).grid(row=0, column=1, padx=6)
        self.B(top, "browse_btn", width=3, command=lambda: self._pick_into(self.batch_xwb_var, [("XWB", "*.xwb")])).grid(row=0, column=2)

        self.L(top, "batch_manifest_label").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.batch_manifest_var, width=55).grid(row=1, column=1, padx=6, pady=(6, 0))
        self.B(top, "browse_btn", width=3, command=lambda: self._pick_into(self.batch_manifest_var, [("JSON", "*.json")])).grid(row=1, column=2, pady=(6, 0))

        self.L(top, "batch_folder_label").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.batch_folder_var, width=55).grid(row=2, column=1, padx=6, pady=(6, 0))
        self.B(top, "browse_btn", width=3, command=self._pick_batch_folder).grid(row=2, column=2, pady=(6, 0))

        btns = ttk.Frame(top)
        btns.grid(row=3, column=0, columnspan=3, pady=10, sticky="w")
        self.B(btns, "batch_dry_run_btn", command=lambda: self._run_batch(dry_run=True)).pack(side="left")
        self.B(btns, "batch_run_btn", command=lambda: self._run_batch(dry_run=False)).pack(side="left", padx=8)

        self.batch_log = tk.Text(f, bg=SURFACE0, fg=TEXT, insertbackground=TEXT, height=14, borderwidth=0)
        self.batch_log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # --- Recorte de audio ---
        trim = self.LF(f, "trim_frame_title")
        trim.pack(fill="x", padx=8, pady=(0, 8))

        self.trim_in_var = tk.StringVar()
        self.trim_out_var = tk.StringVar()
        self.trim_start_var = tk.StringVar()
        self.trim_end_var = tk.StringVar()
        self.trim_auto_var = tk.BooleanVar(value=False)

        self.L(trim, "trim_src_label").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(trim, textvariable=self.trim_in_var, width=40).grid(row=0, column=1, padx=6)
        self.B(trim, "browse_btn", width=3, command=lambda: self._pick_into(self.trim_in_var, [("WAV", "*.wav")])).grid(row=0, column=2)

        self.L(trim, "trim_start_label").grid(row=1, column=0, sticky="w", padx=6)
        ttk.Entry(trim, textvariable=self.trim_start_var, width=8).grid(row=1, column=1, sticky="w", padx=6)
        self.L(trim, "trim_end_label").grid(row=1, column=2, sticky="e")
        ttk.Entry(trim, textvariable=self.trim_end_var, width=8).grid(row=1, column=3, sticky="w", padx=6)
        cb = ttk.Checkbutton(trim, text=self.tr("trim_auto_check"), variable=self.trim_auto_var)
        cb.grid(row=2, column=0, columnspan=4, sticky="w", padx=6, pady=(4, 0))
        self._reg(cb, "trim_auto_check", "text")

        self.B(trim, "trim_btn", command=self._do_trim).grid(row=3, column=0, pady=8, sticky="w")

    def _pick_batch_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.batch_folder_var.set(d)

    def _run_batch(self, dry_run):
        self._apply_xma_settings()
        xwb = self.batch_xwb_var.get().strip()
        manifest = self.batch_manifest_var.get().strip()
        folder = self.batch_folder_var.get().strip()
        if not (xwb and manifest and folder):
            messagebox.showerror("Error", "Falta el .xwb, el manifiesto o la carpeta de audios")
            return

        def run():
            try:
                replacements, missing = load_manifest_replacements(manifest, folder)
                self.batch_log.insert("end", f"{len(replacements)} entradas mapeadas, {len(missing)} sin archivo\n")
                for m_ in missing[:20]:
                    self.batch_log.insert("end", f"  falta: {m_}\n")
                if missing and len(missing) > 20:
                    self.batch_log.insert("end", f"  ... y {len(missing) - 20} mas\n")
                if not replacements:
                    self.batch_log.insert("end", "Nada para hacer.\n\n")
                    self.batch_log.see("end")
                    return

                wb = WaveBank(xwb)
                if dry_run:
                    total_delta, con_warning = 0, 0
                    for i in sorted(replacements):
                        if i >= wb.entry_count:
                            self.batch_log.insert("end", f"  indice {i} fuera de rango, se omite\n")
                            continue
                        try:
                            wav_fmt, pcm = read_riff_wav(replacements[i])
                            _, fmt_tag, ba, ch = build_mini_waveformat(wav_fmt)
                        except Exception:
                            self.batch_log.insert("end", f"  [{i}] {Path(replacements[i]).name}: se convertira al inyectar\n")
                            continue
                        e = wb.entries[i]
                        delta = len(pcm) - e["play_len"]
                        total_delta += delta
                        warn = e["format_tag"] == FMT_ADPCM and e["block_align"] != ba
                        con_warning += warn
                        flag = "  ATENCION block_align distinto" if warn else ""
                        self.batch_log.insert("end", f"  [{i}] {e['play_len']} -> {len(pcm)} ({delta:+d}){flag}\n")
                    self.batch_log.insert("end", f"\nDelta estimado (sin contar el padding entre entradas "
                                                  f"que el modo real tambien elimina): {total_delta:+d} bytes\n")
                    if con_warning:
                        self.batch_log.insert("end", f"{con_warning} entradas con block_align distinto al original.\n")
                    self.batch_log.insert("end", "(Simulacion: no se escribio ningun archivo)\n\n")
                else:
                    out = filedialog.asksaveasfilename(defaultextension=".xwb",
                                                        initialfile=Path(xwb).stem + "_batch.xwb")
                    if not out:
                        return
                    report_path = str(Path(out).with_suffix("")) + "_changelog.json"
                    report = batch_inject_entries(wb, {i: replacements[i] for i in replacements if i < wb.entry_count},
                                                   out, report_path=report_path)
                    for r in report:
                        flag = f"  ATENCION: {'; '.join(r['warnings'])}" if r["warnings"] else ""
                        self.batch_log.insert("end", f"  [{r['index']}] {r['old_bytes']} -> {r['new_bytes']} "
                                                      f"({r['delta_bytes']:+d}){flag}\n")
                    self.batch_log.insert("end", f"\n{len(report)} entradas escritas -> {out}\n"
                                                  f"Changelog: {report_path}\n\n")
                    self.set_status(f"Lote inyectado -> {out}")
                self.batch_log.see("end")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        threading.Thread(target=run, daemon=True).start()

    def _do_trim(self):
        src = self.trim_in_var.get().strip()
        if not src:
            messagebox.showerror("Error", "Falta el .wav fuente")
            return
        out = filedialog.asksaveasfilename(defaultextension=".wav", initialfile=Path(src).stem + "_trim.wav")
        if not out:
            return
        start = self.trim_start_var.get().strip()
        end = self.trim_end_var.get().strip()
        try:
            trim_wav_pcm(src, out,
                         start_seconds=float(start) if start else None,
                         end_seconds=float(end) if end else None,
                         trim_silence=self.trim_auto_var.get() and not (start or end))
            self.batch_log.insert("end", f"Recortado {src} -> {out}\n\n")
            self.batch_log.see("end")
            self.set_status(f"Recortado -> {out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--link":
        print(link_report(sys.argv[2]))
    elif len(sys.argv) >= 5 and sys.argv[1] == "--xsb2-split":
        print(f"{split_xsb2(sys.argv[2], sys.argv[3], sys.argv[4])} entradas -> {sys.argv[4]}")
    elif "--classic" in sys.argv:
        main()
    else:
        # Interfaz nueva (CustomTkinter) si esta DP_Audio_Studio.py al lado y las dependencias estan instaladas;
        # si no, la interfaz clasica de siempre.
        try:
            import DP_Audio_Studio as _studio
        except Exception as _ex:
            print(f"[aviso] No se pudo abrir la interfaz nueva ({_ex.__class__.__name__}: {_ex}); "
                  "uso la clasica. Para la nueva: pip install customtkinter pillow pygame")
            main()
        else:
            try:
                _studio.main()
            except SystemExit as _e:
                if _e.code not in (0, None):
                    print("[aviso] El Studio no pudo iniciar (detalle en dp_studio_error.log); abro la interfaz clasica.")
                    main()
