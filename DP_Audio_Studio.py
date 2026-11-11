#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deadly Premonition - Audio Studio
=================================
Una sola ventana para trabajar con un banco (.xwb) y su .xsb:
  * escuchar cada entrada, ponerle nombre y clasificarla (York, Emily, George, Otro) -> JSON
  * reemplazar audio: el archivo nuevo se convierte solo al MISMO códec de la entrada original
    (XMA2 con xma2encode, WMA Pro / estándar con WMAEncodeRS, MS-ADPCM y PCM con ffmpeg),
    se crea el banco nuevo y el anterior queda renombrado como .bak
  * extraer entradas (con los nombres puestos, opcionalmente separadas por personaje)

Requisitos:
  pip install customtkinter pillow pygame
  ffmpeg en el PATH; xma2encode.exe y WMAEncodeRS.exe junto a la herramienta (o en Ajustes)
  Deadly_Premonition_XBOX_Audio_extractor.py en la misma carpeta (motor de lectura/escritura de bancos)

Deadly Premonition 2 (Unity): selector de juego arriba a la derecha; usa dp2_panel.py (pip install UnityPy).

Atajos:  Y / E / G / O = York / Emily / George / Otro,  Supr = quitar etiqueta,
         Espacio = reproducir/pausar,  flechas o N / P = siguiente / anterior,  Ctrl+S = guardar JSON.
"""
import array
import colorsys
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))      # True cuando corre como .exe (PyInstaller)


def app_dir():
    """Carpeta para ajustes y registro de errores. Como .exe, junto al ejecutable (portatil); si no se puede
    escribir ahi (p.ej. Program Files), en %APPDATA%\\DP_Audio_Studio. En desarrollo, junto al script.
    (No usar la carpeta del script: en un .exe de un solo archivo es temporal y se borra al cerrar.)"""
    if not FROZEN:
        return HERE
    d = Path(sys.executable).resolve().parent
    try:
        probe = d / ".dp_write_test"
        probe.write_text("x")
        probe.unlink()
        return d
    except OSError:
        base = Path(os.environ.get("APPDATA") or Path.home()) / "DP_Audio_Studio"
        base.mkdir(parents=True, exist_ok=True)
        return base


APP_DIR = app_dir()

try:
    import dp_dependencies as deps      # descargador de dependencias (Ajustes)
except Exception:
    deps = None

# ----------------------------------------------------------------------------------------------
#  Idioma de la interfaz (es / en / ru). El texto fuente está en español; I18N (al final del archivo)
#  guarda la traducción de cada texto. Se elige en Ajustes y se aplica al reiniciar el programa.
# ----------------------------------------------------------------------------------------------
LANGS = {"es": "Español", "en": "English", "ru": "Русский"}
# {texto_en_español: (inglés, ruso)}
I18N = {
    'Principales': ('Main characters', 'Главные персонажи'),
    'Policía y sanidad': ('Police & medical', 'Полиция и медицина'),
    'Residentes': ('Residents', 'Жители'),
    'Víctimas y allegados': ('Victims & relatives', 'Жертвы и близкие'),
    'Gemelos Ingram': ('Ingram twins', 'Близнецы Ингрэм'),
    'Voces genéricas': ('Generic voices', 'Обычные голоса'),
    'Personales': ('Personal', 'Личные'),
    'Otros': ('Others', 'Прочие'),
    'Automático': ('Automatic', 'Автоматически'),
    'Todos': ('All', 'Все'),
    'Sin clasificar': ('Unlabeled', 'Без метки'),
    'Sin .xsb: se usan nombres entryNNN. Usá «Elegir XSB…» y después el banco que corresponda.': ('No .xsb: entryNNN names are used. Use “Choose XSB…” and then pick the matching bank.', 'Нет .xsb: используются имена entryNNN. Нажмите «Выбрать XSB…», затем выберите нужный банк.'),
    'El .xsb referencia {0} bancos ({1}) y ninguno coincide con este .xwb: elegí cuál usar en «Banco del XSB».': ('The .xsb references {0} banks ({1}) and none matches this .xwb: choose one in “XSB bank”.', 'В .xsb указано банков: {0} ({1}), и ни один не совпадает с этим .xwb: выберите нужный в поле «Банк XSB».'),
    'No se pudo leer el .xsb: {0}': ('Could not read the .xsb: {0}', 'Не удалось прочитать .xsb: {0}'),
    "Banco '{0}': {1} cues, pero el track más alto es {2} y el .xwb tiene {3} entradas. ¿Es el banco correcto?": ("Bank '{0}': {1} cues, but the highest track is {2} and the .xwb has {3} entries. Is this the right bank?", "Банк '{0}': cue — {1}, но наибольший трек — {2}, а в .xwb записей: {3}. Это нужный банк?"),
    "Banco '{0}': {1} entradas con nombre de {2} (las demás quedan como entryNNN).": ("Bank '{0}': {1} named entries out of {2} (the rest stay as entryNNN).", "Банк '{0}': {1} записей с именами из {2} (остальные остаются как entryNNN)."),
    "Banco '{0}': {1} de {2} entradas con nombre.": ("Bank '{0}': {1} of {2} entries named.", "Банк '{0}': {1} из {2} записей имеют имена."),
    'el archivo no parece un JSON de este clasificador': ('the file does not look like a JSON from this classifier', 'файл не похож на JSON этого классификатора'),
    'ffmpeg no produjo audio': ('ffmpeg produced no audio', 'ffmpeg не вернул аудио'),
    'Convertir al mismo códec del original (recomendado)': ('Convert to the original codec (recommended)', 'Конвертировать в исходный кодек (рекомендуется)'),
    'Inyectar tal cual': ('Inject as is', 'Вставлять как есть'),
    'Sin decodificar (original)': ('Not decoded (original)', 'Без декодирования (оригинал)'),
    'Códec original: {0}. Se inyectará el archivo tal cual (política «tal cual»).': ('Original codec: {0}. The file will be injected as is (“as is” policy).', 'Исходный кодек: {0}. Файл будет вставлен как есть (политика «как есть»).'),
    'Códec original: {0}. Falta ffmpeg: sin él no se puede convertir.': ('Original codec: {0}. ffmpeg is missing: conversion is not possible without it.', 'Исходный кодек: {0}. Нет ffmpeg: без него конвертация невозможна.'),
    'Códec original: {0}. Tu audio se convertirá a XMA2 con xma2encode.': ('Original codec: {0}. Your audio will be converted to XMA2 with xma2encode.', 'Исходный кодек: {0}. Ваше аудио будет конвертировано в XMA2 через xma2encode.'),
    'Códec original: {0}. Sin xma2encode se inyectará como PCM 16-bit (el banco crece).': ('Original codec: {0}. Without xma2encode it will be injected as 16-bit PCM (the bank grows).', 'Исходный кодек: {0}. Без xma2encode аудио будет вставлено как 16-бит PCM (банк увеличится).'),
    'Códec original: {0}. Se convertirá con WMAEncodeRS a {1} ({2} kbps, {3} canal(es)).': ('Original codec: {0}. It will be converted with WMAEncodeRS to {1} ({2} kbps, {3} channel(s)).', 'Исходный кодек: {0}. Будет конвертировано через WMAEncodeRS в {1} ({2} кбит/с, каналов: {3}).'),
    'Códec original: {0}. Falta WMAEncodeRS.exe: no se podrá reemplazar esta entrada.': ('Original codec: {0}. WMAEncodeRS.exe is missing: this entry cannot be replaced.', 'Исходный кодек: {0}. Нет WMAEncodeRS.exe: эту запись заменить нельзя.'),
    'Códec original: {0}. Se convertirá a MS-ADPCM con ffmpeg.': ('Original codec: {0}. It will be converted to MS-ADPCM with ffmpeg.', 'Исходный кодек: {0}. Будет конвертировано в MS-ADPCM через ffmpeg.'),
    'Códec original: {0}. Se convertirá a PCM 16-bit.': ('Original codec: {0}. It will be converted to 16-bit PCM.', 'Исходный кодек: {0}. Будет конвертировано в 16-бит PCM.'),
    '{0} entradas clasificadas como «{1}».': ('{0} entries labeled «{1}».', 'Записей с меткой «{1}»: {0}.'),
    'Etiqueta quitada de {0} entradas.': ('Label removed from {0} entries.', 'Метка убрана у записей: {0}.'),
    '{0} entradas renombradas como «{1}_NN».': ('{0} entries renamed «{1}_NN».', 'Записей переименовано: {0} («{1}_NN»).'),
    'Nombre original restaurado en {0} entradas.': ('Original name restored on {0} entries.', 'Исходное имя восстановлено у записей: {0}.'),
    'Listo. Abrí un banco (.xwb) para empezar.': ('Ready. Open a bank (.xwb) to start.', 'Готово. Откройте банк (.xwb), чтобы начать.'),
    'Abrir banco…': ('Open bank…', 'Открыть банк…'),
    'Elegir XSB…': ('Choose XSB…', 'Выбрать XSB…'),
    'Cargar JSON': ('Load JSON', 'Загрузить JSON'),
    'Guardar JSON': ('Save JSON', 'Сохранить JSON'),
    'Ajustes': ('Settings', 'Настройки'),
    'Ningún banco abierto': ('No bank open', 'Банк не открыт'),
    'Banco del XSB:': ('XSB bank:', 'Банк XSB:'),
    'Registro': ('Log', 'Журнал'),
    'Buscar por nombre o número…': ('Search by name or number…', 'Поиск по имени или номеру…'),
    'Nombre': ('Name', 'Имя'),
    'Códec': ('Codec', 'Кодек'),
    'Personaje': ('Label', 'Метка'),
    'Elegí una entrada': ('Pick an entry', 'Выберите запись'),
    '▶ Reproducir': ('▶ Play', '▶ Играть'),
    'Clasificar': ('Classify', 'Метки'),
    'Reemplazar': ('Replace', 'Замена'),
    'Extraer': ('Extract', 'Извлечение'),
    'Nombre de la entrada': ('Entry name', 'Имя записи'),
    'Renombrar': ('Rename', 'Переименовать'),
    'Importar nombres desde una carpeta de referencia…': ('Import names from a reference folder…', 'Импорт имён из папки-образца…'),
    '¿Quién habla?': ('Who is speaking?', 'Кто говорит?'),
    'Buscar personaje de Greenvale…': ('Search Greenvale character…', 'Поиск персонажа Гринвейла…'),
    'Etiqueta personal (cinemática, OST, efectos…)': ('Personal label (cinematic, OST, SFX…)', 'Своя метка (ролик, OST, эффекты…)'),
    'Asignar': ('Assign', 'Назначить'),
    'Para lo que no es una persona (cinemáticas, OST…). Queda guardada en la lista, grupo «Personales».': ("For things that aren't a person (cinematics, OST…). It is saved in the list, “Personal” group.", 'Для всего, что не персонаж (ролики, OST…). Метка сохраняется в списке, в группе «Личные».'),
    'Quitar etiqueta   [Supr]': ('Remove label   [Del]', 'Убрать метку   [Del]'),
    'Pasar a la siguiente al clasificar': ('Advance to the next entry after labeling', 'Переходить к следующей записи после метки'),
    'Reproducir al seleccionar': ('Play on select', 'Играть при выборе'),
    'Autoguardar el JSON': ('Autosave JSON', 'Автосохранение JSON'),
    'Sin resultados': ('No results', 'Ничего не найдено'),
    'Escribí la etiqueta personal primero.': ('Type the personal label first.', 'Сначала введите свою метку.'),
    'Elegí una entrada de la lista primero.': ('Pick an entry from the list first.', 'Сначала выберите запись в списке.'),
    'Elegí una entrada para ver qué códec usa.': ('Pick an entry to see which codec it uses.', 'Выберите запись, чтобы увидеть её кодек.'),
    'Reemplazar el audio de esta entrada…': ("Replace this entry's audio…", 'Заменить аудио этой записи…'),
    'Reemplazar varias desde una carpeta…': ('Replace several from a folder…', 'Заменить несколько из папки…'),
    'Elegí cualquier audio (wav, mp3, ogg, flac…): se convierte solo al mismo códec que tenía la entrada, se crea el banco nuevo y el anterior queda renombrado como .bak.\n\nEn la carpeta, cada archivo debe llamarse como la entrada (su nombre o entryNNN).': ("Pick any audio (wav, mp3, ogg, flac…): it is converted automatically to the entry's original codec, the new bank is created and the previous one is renamed to .bak.\n\nIn a folder, each file must be named like the entry (its name or entryNNN).", 'Выберите любое аудио (wav, mp3, ogg, flac…): оно автоматически конвертируется в исходный кодек записи, создаётся новый банк, а прежний переименовывается в .bak.\n\nВ папке каждый файл должен называться как запись (её имя или entryNNN).'),
    'Formato de salida': ('Output format', 'Формат вывода'),
    'Separar en carpetas por personaje': ('Split into folders by label', 'Раскладывать по папкам по меткам'),
    'Extraer las seleccionadas…': ('Extract selected…', 'Извлечь выбранные…'),
    'Extraer todas…': ('Extract all…', 'Извлечь все…'),
    'Los archivos salen con el nombre que le pusiste (o el del .xsb). Con Ctrl o Mayús en la lista elegís varias.': ("Files are saved with the name you gave them (or the .xsb's). Use Ctrl or Shift in the list to select several.", 'Файлы сохраняются под заданным вами именем (или именем из .xsb). Выбирайте несколько записей с Ctrl или Shift.'),
    'no se encontró ffmpeg (no se podrá escuchar XMA/xWMA ni convertir)': ("ffmpeg not found (XMA/xWMA can't be played and nothing can be converted)", 'ffmpeg не найден (XMA/xWMA не воспроизвести, конвертация невозможна)'),
    'sin xma2encode.exe (XMA2 se inyectaría como PCM)': ('no xma2encode.exe (XMA2 would be injected as PCM)', 'нет xma2encode.exe (XMA2 будет вставлен как PCM)'),
    'sin WMAEncodeRS.exe (no se podrá reemplazar audio WMA)': ("no WMAEncodeRS.exe (WMA audio can't be replaced)", 'нет WMAEncodeRS.exe (аудио WMA заменить нельзя)'),
    'sin salida de audio: pip install pygame': ('no audio output: pip install pygame', 'нет вывода звука: pip install pygame'),
    'sin pygame no hay pausa ni barra de tiempo (pip install pygame)': ('without pygame there is no pause or time bar (pip install pygame)', 'без pygame нет паузы и полосы времени (pip install pygame)'),
    'Listo. Abrí un .xwb para empezar.': ('Ready. Open an .xwb to start.', 'Готово. Откройте .xwb, чтобы начать.'),
    'Atención: ': ('Warning: ', 'Внимание: '),
    'Hay otra operación en curso; esperá a que termine.': ('Another operation is running; wait until it finishes.', 'Выполняется другая операция; дождитесь её завершения.'),
    'Examinar…': ('Browse…', 'Обзор…'),
    'Se aplica al reiniciar el programa.': ('Takes effect after restarting the program.', 'Применится после перезапуска программы.'),
    'Detectado: {0}': ('Detected: {0}', 'Найдено: {0}'),
    'No se encontró en el PATH (indicá ffmpeg.exe).': ('Not found in PATH (set ffmpeg.exe).', 'Не найден в PATH (укажите ffmpeg.exe).'),
    'XMA2 · xma2encode.exe': ('XMA2 · xma2encode.exe', 'XMA2 · xma2encode.exe'),
    'Ejecutable': ('Executable', 'Исполняемый файл'),
    'No encontrado junto al programa (ni empaquetado).': ('Not found next to the program (nor bundled).', 'Не найден рядом с программой (и не встроен).'),
    'Modo:': ('Mode:', 'Режим:'),
    'Calidad (/Quality):': ('Quality (/Quality):', 'Качество (/Quality):'),
    'Bloque en KB (/BlockSize):': ('Block size in KB (/BlockSize):', 'Размер блока, КБ (/BlockSize):'),
    'auto = XMA2 si hay encoder, si no PCM · xma2 = exigir el encoder · pcm = siempre PCM.': ('auto = XMA2 if an encoder exists, otherwise PCM · xma2 = require the encoder · pcm = always PCM.', 'auto = XMA2, если есть кодировщик, иначе PCM · xma2 = требовать кодировщик · pcm = всегда PCM.'),
    'WMA Pro / estándar · WMAEncodeRS.exe': ('WMA Pro / standard · WMAEncodeRS.exe', 'WMA Pro / стандартный · WMAEncodeRS.exe'),
    'Bitrate (kbps):': ('Bitrate (kbps):', 'Битрейт (кбит/с):'),
    'auto = el perfil más cercano al de la entrada original.': ("auto = the profile closest to the original entry's.", 'auto = профиль, ближайший к исходной записи.'),
    'Al reemplazar': ('When replacing', 'При замене'),
    'Códec:': ('Codec:', 'Кодек:'),
    'Renombrar el banco anterior como .bak (nunca pisa un backup existente)': ('Rename the previous bank to .bak (never overwrites an existing backup)', 'Переименовывать прежний банк в .bak (существующую копию не затирает)'),
    'Personajes de Greenvale': ('Greenvale characters', 'Персонажи Гринвейла'),
    'Una línea por personaje; las líneas que empiezan con # son títulos de grupo. Podés agregar, quitar o renombrar. Los nombres ya usados en un JSON se conservan.': ('One line per character; lines starting with # are group titles. You can add, remove or rename. Names already used in a JSON are kept.', 'Одна строка — один персонаж; строки, начинающиеся с #, — заголовки групп. Можно добавлять, удалять и переименовывать. Имена, уже использованные в JSON, сохраняются.'),
    'Restaurar la lista de Greenvale': ('Restore the Greenvale list', 'Восстановить список Гринвейла'),
    'Ajustes guardados.': ('Settings saved.', 'Настройки сохранены.'),
    'Guardar': ('Save', 'Сохранить'),
    'Cancelar': ('Cancel', 'Отмена'),
    'Falta el lector de bancos': ('Bank reader missing', 'Нет модуля чтения банков'),
    'Poné Deadly_Premonition_XBOX_Audio_extractor.py junto a este archivo.': ('Put Deadly_Premonition_XBOX_Audio_extractor.py next to this file.', 'Положите Deadly_Premonition_XBOX_Audio_extractor.py рядом с этим файлом.'),
    'Hay una operación en curso.': ('An operation is in progress.', 'Идёт операция.'),
    'Abrir banco de ondas': ('Open wave bank', 'Открыть wave bank'),
    'Leyendo banco…': ('Reading bank…', 'Чтение банка…'),
    'No se pudo abrir el banco': ('Could not open the bank', 'Не удалось открыть банк'),
    'Error al abrir el banco.': ('Error opening the bank.', 'Ошибка при открытии банка.'),
    'Primero abrí un banco.': ('Open a bank first.', 'Сначала откройте банк.'),
    'Elegir XSB': ('Choose XSB', 'Выбрать XSB'),
    '{0}  ·  {1} entradas  ·  XSB: {2}': ('{0}  ·  {1} entries  ·  XSB: {2}', '{0}  ·  записей: {1}  ·  XSB: {2}'),
    "Banco '{0}' abierto: {1} entradas, {2} con nombre.": ("Bank '{0}' opened: {1} entries, {2} named.", "Банк '{0}' открыт: записей {1}, с именами {2}."),
    ' JSON anterior cargado ({0} etiquetas': (' Previous JSON loaded ({0} labels', ' Прежний JSON загружен (меток: {0}'),
    ', {0} con nombre distinto': (', {0} with a different name', ', с другим именем: {0}'),
    ' (No se pudo leer {0}: {1})': (' (Could not read {0}: {1})', ' (Не удалось прочитать {0}: {1})'),
    'No se pudo releer el banco': ('Could not re-read the bank', 'Не удалось перечитать банк'),
    'Cambios sin guardar': ('Unsaved changes', 'Несохранённые изменения'),
    'Hay etiquetas sin guardar. ¿Guardar el JSON antes de seguir?': ('There are unsaved labels. Save the JSON before continuing?', 'Есть несохранённые метки. Сохранить JSON перед продолжением?'),
    'No se pudo autoguardar: {0}': ('Could not autosave: {0}', 'Не удалось автосохранить: {0}'),
    'No hay nada que guardar: abrí un banco primero.': ('Nothing to save: open a bank first.', 'Нечего сохранять: сначала откройте банк.'),
    'No se pudo guardar': ('Could not save', 'Не удалось сохранить'),
    'Guardado: {0}  ({1} clasificadas)': ('Saved: {0}  ({1} labeled)', 'Сохранено: {0}  (размечено: {1})'),
    'JSON guardado: {0}': ('JSON saved: {0}', 'JSON сохранён: {0}'),
    'Primero abrí el banco al que corresponde el JSON.': ('First open the bank this JSON belongs to.', 'Сначала откройте банк, к которому относится JSON.'),
    'No se pudo cargar': ('Could not load', 'Не удалось загрузить'),
    'JSON cargado: {0} etiquetas': ('JSON loaded: {0} labels', 'JSON загружен: меток {0}'),
    ', {0} descartadas': (', {0} discarded', ', отброшено: {0}'),
    ', {0} con nombre distinto al banco': (', {0} with a name different from the bank', ', с именем, отличным от банка: {0}'),
    '{0} entradas seleccionadas (usá «Extraer las seleccionadas»).': ('{0} entries selected (use “Extract selected”).', 'Выбрано записей: {0} (используйте «Извлечь выбранные»).'),
    'Falta ffmpeg en el PATH: no puedo decodificar este audio.': ("ffmpeg is missing from PATH: I can't decode this audio.", 'ffmpeg нет в PATH: не могу декодировать это аудио.'),
    'Decodificando {0}…': ('Decoding {0}…', 'Декодирование {0}…'),
    'No hay salida de audio disponible: instalá pygame (pip install pygame).': ('No audio output available: install pygame (pip install pygame).', 'Вывод звука недоступен: установите pygame (pip install pygame).'),
    '{0}  ·  {1}  ·  {2} canal(es)  ·  {3:.1f} s': ('{0}  ·  {1}  ·  {2} channel(s)  ·  {3:.1f} s', '{0}  ·  {1}  ·  каналов: {2}  ·  {3:.1f} с'),
    'duración ?': ('duration ?', 'длительность ?'),
    '#{0}  ·  {1}  ·  {2} canal(es)  ·  {3} Hz  ·  {4}': ('#{0}  ·  {1}  ·  {2} channel(s)  ·  {3} Hz  ·  {4}', '#{0}  ·  {1}  ·  каналов: {2}  ·  {3} Гц  ·  {4}'),
    'Personaje: {0}': ('Label: {0}', 'Метка: {0}'),
    ' (según los créditos)': (' (according to the credits)', ' (по титрам)'),
    'Comparte actor de voz con: ': ('Shares a voice actor with: ', 'Тот же актёр озвучки: '),
    '   (+{0} personajes más)': ('   (+{0} more labels)', '   (ещё меток: {0})'),
    'Sin clasificar: {0}': ('Unlabeled: {0}', 'Без метки: {0}'),
    '{0} / {1} clasificadas': ('{0} / {1} labeled', '{0} / {1} размечено'),
    '❚❚ Pausar': ('❚❚ Pause', '❚❚ Пауза'),
    '■ Detener': ('■ Stop', '■ Стоп'),
    '#{0} ahora se llama «{1}».': ('#{0} is now called “{1}”.', '#{0} теперь называется «{1}».'),
    'Hace falta ffmpeg para comparar los audios.': ('ffmpeg is needed to compare audio.', 'Для сравнения аудио нужен ffmpeg.'),
    'Carpeta de referencia (archivos con los nombres correctos)': ('Reference folder (files with the correct names)', 'Папка-образец (файлы с правильными именами)'),
    'Sin archivos': ('No files', 'Нет файлов'),
    'No encontré archivos de audio en esa carpeta (ni en sus subcarpetas).': ('I found no audio files in that folder (nor its subfolders).', 'В этой папке (и подпапках) нет аудиофайлов.'),
    'Analizando referencia {0}/{1}…': ('Analyzing reference {0}/{1}…', 'Анализ образца {0}/{1}…'),
    'Analizando banco {0}/{1}…': ('Analyzing bank {0}/{1}…', 'Анализ банка {0}/{1}…'),
    'Comparando audios…': ('Comparing audio…', 'Сравнение аудио…'),
    'ERROR al importar nombres: {0}': ('ERROR importing names: {0}', 'ОШИБКА импорта имён: {0}'),
    'No se pudieron importar los nombres': ('Could not import the names', 'Не удалось импортировать имена'),
    '  Dudoso #{0} ({1}): parece «{2}» (similitud {3:.2f}).': ('  Doubtful #{0} ({1}): looks like “{2}” (similarity {3:.2f}).', '  Сомнительно #{0} ({1}): похоже на «{2}» (сходство {3:.2f}).'),
    '  Sin pareja: #{0} ({1})': ('  No match: #{0} ({1})', '  Без пары: #{0} ({1})'),
    '{0} entradas emparejadas con seguridad\n{1} dudosas\n{2} sin pareja\n{3} archivos de referencia sin usar': ('{0} entries matched with confidence\n{1} doubtful\n{2} unmatched\n{3} reference files unused', 'Уверенно сопоставлено записей: {0}\nСомнительных: {1}\nБез пары: {2}\nНеиспользованных файлов-образцов: {3}'),
    'Importar nombres': ('Import names', 'Импорт имён'),
    '\n\n¿Aplicar los {0} nombres seguros?': ('\n\nApply the {0} confident names?', '\n\nПрименить {0} уверенных имён?'),
    'Entradas dudosas': ('Doubtful entries', 'Сомнительные записи'),
    'Quedan {0} entradas dudosas: casi siempre el mejor candidato es el correcto, pero si hay frases idénticas con distinto nombre puede confundirse.\n\n¿Aplicar también el mejor candidato de cada una? (quedan anotadas en el registro para revisarlas)': ('{0} entries are doubtful: the best candidate is almost always right, but if there are identical lines with different names it can get confused.\n\nApply the best candidate for each of them too? (they are noted in the log for review)', 'Сомнительных записей: {0}. Лучший кандидат почти всегда верен, но при одинаковых репликах с разными именами возможна путаница.\n\nПрименить и лучшего кандидата для каждой? (они будут отмечены в журнале для проверки)'),
    'Importación de nombres cancelada.': ('Name import cancelled.', 'Импорт имён отменён.'),
    '  Aplicado (dudoso) #{0} -> «{1}» ({2:.2f})': ('  Applied (doubtful) #{0} -> “{1}” ({2:.2f})', '  Применено (сомнительно) #{0} -> «{1}» ({2:.2f})'),
    '{0} nombres importados y guardados en el JSON.': ('{0} names imported and saved to the JSON.', 'Имён импортировано и сохранено в JSON: {0}.'),
    '{0} nombres importados desde {1}': ('{0} names imported from {1}', 'Имён импортировано: {0} (из {1})'),
    'Importando nombres desde {0}': ('Importing names from {0}', 'Импорт имён из {0}'),
    'Audio nuevo para #{0} · {1}': ('New audio for #{0} · {1}', 'Новое аудио для #{0} · {1}'),
    'Audio': ('Audio', 'Аудио'),
    'ERROR al reemplazar #{0}: {1}': ('ERROR replacing #{0}: {1}', 'ОШИБКА замены #{0}: {1}'),
    'No se pudo reemplazar (el banco original no se tocó).': ('Could not replace (the original bank was not touched).', 'Не удалось заменить (исходный банк не тронут).'),
    'No se pudo reemplazar': ('Could not replace', 'Не удалось заменить'),
    '#{0}: {1} ({2} bytes) -> {3} ({4} bytes), diferencia {5:+d} bytes.': ('#{0}: {1} ({2} bytes) -> {3} ({4} bytes), difference {5:+d} bytes.', '#{0}: {1} ({2} байт) -> {3} ({4} байт), разница {5:+d} байт.'),
    '  ATENCIÓN: {0}': ('  WARNING: {0}', '  ВНИМАНИЕ: {0}'),
    'Banco escrito: {0}': ('Bank written: {0}', 'Банк записан: {0}'),
    '  ·  backup: {0}': ('  ·  backup: {0}', '  ·  копия: {0}'),
    '#{0} reemplazado.': ('#{0} replaced.', '#{0} заменена.'),
    ' Backup: {0}': (' Backup: {0}', ' Копия: {0}'),
    'Reemplazando #{0} con {1}': ('Replacing #{0} with {1}', 'Замена #{0} на {1}'),
    'Carpeta con los audios nuevos': ('Folder with the new audio', 'Папка с новым аудио'),
    'Sin coincidencias': ('No matches', 'Нет совпадений'),
    'Ningún archivo de esa carpeta se llama como una entrada del banco (su nombre, el del .xsb o entryNNN).': ("No file in that folder is named like a bank entry (its name, the .xsb's or entryNNN).", 'Ни один файл в папке не назван как запись банка (её имя, имя из .xsb или entryNNN).'),
    '\n{0} archivo(s) sin pareja se ignoran.': ('\n{0} unmatched file(s) are ignored.', '\nФайлов без пары (игнорируются): {0}.'),
    'Reemplazar desde carpeta': ('Replace from folder', 'Замена из папки'),
    '{0} archivo(s) coinciden con entradas del banco.{1}\n\nSe convertirán al códec de cada entrada y se creará el banco nuevo. ¿Continuar?': ("{0} file(s) match bank entries.{1}\n\nThey will be converted to each entry's codec and the new bank will be created. Continue?", 'Файлов, совпавших с записями банка: {0}.{1}\n\nОни будут сконвертированы в кодек каждой записи, и будет создан новый банк. Продолжить?'),
    'ERROR en el reemplazo por carpeta: {0}': ('ERROR in the folder replacement: {0}', 'ОШИБКА при замене из папки: {0}'),
    '  #{0} ATENCIÓN: {1}': ('  #{0} WARNING: {1}', '  #{0} ВНИМАНИЕ: {1}'),
    '{0} entradas reemplazadas.': ('{0} entries replaced.', 'Записей заменено: {0}.'),
    'Reemplazando {0} entradas': ('Replacing {0} entries', 'Замена записей: {0}'),
    'No hay entradas seleccionadas.': ('No entries selected.', 'Записи не выбраны.'),
    'Carpeta de destino': ('Destination folder', 'Папка назначения'),
    'Extrayendo {0}/{1}…': ('Extracting {0}/{1}…', 'Извлечение {0}/{1}…'),
    'ERROR al extraer: {0}': ('ERROR while extracting: {0}', 'ОШИБКА при извлечении: {0}'),
    'No se pudo extraer': ('Could not extract', 'Не удалось извлечь'),
    '  ERROR {0}': ('  ERROR {0}', '  ОШИБКА {0}'),
    '{0} archivos extraídos en {1}': ('{0} files extracted to {1}', 'Извлечено файлов: {0} (в {1})'),
    ' ({0} con error)': (' ({0} with errors)', ' (с ошибками: {0})'),
    'Extrayendo {0} entradas': ('Extracting {0} entries', 'Извлечение записей: {0}'),
    'No se pudo decodificar #{0}: {1}': ('Could not decode #{0}: {1}', 'Не удалось декодировать #{0}: {1}'),
    'ERROR interno: {0}': ('INTERNAL ERROR: {0}', 'ВНУТРЕННЯЯ ОШИБКА: {0}'),
    'ERROR interno: {0}  (detalle en {1})': ('INTERNAL ERROR: {0}  (details in {1})', 'ВНУТРЕННЯЯ ОШИБКА: {0}  (подробности в {1})'),
    'Operación en curso': ('Operation in progress', 'Идёт операция'),
    'Hay una operación en curso. ¿Salir igual?': ('An operation is in progress. Quit anyway?', 'Идёт операция. Всё равно выйти?'),
    'customtkinter {0} es demasiado viejo (hace falta 5.1 o más): python -m pip install --upgrade customtkinter': ('customtkinter {0} is too old (5.1 or newer is required): python -m pip install --upgrade customtkinter', 'customtkinter {0} слишком старый (нужен 5.1 или новее): python -m pip install --upgrade customtkinter'),
    'No se pudo iniciar Audio Studio': ('Could not start Audio Studio', 'Не удалось запустить Audio Studio'),
    '\n\nDetalle en {0}': ('\n\nDetails in {0}', '\n\nПодробности в {0}'),
    'Otro': ('Other', 'Другое'),
    'ninguno': ('none', 'нет'),
    'No se pudo cargar el módulo de Deadly Premonition 2. Instalá: python -m pip install --upgrade UnityPy (y dejá dp2_panel.py junto a este archivo).\n\nDetalle: {0}': ('Could not load the Deadly Premonition 2 module. Install: python -m pip install --upgrade UnityPy (and keep dp2_panel.py next to this file).\n\nDetails: {0}', 'Не удалось загрузить модуль Deadly Premonition 2. Установите: python -m pip install --upgrade UnityPy (и держите dp2_panel.py рядом с этим файлом).\n\nПодробности: {0}'),
    'Los programas de terceros (ffmpeg, ffprobe, ffplay, xma2encode, WMAEncodeRS y, para Deadly Premonition 2, fsbankcl y vgmstream) no vienen incluidos: se descargan desde sus fuentes y quedan en la carpeta assets.': ('Third-party programs (ffmpeg, ffprobe, ffplay, xma2encode, WMAEncodeRS and, for Deadly Premonition 2, fsbankcl and vgmstream) are not bundled: they are downloaded from their sources into the assets folder.', 'Сторонние программы (ffmpeg, ffprobe, ffplay, xma2encode, WMAEncodeRS и, для Deadly Premonition 2, fsbankcl и vgmstream) не входят в комплект: они скачиваются из своих источников в папку assets.'),
    'Fuentes: assets.zip y assets2 (MediaFire), ffmpeg/ffprobe/ffplay (gyan.dev, respaldo BtbN/GitHub) y vgmstream (GitHub).': ('Sources: assets.zip and assets2 (MediaFire), ffmpeg/ffprobe/ffplay (gyan.dev, BtbN/GitHub as fallback) and vgmstream (GitHub).', 'Источники: assets.zip и assets2 (MediaFire), ffmpeg/ffprobe/ffplay (gyan.dev, запасной вариант — BtbN/GitHub) и vgmstream (GitHub).'),
    'Videos': ('Videos', 'Видео'),
    'Un video': ('One video', 'Одно видео'),
    'Carpeta': ('Folder', 'Папка'),
    'Video (.wmv/.asf)': ('Video (.wmv/.asf)', 'Видео (.wmv/.asf)'),
    'Carpeta de videos': ('Video folder', 'Папка с видео'),
    'Tu audio (wav, mp3, ogg, flac…)': ('Your audio (wav, mp3, ogg, flac…)', 'Ваше аудио (wav, mp3, ogg, flac…)'),
    'Carpeta de audios (mismo nombre que cada video)': ('Audio folder (same name as each video)', 'Папка с аудио (то же имя, что у видео)'),
    'Salida (vacío = junto al original)': ('Output (empty = next to the original)', 'Вывод (пусто = рядом с оригиналом)'),
    'Carpeta de salida': ('Output folder', 'Папка вывода'),
    'Video WMV/ASF': ('WMV/ASF video', 'Видео WMV/ASF'),
    'Audio': ('Audio', 'Аудио'),
    'Ajustar la duración al original (silencio / recorte)': ('Fit the length to the original (silence / trim)', 'Подогнать длину под оригинал (тишина / обрезка)'),
    'Guardar el .wma y el wav adaptado': ('Keep the .wma and the adapted wav', 'Сохранить .wma и адаптированный wav'),
    'Ver info del video': ('Video info', 'Сведения о видео'),
    'Reemplazar el audio del video…': ('Replace the video audio…', 'Заменить аудио видео…'),
    'Cambia la pista de audio de un .wmv/.asf por tu audio sin recodificar el video, con el mismo códec que tenía (WMA Pro o estándar). El original no se toca: sale como <nombre>_new.wmv.\n\nEn carpeta, cada video se empareja con el audio del mismo nombre.': ('Swaps the audio track of a .wmv/.asf for your audio without re-encoding the video, using the same codec it had (WMA Pro or standard). The original is not touched: the result is saved as <name>_new.wmv.\n\nIn folder mode each video is paired with the audio of the same name.', 'Заменяет звуковую дорожку .wmv/.asf вашим аудио без перекодирования видео, тем же кодеком (WMA Pro или стандартный). Оригинал не изменяется: результат сохраняется как <имя>_new.wmv.\n\nВ режиме папки каждое видео сопоставляется с аудио с тем же именем.'),
    'Listo: ffmpeg, ffprobe y WMAEncodeRS encontrados.': ('Ready: ffmpeg, ffprobe and WMAEncodeRS found.', 'Готово: ffmpeg, ffprobe и WMAEncodeRS найдены.'),
    'Falta: {0} (ponelo en la carpeta assets o indicalo en Ajustes).': ('Missing: {0} (put it in the assets folder or set it in Settings).', 'Не найдено: {0} (поместите в папку assets или укажите в настройках).'),
    'Falta ffmpeg': ('ffmpeg is missing', 'Нет ffmpeg'),
    'No encuentro ffmpeg y ffprobe: ponelos en la carpeta assets (junto al programa) o indicá ffmpeg en Ajustes.': ('ffmpeg and ffprobe were not found: put them in the assets folder (next to the program) or set ffmpeg in Settings.', 'ffmpeg и ffprobe не найдены: поместите их в папку assets (рядом с программой) или укажите ffmpeg в настройках.'),
    'Falta WMAEncodeRS': ('WMAEncodeRS is missing', 'Нет WMAEncodeRS'),
    'No encuentro WMAEncodeRS.exe (hace falta para WMA Pro / estándar): ponelo en la carpeta assets o indicalo en Ajustes.': ('WMAEncodeRS.exe was not found (needed for WMA Pro / standard): put it in the assets folder or set it in Settings.', 'WMAEncodeRS.exe не найден (нужен для WMA Pro / стандартного): поместите его в папку assets или укажите в настройках.'),
    'El bitrate debe ser un número (o auto).': ('The bitrate must be a number (or auto).', 'Битрейт должен быть числом (или auto).'),
    'Elegí un video (o una carpeta con videos) primero.': ('Pick a video (or a folder with videos) first.', 'Сначала выберите видео (или папку с видео).'),
    'Indicá el video y tu audio primero.': ('Set the video and your audio first.', 'Сначала укажите видео и ваше аудио.'),
    'Sin audio para {0}: se omite.': ('No audio for {0}: skipped.', 'Нет аудио для {0}: пропущено.'),
    'No hay ningún video con un audio del mismo nombre.': ('No video has an audio file with the same name.', 'Нет ни одного видео с аудио с тем же именем.'),
    'Información de video': ('Video info', 'Сведения о видео'),
    'Reemplazando audio en video': ('Replacing video audio', 'Замена аудио в видео'),
    '  cabecera ASF: {0}': ('  ASF header: {0}', '  заголовок ASF: {0}'),
    '  OK -> {0}': ('  OK -> {0}', '  OK -> {0}'),
    'ERROR: {0}': ('ERROR: {0}', 'ОШИБКА: {0}'),
    'Terminado: {0} bien, {1} con error.': ('Done: {0} OK, {1} with errors.', 'Готово: {0} успешно, {1} с ошибками.'),
    'No se encontró WMV_Audio_Replacer.py junto al programa: esta pestaña no está disponible.': ('WMV_Audio_Replacer.py was not found next to the program: this tab is not available.', 'WMV_Audio_Replacer.py не найден рядом с программой: эта вкладка недоступна.'),
    'Dependencias': ('Dependencies', 'Зависимости'),
    '▶ Reproducir': ('▶ Play', '▶ Воспроизвести'),
    'Falta ffplay: se abre con el reproductor del sistema (Ajustes > Dependencias lo descarga).': ('ffplay is missing: opening with the system player (Settings > Dependencies downloads it).', 'Нет ffplay: открываю системным плеером (Настройки > Зависимости скачает его).'),
    'Falta ffplay': ('ffplay is missing', 'Нет ffplay'),
    'Descargalo en Ajustes > Dependencias.': ('Download it in Settings > Dependencies.', 'Скачайте его в Настройки > Зависимости.'),
    'No se pudo reproducir': ('Could not play', 'Не удалось воспроизвести'),
    'Falta dp_dependencies.py junto al programa: el descargador no está disponible.': ('dp_dependencies.py is missing next to the program: the downloader is not available.', 'Рядом с программой нет dp_dependencies.py: загрузчик недоступен.'),
    'Los programas de terceros (ffmpeg, ffprobe, ffplay, xma2encode, WMAEncodeRS) no vienen incluidos: se descargan desde sus fuentes y quedan en la carpeta assets.': ('Third-party programs (ffmpeg, ffprobe, ffplay, xma2encode, WMAEncodeRS) are not bundled: they are downloaded from their sources into the assets folder.', 'Сторонние программы (ffmpeg, ffprobe, ffplay, xma2encode, WMAEncodeRS) не входят в комплект: они скачиваются из своих источников в папку assets.'),
    'Descargar dependencias': ('Download dependencies', 'Скачать зависимости'),
    'Abrir carpeta assets': ('Open assets folder', 'Открыть папку assets'),
    'Descargando dependencias…': ('Downloading dependencies…', 'Загрузка зависимостей…'),
    'Ya están todas las dependencias.': ('All dependencies are already in place.', 'Все зависимости уже на месте.'),
    'Listo: dependencias instaladas en assets.': ('Done: dependencies installed in assets.', 'Готово: зависимости установлены в assets.'),
    'Fuentes: assets.zip (MediaFire) y ffmpeg/ffprobe/ffplay (build oficial de gyan.dev, con respaldo en BtbN/GitHub).': ('Sources: assets.zip (MediaFire) and ffmpeg/ffprobe/ffplay (official gyan.dev build, BtbN/GitHub as fallback).', 'Источники: assets.zip (MediaFire) и ffmpeg/ffprobe/ffplay (официальная сборка gyan.dev, запасной вариант — BtbN/GitHub).'),
}


def _early_lang():
    try:
        code = json.loads((APP_DIR / "dp_studio_settings.json").read_text(encoding="utf-8")).get("lang", "es")
    except Exception:
        code = "es"
    return code if code in LANGS else "es"


LANG = _early_lang()


def tr(key, *args):
    """Traduce `key` al idioma activo y le aplica .format(*args) (si hay argumentos)."""
    if LANG != "es":
        row = I18N.get(key)
        if row:
            key = row[0] if LANG == "en" else row[1]
    return key.format(*args) if args else key


def tr_all(key):
    """Todas las versiones (es, en, ru) de un texto: sirve para reconocer datos guardados en otro idioma."""
    row = I18N.get(key) or ("", "")
    return {key, row[0], row[1]} - {""}


def make_hardened_popen_init(orig):
    """Para el .exe sin consola: los procesos hijos (ffmpeg, encoders) no deben abrir ventanas de consola ni
    heredar entrada/salida estandar invalidas (WinError 6)."""
    def init(self, *a, **k):
        k["creationflags"] = k.get("creationflags", 0) | 0x08000000     # CREATE_NO_WINDOW
        for h in ("stdin", "stdout", "stderr"):
            if k.get(h) is None:
                k[h] = subprocess.DEVNULL
        orig(self, *a, **k)
    return init


if FROZEN and os.name == "nt" and not getattr(subprocess.Popen, "_dp_hardened", False):
    subprocess.Popen.__init__ = make_hardened_popen_init(subprocess.Popen.__init__)
    subprocess.Popen._dp_hardened = True
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
except ImportError as _ex:
    if __name__ == "__main__":
        print("\nFalta una dependencia:", _ex)
        print("Instalala con:   python -m pip install --upgrade customtkinter pillow pygame\n")
        try:
            input("Presioná Enter para cerrar...")
        except EOFError:
            pass
        raise SystemExit(1)
    raise

# ----------------------------------------------------------------------------------------------
#  Paleta y personajes
# ----------------------------------------------------------------------------------------------
BG = "#0a0606"
PANEL = "#150c0c"
PANEL2 = "#1d1010"
EDGE = "#3a1c1c"
RED = "#8b0f0f"
RED_HOT = "#c01818"
CREAM = "#e9e1d1"
MUTED = "#9c8f86"

# Personajes de Greenvale (nombres segun la wiki del juego), agrupados. Se puede editar la lista completa en
# Ajustes > Personajes (una linea por nombre; las lineas que empiezan con # son titulos de grupo).
ROSTER_DEFAULT = [
    (tr('Principales'), ["York", "Zach", "Emily", "George", "Forrest Kaysen"]),
    (tr('Policía y sanidad'), ["Thomas MacLaine", "Ushah Johnson"]),
    (tr('Residentes'), ["Harry Stewart", "Michael Tillotson", "Carol MacLaine", "Diane Ames", "Polly Oxford",
                    "Nick Cormack", "Olivia Cormack", "Keith Ingram", "Lilly Ingram", "Jim Green",
                    "Brian (el insomne)", "Sigourney (la de la olla)", "Wesley (el armero)",
                    "Lysander (El General)", 'Jack "The Raging Bull"']),
    (tr('Víctimas y allegados'), ["Anna Graham", "Becky Ames", "Sallie Graham", "Quint Dunn"]),
    (tr('Gemelos Ingram'), ["Isaach Ingram", "Isaiah Ingram"]),
    (tr('Voces genéricas'), ["Harry (joven)", "Soldados", "Multitud", "Ciudadanos (hace 50 años)",
                         "Asesino del impermeable"]),
]
OTHER_LABEL = "Otro"          # dato guardado en el JSON: no se traduce (se muestra con disp())
CUSTOM_GROUP = "Personales"   # grupo de la lista donde quedan las etiquetas personales


def disp(name):
    """Nombre para mostrar en pantalla (solo «Otro» cambia con el idioma)."""
    return tr("Otro") if name == OTHER_LABEL else name
QUICK = [("York", "y"), ("Zach", "z"), ("Emily", "e"), ("George", "g")]      # botones grandes + atajos
KEYMAP = {k: n for n, k in QUICK}
KEYMAP["o"] = OTHER_LABEL
QUICK_COLORS = {"York": "#d9a441", "Zach": "#a9c7ee", "Emily": "#e08aa6", "George": "#4fa89e", OTHER_LABEL: "#8d8d8d"}

# Personajes que comparten actor de voz (segun los creditos de la version original): ayuda al clasificar de oido.
VOICE_SHARED = [
    ("Carol MacLaine", "Lilly Ingram"), ("Diane Ames", "Polly Oxford"),
    ("Michael Tillotson", "Brian (el insomne)", "Harry (joven)", "Soldados"),
    ("Olivia Cormack", "Sigourney (la de la olla)", "Multitud"), ("Nick Cormack", "Multitud"),
    ("Keith Ingram", "Ciudadanos (hace 50 años)"), ("Quint Dunn", "Soldados"),
    ("Lysander (El General)", 'Jack "The Raging Bull"', "Wesley (el armero)"),
]


def char_color(name):
    if name in QUICK_COLORS:
        return QUICK_COLORS[name]
    h = (zlib.crc32(name.encode("utf-8")) % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.42, 0.95)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def roster_to_text(groups):
    lines = []
    for g, names in groups:
        lines.append(f"# {g}")
        lines += list(names)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def parse_roster(text):
    """Texto -> [(grupo, [nombres])]. Lineas '# Grupo' abren un grupo; sin duplicados; siempre existe «Otro»."""
    groups, cur, seen = [], None, set()
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            cur = (line.lstrip("#").strip() or tr('Otros'), [])
            groups.append(cur)
            continue
        if line.lower() in seen:
            continue
        seen.add(line.lower())
        if cur is None:
            cur = (tr('Otros'), [])
            groups.append(cur)
        cur[1].append(line)
    if OTHER_LABEL.lower() not in seen:
        groups.append((tr('Otros'), [OTHER_LABEL]))
    return [(g, n) for g, n in groups if n]


def shares_voice(name):
    out = []
    for grp in VOICE_SHARED:
        if name in grp:
            out += [n for n in grp if n != name and n not in out]
    return out


AUTO_BANK = tr('Automático')
FILTER_ALL = tr('Todos')
FILTER_NONE = tr('Sin clasificar')

BANNER_H = 110      # alto logico del banner
STACK_W = 980       # por debajo de este ancho, la lista queda arriba y el detalle abajo
JSON_FORMAT = "dp-clasificador-voces"

ASSET_NAMES = {
    "fondo": ("fondo.jpg", "1000303548.jpg"),
    "logo": ("logo.jpg", "02764856-photo-deadly-premonitions.jpg"),
    "duo": ("duo.jpg", "1000303549.jpg"),
    "dp2": ("dp2_banner.jpg", "deadly-premonition-2-a-blessing-in-disguise-review-2.jpg"),
    "dp2logo": ("dp2_logo.png", "4e05b55c-d07b-4e5e-8139-35c32f48598f.png"),
}
GAME_DP1 = "Deadly Premonition"
GAME_DP2 = "Deadly Premonition 2"
YORK_BOX = (190, 60, 930, 800)       # recortes sobre duo.jpg (1920x1080)
EMILY_BOX = (950, 120, 1690, 860)
SPLASH_BOX = (1180, 40, 1920, 560)   # salpicadura de fondo.jpg
CUP_BOX = (0, 800, 480, 1200)        # la taza de fondo.jpg


# ----------------------------------------------------------------------------------------------
#  Imagenes
# ----------------------------------------------------------------------------------------------
def find_asset(key):
    for folder in (APP_DIR / "assets", HERE / "assets", HERE):
        for name in ASSET_NAMES[key]:
            p = folder / name
            if p.is_file():
                return p
    return None


def load_asset(key):
    p = find_asset(key)
    if not p:
        return None
    try:
        return Image.open(p).convert("RGB")
    except Exception:
        return None


def load_asset_rgba(key):
    """Como load_asset, pero conserva la transparencia (logos PNG)."""
    p = find_asset(key)
    if not p:
        return None
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        return None


def _feather_mask(size, margin):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle([margin, margin, size[0] - margin, size[1] - margin], fill=255)
    return m.filter(ImageFilter.GaussianBlur(max(1, margin / 2)))


def make_banner(width, height, fondo, logo):
    """Banner: salpicadura a la derecha + logo a la izquierda (mezcla 'screen': el negro del logo desaparece)."""
    width, height = max(200, int(width)), max(40, int(height))
    base = Image.new("RGB", (width, height), (0, 0, 0))
    if fondo is not None and width >= 560:
        splash = fondo.crop(SPLASH_BOX)
        sw = int(splash.width * height / splash.height)
        splash = splash.resize((sw, height), Image.LANCZOS)
        base.paste(splash, (width - sw, 0), _feather_mask((sw, height), max(6, height // 8)))
    if logo is not None:
        lh = int(height * 0.86)
        lw = int(logo.width * lh / logo.height)
        if lw > width - 24:
            lw = width - 24
            lh = int(logo.height * lw / logo.width)
        lg = logo.resize((lw, lh), Image.LANCZOS)
        lg = Image.composite(lg, Image.new("RGB", lg.size, (0, 0, 0)), _feather_mask((lw, lh), max(6, lh // 10)))
        layer = Image.new("RGB", (width, height), (0, 0, 0))
        layer.paste(lg, (12, (height - lh) // 2))
        base = ImageChops.screen(base, layer)
    return base


def make_banner_dp2(width, height, art, logo=None):
    """Banner de Deadly Premonition 2: arte a la derecha (recorte a la altura del rostro de York) + logo oficial."""
    width, height = max(200, int(width)), max(40, int(height))
    base = Image.new("RGB", (width, height), (0, 0, 0))
    if art is not None and width >= 560:
        pw = int(width * 0.60)
        aw, ah = art.size
        crop_h = min(ah, int(aw * height / pw))
        crop_w = int(crop_h * pw / height)
        cx, cy = int(aw * 0.56), int(ah * 0.27)
        x0 = max(0, min(aw - crop_w, cx - crop_w // 2))
        y0 = max(0, min(ah - crop_h, cy - crop_h // 2))
        piece = art.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize((pw, height), Image.LANCZOS)
        base.paste(piece, (width - pw, 0), _feather_mask((pw, height), max(6, height // 6)))
    if logo is not None:
        lh = int(height * 0.9)
        lw = int(logo.width * lh / logo.height)
        if lw > width - 24:
            lw = width - 24
            lh = int(logo.height * lw / logo.width)
        lg = logo.resize((lw, lh), Image.LANCZOS)
        base.paste(lg.convert("RGB"), (12, (height - lh) // 2), lg.getchannel("A"))
    else:                                    # sin logo: titulo en texto
        d = ImageDraw.Draw(base)
        d.text((18, height // 3), "DEADLY PREMONITION 2", font=_font(max(14, int(height * 0.28))), fill=(233, 225, 209))
    return base


def _font(px):
    for name in ("georgiab.ttf", "arialbd.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def monogram(letter, color, size=96):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 3, size - 3], fill=(26, 14, 14, 255), outline=color, width=4)
    f = _font(int(size * 0.55))
    box = d.textbbox((0, 0), letter, font=f)
    d.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
           letter, font=f, fill=color)
    return img


def character_portraits(duo, size=96):
    """PIL de cada personaje: York/Emily recortados del arte, George/Otro con monograma."""
    out = {}
    if duo is not None:
        out["York"] = duo.crop(YORK_BOX).resize((size, size), Image.LANCZOS)
        out["Emily"] = duo.crop(EMILY_BOX).resize((size, size), Image.LANCZOS)
    for name, _k in QUICK:
        if name not in out:
            out[name] = monogram(name[0].upper(), char_color(name), size)
    return out


# ----------------------------------------------------------------------------------------------
#  Datos: banco, nombres de cue y etiquetas
# ----------------------------------------------------------------------------------------------
def load_core():
    """Modulo con el lector de bancos (tu script de extraccion, en la misma carpeta)."""
    try:
        import Deadly_Premonition_XBOX_Audio_extractor as core
        return core
    except ModuleNotFoundError as ex:
        if ex.name != "Deadly_Premonition_XBOX_Audio_extractor":
            raise
    return None


def load_wmv():
    """Modulo de reemplazo de audio en videos (WMV_Audio_Replacer.py, en la misma carpeta)."""
    try:
        import WMV_Audio_Replacer as wmv
        return wmv
    except ModuleNotFoundError as ex:
        if ex.name != "WMV_Audio_Replacer":
            raise
    return None


def resolve_bank(banks, wb, xwb_path, chosen=None):
    """Que banco del .xsb corresponde a este .xwb: el elegido a mano > el nombre interno del .xwb >
    el nombre del archivo > el unico banco del .xsb. None si no se puede decidir."""
    low = {b.lower(): b for b in banks}
    if chosen and chosen in banks:
        return chosen
    for cand in (getattr(wb, "bank_name", ""), Path(xwb_path).stem):
        if cand and cand.lower() in low:
            return low[cand.lower()]
    return banks[0] if len(banks) == 1 else None


def names_by_track(core, xwb_path, wb, xsb_path, chosen=None):
    """({track: 'CUE1 / CUE2'}, info). Los nombres salen del banco del .xsb elegido (o detectado) para este
    .xwb. Si el .xsb tiene varios bancos y ninguno coincide, NO se mezclan nombres: se devuelve {} y info
    lo avisa para que se elija uno a mano."""
    info = dict(banks=[], bank=None, cues=0, entries=len(wb.entries), max_track=-1, ok=False,
                text=tr('Sin .xsb: se usan nombres entryNNN. Usá «Elegir XSB…» y después el banco que corresponda.'))
    if not xsb_path:
        return {}, info
    banks = core.xsb_bank_names(str(xsb_path))
    info["banks"] = banks
    bank = resolve_bank(banks, wb, xwb_path, chosen) if banks else None
    info["bank"] = bank
    if banks and bank is None:
        info["text"] = (tr('El .xsb referencia {0} bancos ({1}) y ninguno coincide con este .xwb: elegí cuál usar en «Banco del XSB».', len(banks), ', '.join(banks)))
        return {}, info
    try:
        mapping, _nc = core.parse_xsb(str(xsb_path), bank or wb.bank_name or Path(xwb_path).stem)
    except Exception as ex:
        info["text"] = tr('No se pudo leer el .xsb: {0}', ex)
        return {}, info
    inv = {}
    for name, track in mapping.items():
        inv.setdefault(track, []).append(name)
    names = {t: " / ".join(v) for t, v in inv.items()}
    tracks = sorted(mapping.values())
    info.update(cues=len(mapping), max_track=tracks[-1] if tracks else -1)
    n = len(wb.entries)
    if tracks and tracks[-1] >= n:
        info["text"] = (tr("Banco '{0}': {1} cues, pero el track más alto es {2} y el .xwb tiene {3} entradas. ¿Es el banco correcto?", bank or '—', len(mapping), tracks[-1], n))
    elif len(set(tracks)) != n:
        info["text"] = (tr("Banco '{0}': {1} entradas con nombre de {2} (las demás quedan como entryNNN).", bank or '—', len(set(tracks)), n))
        info["ok"] = True
    else:
        info["text"] = tr("Banco '{0}': {1} de {2} entradas con nombre.", bank or '—', n, n)
        info["ok"] = True
    return names, info


def build_entries(core, wb, names):
    out = []
    for i, e in enumerate(wb.entries):
        rate = e.get("sample_rate") or 0
        out.append(dict(
            idx=i,
            cue=names.get(i, f"entry{i:03d}"),
            fmt=core.codec_label(e),
            ch=e.get("channels", 0),
            rate=rate,
            secs=(e.get("duration", 0) / rate) if rate else 0.0,
        ))
    return out


class Session:
    """Banco abierto + etiquetas {indice: personaje}."""

    def __init__(self):
        self.bank_path = None
        self.wb = None
        self.bank_name = ""
        self.xsb_path = None
        self.entries = []
        self.labels = {}
        self.json_path = None
        self.dirty = False
        self.names = {}             # nombres puestos a mano {indice: nombre}
        self.roster = []            # lista de personajes (solo para guardarla en el JSON)
        self.xsb_bank = None        # banco del .xsb elegido a mano (None = automatico)
        self.xsb_bank_used = None   # banco realmente usado para los nombres
        self.pending_bank = None    # banco guardado en un JSON cargado

    def default_json_path(self):
        if not self.bank_path:
            return None
        p = Path(self.bank_path)
        return p.with_name(p.stem + ".json")        # scnd.xwb -> scnd.json, bgm.xwb -> bgm.json, ...

    def legacy_json_path(self):
        """Nombre antiguo (<banco>.personajes.json): solo se usa para leer trabajos ya guardados."""
        if not self.bank_path:
            return None
        p = Path(self.bank_path)
        return p.with_name(p.stem + ".personajes.json")

    def to_json(self):
        entradas, por = {}, {}
        for e in self.entries:
            who = self.labels.get(e["idx"])
            if who:
                entradas[str(e["idx"])] = {"cue": e["cue"], "personaje": who}
                por.setdefault(who, []).append({"indice": e["idx"], "cue": e["cue"]})
        return {
            "formato": JSON_FORMAT,
            "version": 2,
            "banco": Path(self.bank_path).name if self.bank_path else "",
            "nombre_banco": self.bank_name,
            "xsb": Path(self.xsb_path).name if self.xsb_path else "",
            "banco_en_xsb": self.xsb_bank_used or "",
            "personajes": list(self.roster),
            "total_entradas": len(self.entries),
            "clasificadas": len(entradas),
            "entradas": entradas,
            "nombres": {str(i): n for i, n in sorted(self.names.items())},
            "por_personaje": por,
        }

    def save(self, path=None):
        path = Path(path or self.json_path or self.default_json_path())
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        self.json_path = path
        self.dirty = False
        return path

    def load(self, path):
        """Carga etiquetas de un JSON. Devuelve (cargadas, descartadas, cue_distintos)."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "entradas" not in data:
            raise ValueError(tr('el archivo no parece un JSON de este clasificador'))
        by_idx = {e["idx"]: e for e in self.entries}
        labels, dropped, cue_diff = {}, 0, 0
        for k, v in data["entradas"].items():
            try:
                idx = int(k)
            except ValueError:
                dropped += 1
                continue
            who = v.get("personaje") if isinstance(v, dict) else None
            if idx not in by_idx or not isinstance(who, str) or not who.strip():
                dropped += 1
                continue
            if v.get("cue") and v["cue"] != by_idx[idx]["cue"]:
                cue_diff += 1
            labels[idx] = who.strip()
        names = {}
        for k, v in (data.get("nombres") or {}).items():
            try:
                if int(k) in by_idx and isinstance(v, str) and v.strip():
                    names[int(k)] = v.strip()
            except ValueError:
                pass
        self.names = names
        self.labels = labels
        self.pending_bank = data.get("banco_en_xsb") or None
        self.json_path = Path(path)
        self.dirty = False
        return len(labels), dropped, cue_diff


# ----------------------------------------------------------------------------------------------
#  Audio: decodificacion con ffmpeg y reproductor
# ----------------------------------------------------------------------------------------------
def decode_to_pcm(ffmpeg, data, suffix, rate=48000, channels=2):
    """Decodifica cualquier contenedor que ffmpeg entienda a PCM s16le (estereo para escuchar)."""
    tmpdir = tempfile.mkdtemp(prefix="dpclf_")
    try:
        src = Path(tmpdir) / ("in" + suffix)
        src.write_bytes(data)
        cmd = [ffmpeg, "-v", "error", "-i", str(src), "-f", "s16le", "-acodec", "pcm_s16le",
               "-ac", str(channels), "-ar", str(rate), "pipe:1"]
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}   # sin ventana de consola
        r = subprocess.run(cmd, capture_output=True, **kw)
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or tr('ffmpeg no produjo audio'))
        return r.stdout
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class AudioEngine:
    """Reproduce PCM en memoria. Con pygame hay pausa y barra de busqueda; sin pygame, en Windows,
    cae a winsound (solo reproducir/detener)."""

    def __init__(self):
        self.backend = None
        self.rate, self.channels = 48000, 2
        self._pg = self._ws = None
        try:
            import pygame
            pygame.mixer.init(frequency=self.rate, size=-16, channels=self.channels, buffer=2048)
            init = pygame.mixer.get_init()
            if init:
                self.rate, _fmt, self.channels = init
            self._pg = pygame
            self.backend = "pygame"
        except Exception:
            if os.name == "nt":
                try:
                    import winsound
                    self._ws = winsound
                    self.backend = "winsound"
                except Exception:
                    pass
        self.pcm = b""
        self.duration = 0.0
        self.state = "stopped"      # stopped | playing | paused
        self._pos = 0.0
        self._t0 = 0.0
        self._chan = None
        self._tmp_wav = None

    @property
    def can_seek(self):
        return self.backend == "pygame"

    def load(self, pcm):
        self.stop()
        self.pcm = pcm
        self.duration = len(pcm) / float(self.rate * self.channels * 2)
        self._pos = 0.0

    def play(self, start=None):
        if not self.pcm or not self.backend:
            return
        if start is None:
            start = self._pos if self.state == "paused" else 0.0
        start = max(0.0, min(float(start), max(0.0, self.duration - 0.05)))
        self._halt()
        if self.backend == "pygame":
            off = int(start * self.rate) * self.channels * 2
            snd = self._pg.mixer.Sound(buffer=self.pcm[off:])
            self._chan = snd.play()
        else:
            start = 0.0
            self._ws.PlaySound(self._wav_path(), self._ws.SND_FILENAME | self._ws.SND_ASYNC)
        self._t0 = time.monotonic() - start
        self.state = "playing"

    def pause(self):
        if self.state != "playing":
            return
        if not self.can_seek:
            self.stop()
            return
        self._pos = self.position()
        self._halt()
        self.state = "paused"

    def stop(self):
        self._halt()
        self._pos = 0.0
        self.state = "stopped"

    def position(self):
        if self.state == "playing":
            p = time.monotonic() - self._t0
            busy = True
            if self._chan is not None:
                try:
                    busy = self._chan.get_busy()
                except Exception:
                    busy = True
            if p >= self.duration or (not busy and p > 0.25):
                self.state = "stopped"
                self._pos = 0.0
                return self.duration
            return p
        return self._pos

    def _halt(self):
        if self._chan is not None:
            try:
                self._chan.stop()
            except Exception:
                pass
            self._chan = None
        if self.backend == "winsound":
            try:
                self._ws.PlaySound(None, self._ws.SND_PURGE)
            except Exception:
                pass

    def _wav_path(self):
        import wave
        if self._tmp_wav is None:
            fd, self._tmp_wav = tempfile.mkstemp(prefix="dpclf_", suffix=".wav")
            os.close(fd)
        with wave.open(self._tmp_wav, "wb") as w:
            w.setnchannels(self.channels)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(self.pcm)
        return self._tmp_wav

    def close(self):
        self.stop()
        if self._tmp_wav:
            try:
                os.remove(self._tmp_wav)
            except OSError:
                pass


def fmt_time(sec):
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


# ----------------------------------------------------------------------------------------------
#  Ajustes persistentes y utilidades del Studio
# ----------------------------------------------------------------------------------------------
SETTINGS_PATH = APP_DIR / "dp_studio_settings.json"
DEFAULT_SETTINGS = {
    "ffmpeg": "", "xma2encode": "", "wmaencode": "",
    "xma_mode": "auto", "xma_quality": 75, "xma_block": 64,
    "wma_bitrate": "auto", "policy": "same", "backup": True,
    "extract_format": "raw", "split_by_char": False, "personajes": "", "lang": "es",
    "wmv_bitrate": "auto", "wmv_fit": True, "wmv_keep": True,
}
POLICY_LABELS = {"same": tr('Convertir al mismo códec del original (recomendado)'), "keep": tr('Inyectar tal cual')}
EXTRACT_FORMATS = {"raw": tr('Sin decodificar (original)'), "wav": "WAV (PCM)", "ogg": "OGG", "mp3": "MP3"}
AUDIO_EXTS = (".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".xwma", ".wma")


def load_settings():
    d = dict(DEFAULT_SETTINGS)
    try:
        d.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return d


def save_settings(d):
    try:
        SETTINGS_PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def apply_settings(core, st):
    """Vuelca los ajustes en el motor (rutas de encoders, politica de codec, calidad...)."""
    core.ensure_ffmpeg_on_path()
    ff = (st.get("ffmpeg") or "").strip()
    if ff:
        p = Path(ff)
        folder = p.parent if p.is_file() else p
        if folder.is_dir() and str(folder) not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
    core.XMA_SETTINGS.update(mode=st.get("xma_mode", "auto"), exe=(st.get("xma2encode") or None),
                             quality=_int(st.get("xma_quality"), 75), block_kb=_int(st.get("xma_block"), 64))
    br = st.get("wma_bitrate", "auto")
    core.CODEC_SETTINGS.update(policy=st.get("policy", "same"), wma_exe=(st.get("wmaencode") or None),
                               wma_bitrate=None if br in ("auto", "", None) else _int(br, None))


def tool_status(core, st):
    """Que herramientas externas hay disponibles (ruta o None)."""
    def pick(custom, finder):
        if custom:
            return str(custom) if Path(custom).is_file() else None
        found = finder()
        return str(found) if found else None
    return dict(ffmpeg=shutil.which("ffmpeg"),
                xma=pick((st.get("xma2encode") or "").strip(), core.find_xma2_encoder),
                wma=pick((st.get("wmaencode") or "").strip(), core.find_wma_encoder))


def replace_hint(core, st, entry, tools):
    """(texto, ok) que explica que va a pasar al reemplazar esta entrada."""
    label = core.codec_label(entry)
    if st.get("policy") == "keep":
        return tr('Códec original: {0}. Se inyectará el archivo tal cual (política «tal cual»).', label), True
    if not tools["ffmpeg"]:
        return tr('Códec original: {0}. Falta ffmpeg: sin él no se puede convertir.', label), False
    t = entry["format_tag"]
    if t == core.FMT_XMA:
        if tools["xma"]:
            return tr('Códec original: {0}. Tu audio se convertirá a XMA2 con xma2encode.', label), True
        return tr('Códec original: {0}. Sin xma2encode se inyectará como PCM 16-bit (el banco crece).', label), False
    if t == core.FMT_WMA:
        if tools["wma"]:
            return (tr('Códec original: {0}. Se convertirá con WMAEncodeRS a {1} ({2} kbps, {3} canal(es)).', label, label, core.nearest_wma_bitrate(entry), entry['channels']), True)
        return tr('Códec original: {0}. Falta WMAEncodeRS.exe: no se podrá reemplazar esta entrada.', label), False
    if t == core.FMT_ADPCM:
        return tr('Códec original: {0}. Se convertirá a MS-ADPCM con ffmpeg.', label), True
    return tr('Códec original: {0}. Se convertirá a PCM 16-bit.', label), True


def safe_filename(name):
    out = "".join("_" if (c in '<>:"/\\|?*' or ord(c) < 32) else c for c in str(name)).strip(" .")
    return out or "sin_nombre"


def match_folder_files(folder, entries, names):
    """Empareja archivos de audio de una carpeta con entradas del banco por nombre de archivo
    (nombre editado, nombre de cue o entryNNN). Devuelve ({indice: ruta}, [archivos sin pareja])."""
    by_key = {}
    for e in entries:
        i = e["idx"]
        for key in (names.get(i), e["cue"], f"entry{i:03d}"):
            if key:
                by_key.setdefault(key.lower(), i)
    prio = {x: n for n, x in enumerate(AUDIO_EXTS)}
    repl, unmatched = {}, []
    files = [f for f in Path(folder).iterdir() if f.is_file() and f.suffix.lower() in prio]
    for f in sorted(files, key=lambda f: (prio[f.suffix.lower()], f.name.lower())):
        i = by_key.get(f.stem.lower())
        if i is None:
            unmatched.append(f.name)
        else:
            repl.setdefault(i, f)
    return repl, unmatched


# ----------------------------------------------------------------------------------------------
#  Importar nombres desde una carpeta de referencia (emparejando por el contenido del audio)
# ----------------------------------------------------------------------------------------------
def envelope(pcm, rate=8000, win=0.02):
    """Huella de una grabacion: por cada ventana de 20 ms, el volumen (log del RMS) y la 'brillantez' (log del
    RMS de la señal derivada: separa vocales de consonantes). Sirve para reconocer la misma grabacion aunque
    este en otro codec (XMA2 / WMA / ADPCM...). Devuelve (volumen, brillantez)."""
    a = array.array("h")
    a.frombytes(pcm[:len(pcm) & ~1])
    if sys.byteorder == "big":
        a.byteswap()
    n = max(2, int(rate * win))
    lo, hi = [], []
    for i in range(0, len(a) - n + 1, n):
        seg = a[i:i + n]
        lo.append(math.log1p(math.sqrt(sum(x * x for x in seg) / n)))
        hi.append(math.log1p(math.sqrt(sum((seg[k] - seg[k - 1]) ** 2 for k in range(1, n)) / (n - 1))))
    return lo, hi


def _corr(x, y):
    n = min(len(x), len(y))
    if n < 4:
        return -1.0
    x, y = x[:n], y[:n]
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    syy = sum((v - my) ** 2 for v in y)
    den = math.sqrt(sxx * syy)
    if den < 1e-9:
        return 1.0 if (sxx < 1e-9 and syy < 1e-9) else -1.0
    return sum((p - mx) * (q - my) for p, q in zip(x, y)) / den


def _aligned(x, y, lag):
    return (x[lag:], y) if lag > 0 else ((x, y[-lag:]) if lag < 0 else (x, y))


def env_similarity(a, b, max_lag=5):
    """Correlacion (-1..1) entre dos huellas, tolerando un pequeno desfase (relleno/retardo del codec)."""
    best = -1.0
    for lag in range(-max_lag, max_lag + 1):
        cl = _corr(*_aligned(a[0], b[0], lag))
        ch = _corr(*_aligned(a[1], b[1], lag))
        best = max(best, (cl + ch) / 2)
    return best


def match_by_content(ents, refs, min_score=0.85, margin=0.02):
    """ents / refs: {clave: (segundos, envolvente)}. Empareja uno a uno cada entrada con el archivo de
    referencia que suena igual. Devuelve dict(matches={ent: (ref, score)}, doubtful={ent: (ref, score)},
    unmatched=[ent], unused=[ref]).  'doubtful' = parecido pero no concluyente (score bajo o dos archivos casi
    igual de buenos, p.ej. la misma frase repetida con dos nombres): no se aplica solo."""
    cands, second = [], {}
    for ek, (ed, ee) in ents.items():
        scored = []
        for rk, (rd, re_) in refs.items():
            if abs(ed - rd) > max(0.35, 0.12 * max(ed, rd)):
                continue
            scored.append((env_similarity(ee, re_), rk))
        scored.sort(reverse=True)
        second[ek] = scored[1][0] if len(scored) > 1 else -1.0
        cands += [(sc, ek, rk) for sc, rk in scored[:5]]
    cands.sort(reverse=True)
    matches, doubtful, used_e, used_r = {}, {}, set(), set()
    for sc, ek, rk in cands:
        if ek in used_e or rk in used_r:
            continue
        used_e.add(ek)
        used_r.add(rk)
        if sc >= min_score and sc - second[ek] >= margin:
            matches[ek] = (rk, sc)
        elif sc >= 0.70:
            doubtful[ek] = (rk, sc)
    unmatched = [ek for ek in ents if ek not in matches and ek not in doubtful]
    unused = [rk for rk in refs if rk not in {v[0] for v in matches.values()}]
    return dict(matches=matches, doubtful=doubtful, unmatched=unmatched, unused=unused)


# ----------------------------------------------------------------------------------------------
#  Aplicacion
# ----------------------------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.wmv = load_wmv()
        ctk.set_appearance_mode("dark")
        self.title("Deadly Premonition · Audio Studio")
        self.configure(fg_color=BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1240, int(sw * 0.94)), min(860, int(sh * 0.92))
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 4)}")
        self.minsize(680, 520)

        self._uiq = queue.Queue()
        self.settings = load_settings()
        if core is not None:
            apply_settings(core, self.settings)
            core.CODEC_LOG = lambda m: self._uiq.put(("log", m))

        if core is not None:
            core.ensure_ffmpeg_on_path()      # ffmpeg empaquetado o junto al exe
        self.session = Session()
        self.roster = parse_roster(self.settings.get("personajes") or roster_to_text(ROSTER_DEFAULT))
        self.session.roster = self._roster_names()
        self._tag_of = {}
        self._char_btns = {}
        self.engine = AudioEngine()
        self.ffmpeg = shutil.which("ffmpeg")
        self.fondo, self.logo, self.duo = load_asset("fondo"), load_asset("logo"), load_asset("duo")
        self.portraits = character_portraits(self.duo)
        self.art_dp2 = load_asset("dp2")
        self.logo_dp2 = load_asset_rgba("dp2logo")
        self.game = "dp1"            # juego activo: "dp1" (bancos XACT) o "dp2" (Unity/FSB5)
        self.dp2_panel = None        # se crea la primera vez que se elige Deadly Premonition 2

        self.cur = None
        self.visible = []
        self.cache = {}
        self.cache_bytes = 0
        self._token = 0
        self._busy = False
        self._suppress_select = False
        self._stacked = None
        self._banner_w = 0
        self._resize_job = None
        self._seek_job = None
        self._alive = True
        self._settings_win = None

        self.auto_adv = tk.BooleanVar(value=True)
        self.auto_play = tk.BooleanVar(value=True)
        self.autosave = tk.BooleanVar(value=True)
        self.show_log = tk.BooleanVar(value=True)
        self.split_var = tk.BooleanVar(value=bool(self.settings.get("split_by_char")))
        self.filter_var = tk.StringVar(value=FILTER_ALL)
        self.fmt_var = tk.StringVar(value=EXTRACT_FORMATS.get(self.settings.get("extract_format"), EXTRACT_FORMATS["raw"]))

        self._build_ui()
        self.bind("<Key>", self._on_key)
        self.bind("<Control-s>", lambda e: self._save_json() if self.game == "dp1" else None)
        self.bind("<Configure>", self._on_configure, add="+")   # add="+": no pisar el binding interno de CustomTkinter
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._apply_layout)
        self.after(100, self._poll)
        self.after(400, self._set_icon)
        self._status(self._startup_hint())
        self._log(tr('Listo. Abrí un banco (.xwb) para empezar.'))

    # ---------------------------------------------------------------- construccion de la UI
    def _font(self, size, weight="normal"):
        return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)

    def _title_font(self, size):
        return ctk.CTkFont(family="Georgia", size=size, weight="bold")

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.banner = ctk.CTkLabel(self, text="", fg_color=BG, height=BANNER_H)
        self.banner.grid(row=0, column=0, sticky="ew")

        self.bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        self.bar.grid(row=1, column=0, sticky="ew")
        self.bar.grid_columnconfigure(10, weight=1)
        self._tool_button(tr('Abrir banco…'), self._open_bank, 0)
        self._tool_button(tr('Elegir XSB…'), self._pick_xsb, 1)
        self._tool_button(tr('Cargar JSON'), self._load_json, 2)
        self._tool_button(tr('Guardar JSON'), self._save_json, 3, primary=True)
        self._tool_button(tr('Ajustes'), self._open_settings, 4)
        self.bank_lbl = ctk.CTkLabel(self.bar, text=tr('Ningún banco abierto'), text_color=MUTED, anchor="w",
                                     font=self._font(12))
        self.bank_lbl.grid(row=0, column=5, padx=(10, 6), sticky="w")
        self.link_row = ctk.CTkFrame(self.bar, fg_color="transparent")
        self.link_row.grid(row=1, column=0, columnspan=11, sticky="ew", padx=10, pady=(0, 6))
        self.link_row.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(self.link_row, text=tr('Banco del XSB:'), text_color=CREAM, font=self._font(12, "bold")).grid(
            row=0, column=0, padx=(0, 6))
        self.bank_menu = ctk.CTkOptionMenu(
            self.link_row, values=[AUTO_BANK], command=self._on_bank_choice, width=150, fg_color=PANEL2,
            button_color=RED, button_hover_color=RED_HOT, dropdown_fg_color=PANEL2, text_color=CREAM,
            font=self._font(12))
        self.bank_menu.grid(row=0, column=1)
        self.link_lbl = ctk.CTkLabel(self.link_row, text="", text_color=MUTED, anchor="w", justify="left",
                                     font=self._font(11), wraplength=600)
        self.link_lbl.grid(row=0, column=2, padx=10, sticky="ew")
        ctk.CTkSwitch(self.link_row, text=tr('Registro'), variable=self.show_log, command=self._toggle_log,
                      progress_color=RED_HOT, button_color=CREAM, button_hover_color="#ffffff", fg_color=EDGE,
                      text_color=CREAM, font=self._font(12)).grid(row=0, column=3)
        self.prog_box = ctk.CTkFrame(self.bar, fg_color="transparent")
        self.prog_box.grid(row=0, column=10, padx=10, pady=6, sticky="e")
        self.prog_lbl = ctk.CTkLabel(self.prog_box, text="0 / 0", text_color=CREAM, font=self._font(12, "bold"))
        self.prog_lbl.pack(side="left", padx=(0, 8))
        self.prog_bar = ctk.CTkProgressBar(self.prog_box, width=150, progress_color=RED_HOT, fg_color=EDGE)
        self.prog_bar.set(0)
        self.prog_bar.pack(side="left")

        self.body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.body.grid(row=2, column=0, sticky="nsew")
        self._build_list_panel()
        self._build_detail_panel()

        self.logbox = ctk.CTkTextbox(self, height=92, fg_color=PANEL2, text_color=CREAM, border_width=1,
                                     border_color=EDGE, font=ctk.CTkFont(family="Consolas", size=11))
        self.logbox.configure(state="disabled")
        self.logbox.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 4))

        self.status = ctk.CTkLabel(self, text="", anchor="w", text_color=MUTED, font=self._font(11))
        self.status.grid(row=4, column=0, sticky="ew", padx=12, pady=(2, 6))

        # Selector de juego, flotando sobre el banner (se ve en los dos modos)
        self.game_switch = ctk.CTkSegmentedButton(
            self, values=[GAME_DP1, GAME_DP2], command=self._on_game, font=self._font(12, "bold"), height=30,
            fg_color=PANEL, selected_color=RED, selected_hover_color=RED_HOT, unselected_color=PANEL2,
            unselected_hover_color="#2d1717", text_color=CREAM)
        self.game_switch.set(GAME_DP1)
        self.game_switch.place(relx=1.0, x=-14, y=12, anchor="ne")

    def _tool_button(self, text, cmd, col, primary=False):
        b = ctk.CTkButton(self.bar, text=text, command=cmd, width=108, height=30, font=self._font(12, "bold"),
                          fg_color=RED if primary else PANEL2, hover_color=RED_HOT if primary else "#2d1717",
                          border_width=1, border_color=EDGE, text_color=CREAM, corner_radius=6)
        b.grid(row=0, column=col, padx=(10 if col == 0 else 4, 0), pady=8)
        return b

    def _build_list_panel(self):
        self.list_panel = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=10, border_width=1, border_color=EDGE)
        lp = self.list_panel
        lp.grid_rowconfigure(1, weight=1)
        lp.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(lp, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        top.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(top, placeholder_text=tr('Buscar por nombre o número…'), fg_color=PANEL2,
                                   border_color=EDGE, text_color=CREAM, font=self._font(12))
        self.search.grid(row=0, column=0, sticky="ew")
        self.search.bind("<KeyRelease>", lambda e: self._refresh_list(keep_idx=self.cur))
        self.filter_menu = ctk.CTkOptionMenu(
            top, values=[FILTER_ALL, FILTER_NONE], variable=self.filter_var,
            command=lambda v: self._refresh_list(keep_idx=self.cur), width=140, fg_color=PANEL2,
            button_color=RED, button_hover_color=RED_HOT, dropdown_fg_color=PANEL2, text_color=CREAM,
            font=self._font(12))
        self.filter_menu.grid(row=0, column=1, padx=(6, 0))

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("DP.Treeview", background=PANEL2, fieldbackground=PANEL2, foreground=CREAM,
                        rowheight=26, borderwidth=0, font=("Segoe UI", 10))
        style.configure("DP.Treeview.Heading", background="#2a0e0e", foreground=CREAM, relief="flat",
                        font=("Segoe UI", 10, "bold"))
        style.map("DP.Treeview", background=[("selected", "#7a1111")], foreground=[("selected", "#ffffff")])
        style.map("DP.Treeview.Heading", background=[("active", "#3a1212")])

        cols = ("idx", "cue", "fmt", "dur", "who")
        self.tree = ttk.Treeview(lp, columns=cols, show="headings", selectmode="extended", style="DP.Treeview")
        for c, title, width, stretch in (("idx", "#", 52, False), ("cue", tr('Nombre'), 190, True),
                                         ("fmt", tr('Códec'), 92, False), ("dur", "Dur.", 64, False),
                                         ("who", tr('Personaje'), 84, False)):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=width, minwidth=40, stretch=stretch, anchor="w")
        self._configure_tags()
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
        sb = ctk.CTkScrollbar(lp, command=self.tree.yview, fg_color=PANEL, button_color=EDGE,
                              button_hover_color=RED)
        sb.grid(row=1, column=1, sticky="ns", padx=(2, 6), pady=(0, 8))
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_detail_panel(self):
        self.detail = ctk.CTkScrollableFrame(self.body, fg_color=PANEL, corner_radius=10, border_width=1,
                                             border_color=EDGE, scrollbar_button_color=EDGE,
                                             scrollbar_button_hover_color=RED)
        d = self.detail
        d.grid_columnconfigure(0, weight=1)

        self.now_title = ctk.CTkLabel(d, text=tr('Elegí una entrada'), font=self._title_font(22), text_color=CREAM,
                                      anchor="w", justify="left", wraplength=360)
        self.now_title.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        self.now_meta = ctk.CTkLabel(d, text="", text_color=MUTED, anchor="w", font=self._font(12))
        self.now_meta.grid(row=1, column=0, sticky="ew", padx=12)
        self.now_who = ctk.CTkLabel(d, text="", anchor="w", font=self._font(13, "bold"))
        self.now_who.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 8))

        # Reproductor
        card = ctk.CTkFrame(d, fg_color=PANEL2, corner_radius=10, border_width=1, border_color=EDGE)
        card.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        card.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.btn_prev = self._player_button(card, "◀◀", self._prev, 0)
        self.btn_play = self._player_button(card, tr('▶ Reproducir'), self._toggle_play, 1, primary=True)
        self.btn_stop = self._player_button(card, "■", self._stop, 2)
        self.btn_next = self._player_button(card, "▶▶", self._next, 3)
        self.slider = ctk.CTkSlider(card, from_=0, to=1, command=self._on_slider, progress_color=RED_HOT,
                                    button_color=CREAM, button_hover_color="#ffffff", fg_color=EDGE)
        self.slider.set(0)
        self.slider.grid(row=1, column=0, columnspan=4, sticky="ew", padx=12, pady=(4, 0))
        self.time_lbl = ctk.CTkLabel(card, text="00:00 / 00:00", text_color=MUTED, font=self._font(12))
        self.time_lbl.grid(row=2, column=0, columnspan=4, pady=(0, 8))

        # Pestanas de trabajo
        self.tabs = ctk.CTkTabview(d, height=540, fg_color=PANEL2, border_width=1, border_color=EDGE,
                                   segmented_button_fg_color=PANEL, segmented_button_selected_color=RED,
                                   segmented_button_selected_hover_color=RED_HOT,
                                   segmented_button_unselected_color=PANEL2,
                                   segmented_button_unselected_hover_color="#2d1717", text_color=CREAM)
        self.tabs.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))
        t_cls, t_rep, t_ext = self.tabs.add(tr('Clasificar')), self.tabs.add(tr('Reemplazar')), self.tabs.add(tr('Extraer'))
        t_vid = self.tabs.add(tr('Videos'))
        self._build_tab_classify(t_cls)
        self._build_tab_replace(t_rep)
        self._build_tab_extract(t_ext)
        self._build_tab_video(t_vid)

        self.stats = ctk.CTkLabel(d, text="", anchor="w", justify="left", font=self._font(12), text_color=MUTED,
                                  wraplength=360)
        self.stats.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 12))

    def _build_tab_classify(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text=tr('Nombre de la entrada'), text_color=MUTED, anchor="w", font=self._font(12)).grid(
            row=0, column=0, sticky="ew", padx=8, pady=(4, 0))
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=4)
        row.grid_columnconfigure(0, weight=1)
        self.rename_entry = ctk.CTkEntry(row, fg_color=PANEL, border_color=EDGE, text_color=CREAM,
                                         font=self._font(12))
        self.rename_entry.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.rename_entry.bind("<Return>", lambda e: self._rename())
        ctk.CTkButton(row, text=tr('Renombrar'), width=96, command=self._rename, fg_color=RED, hover_color=RED_HOT,
                      text_color=CREAM, font=self._font(12, "bold")).grid(row=0, column=1, padx=(0, 4))
        ctk.CTkButton(row, text=tr('Importar nombres desde una carpeta de referencia…'), command=self._import_names,
                      height=30, fg_color=PANEL, hover_color="#2d1717", border_width=1, border_color=EDGE,
                      text_color=CREAM, font=self._font(12)).grid(row=1, column=0, columnspan=2, sticky="ew",
                                                                  padx=4, pady=(0, 4))

        ctk.CTkLabel(tab, text=tr('¿Quién habla?'), font=self._title_font(17), text_color=CREAM, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=8, pady=(8, 2))
        grid = ctk.CTkFrame(tab, fg_color="transparent")
        grid.grid(row=3, column=0, sticky="ew")
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.char_btns = {}
        for n, (name, key) in enumerate(QUICK):
            pil = self.portraits.get(name)
            img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(64, 64)) if pil is not None else None
            b = ctk.CTkButton(grid, text=f"{name} [{key.upper()}]", image=img, compound="top",
                              command=lambda nm=name: self._assign(nm), height=100, width=70, corner_radius=10,
                              fg_color=PANEL, hover_color="#2d1717", border_width=2, border_color=EDGE,
                              text_color=char_color(name), font=self._font(12, "bold"))
            b.grid(row=0, column=n, sticky="nsew", padx=3, pady=4)
            self.char_btns[name] = b

        self.char_search = ctk.CTkEntry(tab, placeholder_text=tr('Buscar personaje de Greenvale…'), fg_color=PANEL,
                                        border_color=EDGE, text_color=CREAM, font=self._font(12))
        self.char_search.grid(row=4, column=0, sticky="ew", padx=8, pady=(6, 2))
        self.char_search.bind("<KeyRelease>", lambda e: self._build_char_list())
        self.char_list = ctk.CTkScrollableFrame(tab, height=210, fg_color=PANEL, corner_radius=8, border_width=1,
                                                border_color=EDGE, scrollbar_button_color=EDGE,
                                                scrollbar_button_hover_color=RED)
        self.char_list.grid(row=5, column=0, sticky="ew", padx=8, pady=2)
        self.char_list.grid_columnconfigure(0, weight=1)
        self.voice_hint = ctk.CTkLabel(tab, text="", text_color=MUTED, anchor="w", justify="left",
                                       font=self._font(11), wraplength=340)
        self.voice_hint.grid(row=6, column=0, sticky="ew", padx=10, pady=(2, 0))
        cust = ctk.CTkFrame(tab, fg_color="transparent")
        cust.grid(row=7, column=0, sticky="ew", padx=8, pady=(8, 0))
        cust.grid_columnconfigure(0, weight=1)
        self.custom_entry = ctk.CTkEntry(cust, placeholder_text=tr('Etiqueta personal (cinemática, OST, efectos…)'),
                                         fg_color=PANEL, border_color=EDGE, text_color=CREAM, font=self._font(12))
        self.custom_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.custom_entry.bind("<Return>", lambda e: self._assign_custom())
        ctk.CTkButton(cust, text=tr('Asignar'), width=80, command=self._assign_custom, fg_color=RED,
                      hover_color=RED_HOT, text_color=CREAM, font=self._font(12, "bold")).grid(row=0, column=1)
        ctk.CTkLabel(cust, text=tr('Para lo que no es una persona (cinemáticas, OST…). Queda guardada en la lista, grupo «Personales».'),
                     text_color=MUTED, anchor="w", justify="left", font=self._font(11), wraplength=340).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self.btn_other = ctk.CTkButton(tab, text=f"{disp(OTHER_LABEL)}   [O]", command=lambda: self._assign(OTHER_LABEL),
                                       fg_color=PANEL, hover_color="#2d1717", border_width=1, border_color=EDGE,
                                       text_color=char_color(OTHER_LABEL), height=28, font=self._font(12, "bold"))
        self.btn_other.grid(row=8, column=0, sticky="ew", padx=10, pady=(8, 0))
        self.char_btns[OTHER_LABEL] = self.btn_other
        ctk.CTkButton(tab, text=tr('Quitar etiqueta   [Supr]'), command=lambda: self._assign(None),
                      fg_color="transparent", hover_color="#2d1717", border_width=1, border_color=EDGE,
                      text_color=MUTED, height=28, font=self._font(12)).grid(row=9, column=0, sticky="ew",
                                                                              padx=10, pady=(4, 8))
        opts = ctk.CTkFrame(tab, fg_color="transparent")
        opts.grid(row=10, column=0, sticky="ew", padx=10)
        for text, var in ((tr('Pasar a la siguiente al clasificar'), self.auto_adv),
                          (tr('Reproducir al seleccionar'), self.auto_play),
                          (tr('Autoguardar el JSON'), self.autosave)):
            ctk.CTkSwitch(opts, text=text, variable=var, progress_color=RED_HOT, button_color=CREAM,
                          button_hover_color="#ffffff", fg_color=EDGE, text_color=CREAM,
                          font=self._font(12)).pack(anchor="w", pady=3)
        self._build_char_list()

    # ---------------------------------------------------------------- personajes (roster)
    def _roster_names(self):
        return [n for _g, names in self.roster for n in names]

    def _color(self, name):
        return char_color(name)

    def _tag(self, name):
        """Nombre de tag del Treeview para un personaje (los nombres pueden tener comillas o espacios)."""
        if name not in self._tag_of:
            self._tag_of[name] = f"ch{len(self._tag_of)}"
            self.tree.tag_configure(self._tag_of[name], foreground=self._color(name))
        return self._tag_of[name]

    def _configure_tags(self):
        for n in self._roster_names():
            self._tag(n)

    def _build_char_list(self):
        """Lista de personajes con buscador, agrupada; un boton por nombre."""
        for w in self.char_list.winfo_children():
            w.destroy()
        self._char_btns = {}
        q = self.char_search.get().strip().lower()
        r = 0
        for group, names in self.roster:
            shown = [n for n in names if not q or q in n.lower()]
            if not shown:
                continue
            ctk.CTkLabel(self.char_list, text=group.upper(), text_color=MUTED, anchor="w",
                         font=self._font(10, "bold")).grid(row=r, column=0, sticky="ew", padx=6, pady=(6, 0))
            r += 1
            for n in shown:
                b = ctk.CTkButton(self.char_list, text=disp(n), anchor="w", height=28, corner_radius=6,
                                  fg_color="transparent", hover_color="#2d1717", text_color=self._color(n),
                                  font=self._font(12), command=lambda nm=n: self._assign(nm))
                b.grid(row=r, column=0, sticky="ew", padx=4, pady=1)
                self._char_btns[n] = b
                r += 1
        if r == 0:
            ctk.CTkLabel(self.char_list, text=tr('Sin resultados'), text_color=MUTED).grid(row=0, column=0, pady=12)
        self._highlight_current()

    def _highlight_current(self):
        who = self.session.labels.get(self.cur) if self.cur is not None else None
        for n, b in self._char_btns.items():
            b.configure(fg_color="#3a1616" if n == who else "transparent")

    def _apply_roster_text(self, text):
        """Aplica la lista de personajes editada en Ajustes (y la guarda en los ajustes)."""
        self.roster = parse_roster(text)
        self.settings["personajes"] = text
        self.session.roster = self._roster_names()
        self._configure_tags()
        self._sync_roster_with_labels()      # conserva los personajes que ya esten usados en el JSON
        self.session.roster = self._roster_names()
        self._build_char_list()
        self._refresh_filter_menu()
        self._refresh_list(keep_idx=self.cur)

    def _sync_roster_with_labels(self):
        """Si un JSON trae personajes que no estan en la lista, se agregan en un grupo aparte."""
        known = {n.lower() for n in self._roster_names()}
        extra = sorted({w for w in self.session.labels.values() if w.lower() not in known})
        if extra:
            self._add_to_custom_group(extra)
            self.session.roster = self._roster_names()
            self._configure_tags()
            self._build_char_list()

    def _add_to_custom_group(self, names):
        """Agrega nombres al grupo «Personales» (lo crea arriba de la lista si no existe)."""
        titles = tr_all(CUSTOM_GROUP)
        for g, lst in self.roster:
            if g in titles:
                lst.extend(names)
                return
        self.roster.insert(0, (tr(CUSTOM_GROUP), list(names)))

    def _assign_custom(self):
        """Etiqueta personal: texto libre para lo que no es un personaje (cinemáticas, OST, efectos…)."""
        name = self.custom_entry.get().strip().lstrip("#").strip()
        if not name:
            self._status(tr('Escribí la etiqueta personal primero.'))
            return
        if not self._target_idxs() or not self.session.wb:
            self._status(tr('Elegí una entrada de la lista primero.'))
            return
        known = {n.lower(): n for n in self._roster_names()}
        if name.lower() in known:
            name = known[name.lower()]               # reutiliza la grafía de una etiqueta que ya existe
        else:
            self._add_to_custom_group([name])
            self.settings["personajes"] = roster_to_text(self.roster)     # queda en Ajustes > Personajes
            save_settings(self.settings)
            self.session.roster = self._roster_names()
            self._configure_tags()
            self._build_char_list()
        self.custom_entry.delete(0, "end")
        self._assign(name)

    def _used_labels(self):
        return sorted(set(self.session.labels.values()), key=str.lower)

    def _refresh_filter_menu(self):
        vals = [FILTER_ALL, FILTER_NONE] + self._used_labels()
        self.filter_menu.configure(values=vals)
        if self.filter_var.get() not in vals:
            self.filter_var.set(FILTER_ALL)

    def _build_tab_replace(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        self.rep_hint = ctk.CTkLabel(tab, text=tr('Elegí una entrada para ver qué códec usa.'), text_color=MUTED,
                                     anchor="w", justify="left", font=self._font(12), wraplength=360)
        self.rep_hint.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 8))
        ctk.CTkButton(tab, text=tr('Reemplazar el audio de esta entrada…'), command=self._replace_one, height=40,
                      fg_color=RED, hover_color=RED_HOT, text_color=CREAM, font=self._font(13, "bold")).grid(
            row=1, column=0, sticky="ew", padx=10, pady=4)
        ctk.CTkButton(tab, text=tr('Reemplazar varias desde una carpeta…'), command=self._replace_folder, height=36,
                      fg_color=PANEL, hover_color="#2d1717", border_width=1, border_color=EDGE, text_color=CREAM,
                      font=self._font(12, "bold")).grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        self.rep_note = ctk.CTkLabel(
            tab, text=(tr('Elegí cualquier audio (wav, mp3, ogg, flac…): se convierte solo al mismo códec que tenía la entrada, se crea el banco nuevo y el anterior queda renombrado como .bak.\n\nEn la carpeta, cada archivo debe llamarse como la entrada (su nombre o entryNNN).')),
            text_color=MUTED, anchor="w", justify="left", font=self._font(11), wraplength=360)
        self.rep_note.grid(row=3, column=0, sticky="ew", padx=10, pady=(8, 4))

    def _build_tab_extract(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text=tr('Formato de salida'), text_color=MUTED, anchor="w", font=self._font(12)).grid(
            row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        self.fmt_menu = ctk.CTkOptionMenu(tab, values=list(EXTRACT_FORMATS.values()), variable=self.fmt_var,
                                          fg_color=PANEL, button_color=RED, button_hover_color=RED_HOT,
                                          dropdown_fg_color=PANEL2, text_color=CREAM, font=self._font(12))
        self.fmt_menu.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        ctk.CTkSwitch(tab, text=tr('Separar en carpetas por personaje'), variable=self.split_var,
                      progress_color=RED_HOT, button_color=CREAM, button_hover_color="#ffffff", fg_color=EDGE,
                      text_color=CREAM, font=self._font(12)).grid(row=2, column=0, sticky="w", padx=10, pady=6)
        ctk.CTkButton(tab, text=tr('Extraer las seleccionadas…'), command=lambda: self._extract("sel"), height=36,
                      fg_color=RED, hover_color=RED_HOT, text_color=CREAM, font=self._font(13, "bold")).grid(
            row=3, column=0, sticky="ew", padx=10, pady=4)
        ctk.CTkButton(tab, text=tr('Extraer todas…'), command=lambda: self._extract("all"), height=34,
                      fg_color=PANEL, hover_color="#2d1717", border_width=1, border_color=EDGE, text_color=CREAM,
                      font=self._font(12, "bold")).grid(row=4, column=0, sticky="ew", padx=10, pady=4)
        ctk.CTkLabel(tab, text=(tr('Los archivos salen con el nombre que le pusiste (o el del .xsb). Con Ctrl o Mayús en la lista elegís varias.')),
                     text_color=MUTED, anchor="w", justify="left", font=self._font(11), wraplength=360).grid(
            row=5, column=0, sticky="ew", padx=10, pady=(8, 4))

    # ---------------------------------------------------------------- pestana Videos (WMV_Audio_Replacer)
    def _build_tab_video(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        if self.wmv is None:
            self.vid_note = self.vid_tools_lbl = ctk.CTkLabel(
                tab, text=tr('No se encontró WMV_Audio_Replacer.py junto al programa: esta pestaña no está disponible.'),
                text_color="#e0b050", anchor="w", justify="left", font=self._font(12), wraplength=360)
            self.vid_note.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
            return
        self.vid_mode = tk.StringVar(value="one")
        self.vid_video, self.vid_wav, self.vid_out = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.vid_br = tk.StringVar(value=str(self.settings.get("wmv_bitrate", "auto")))
        self.vid_fit = tk.BooleanVar(value=bool(self.settings.get("wmv_fit", True)))
        self.vid_keep = tk.BooleanVar(value=bool(self.settings.get("wmv_keep", True)))
        self._vid_modes = {tr('Un video'): "one", tr('Carpeta'): "dir"}

        seg = ctk.CTkSegmentedButton(tab, values=list(self._vid_modes), command=self._video_mode_changed,
                                     fg_color=PANEL, selected_color=RED, selected_hover_color=RED_HOT,
                                     unselected_color=PANEL, unselected_hover_color="#2d1717", text_color=CREAM,
                                     font=self._font(12, "bold"))
        seg.set(tr('Un video'))
        seg.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))

        self._vid_entries = {}
        for r, (key, var) in enumerate((("video", self.vid_video), ("wav", self.vid_wav), ("out", self.vid_out)), start=1):
            fr = ctk.CTkFrame(tab, fg_color="transparent")
            fr.grid(row=r, column=0, sticky="ew", padx=6, pady=2)
            fr.grid_columnconfigure(0, weight=1)
            ent = ctk.CTkEntry(fr, textvariable=var, fg_color=PANEL2, border_color=EDGE, text_color=CREAM,
                               font=self._font(12))
            ent.grid(row=0, column=0, sticky="ew", padx=4)
            ctk.CTkButton(fr, text=tr('Examinar…'), width=92, fg_color=PANEL2, hover_color="#2d1717", border_width=1,
                          border_color=EDGE, text_color=CREAM, font=self._font(12),
                          command=lambda k=key: self._video_browse(k)).grid(row=0, column=1, padx=4)
            self._vid_entries[key] = ent
        self._video_mode_changed(tr('Un video'))

        opt = ctk.CTkFrame(tab, fg_color="transparent")
        opt.grid(row=4, column=0, sticky="ew", padx=6, pady=(6, 0))
        ctk.CTkLabel(opt, text=tr('Bitrate (kbps):'), text_color=CREAM, font=self._font(12)).grid(row=0, column=0, padx=4)
        ctk.CTkComboBox(opt, values=["auto"] + [str(b) for b in self.wmv.VALID_BITRATES], variable=self.vid_br,
                        width=100, fg_color=PANEL2, border_color=EDGE, button_color=RED, button_hover_color=RED_HOT,
                        dropdown_fg_color=PANEL2, text_color=CREAM, font=self._font(12)).grid(row=0, column=1, padx=4)
        for r, (text, var) in enumerate(((tr('Ajustar la duración al original (silencio / recorte)'), self.vid_fit),
                                         (tr('Guardar el .wma y el wav adaptado'), self.vid_keep)), start=5):
            ctk.CTkSwitch(tab, text=text, variable=var, progress_color=RED_HOT, button_color=CREAM,
                          button_hover_color="#ffffff", fg_color=EDGE, text_color=CREAM,
                          font=self._font(12)).grid(row=r, column=0, sticky="w", padx=10, pady=4)

        self.vid_tools_lbl = ctk.CTkLabel(tab, text="", anchor="w", justify="left", font=self._font(11), wraplength=360)
        self.vid_tools_lbl.grid(row=7, column=0, sticky="ew", padx=10, pady=(4, 2))
        bt = ctk.CTkFrame(tab, fg_color="transparent")
        bt.grid(row=8, column=0, sticky="ew", padx=6, pady=2)
        bt.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(bt, text=tr('Ver info del video'), command=lambda: self._video_start("info"), height=36, width=140,
                      fg_color=PANEL, hover_color="#2d1717", border_width=1, border_color=EDGE, text_color=CREAM,
                      font=self._font(12, "bold")).grid(row=0, column=0, padx=4)
        ctk.CTkButton(bt, text=tr('Reemplazar el audio del video…'), command=lambda: self._video_start("go"), height=36,
                      fg_color=RED, hover_color=RED_HOT, text_color=CREAM, font=self._font(13, "bold")).grid(
            row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(bt, text=tr('▶ Reproducir'), command=self._video_play, height=36, width=110,
                      fg_color=PANEL, hover_color="#2d1717", border_width=1, border_color=EDGE, text_color=CREAM,
                      font=self._font(12, "bold")).grid(row=0, column=2, padx=4)
        self.vid_note = ctk.CTkLabel(
            tab, text=tr('Cambia la pista de audio de un .wmv/.asf por tu audio sin recodificar el video, con el mismo códec que tenía (WMA Pro o estándar). El original no se toca: sale como <nombre>_new.wmv.\n\nEn carpeta, cada video se empareja con el audio del mismo nombre.'),
            text_color=MUTED, anchor="w", justify="left", font=self._font(11), wraplength=360)
        self.vid_note.grid(row=9, column=0, sticky="ew", padx=10, pady=(6, 4))
        self._refresh_video_tools()

    def _video_play(self):
        """Reproduce el video con ffplay (de assets\\); si no está, con el reproductor del sistema."""
        path = self.vid_video.get().strip()
        if self.vid_mode.get() != "one" or not Path(path).is_file():
            path = filedialog.askopenfilename(title=tr('Video (.wmv/.asf)'),
                                              filetypes=[(tr('Video WMV/ASF'), "*.wmv *.asf"), (tr('Todos'), "*.*")])
            if not path:
                return
        ff = (self.settings.get("ffmpeg") or "").strip()
        sib = Path(ff).with_name("ffplay.exe") if ff else None
        fp = str(sib) if sib is not None and sib.is_file() else self.wmv.find_tool(("ffplay.exe", "ffplay"))
        try:
            if fp:
                subprocess.Popen([fp, "-autoexit", "-window_title", Path(path).name, path])
            elif hasattr(os, "startfile"):
                self._status(tr('Falta ffplay: se abre con el reproductor del sistema (Ajustes > Dependencias lo descarga).'))
                os.startfile(path)
            else:
                messagebox.showerror(tr('Falta ffplay'), tr('Descargalo en Ajustes > Dependencias.'))
        except OSError as ex:
            messagebox.showerror(tr('No se pudo reproducir'), str(ex))

    def _video_mode_changed(self, value):
        self.vid_mode.set(self._vid_modes.get(value, "one"))
        one = self.vid_mode.get() == "one"
        hints = {"video": tr('Video (.wmv/.asf)') if one else tr('Carpeta de videos'),
                 "wav": tr('Tu audio (wav, mp3, ogg, flac…)') if one else tr('Carpeta de audios (mismo nombre que cada video)'),
                 "out": tr('Salida (vacío = junto al original)')}
        for k, ent in self._vid_entries.items():
            try:
                ent.configure(placeholder_text=hints[k])
            except Exception:
                pass

    def _video_browse(self, which):
        one = self.vid_mode.get() == "one"
        if which == "video":
            p = (filedialog.askopenfilename(title=tr('Video (.wmv/.asf)'), filetypes=[(tr('Video WMV/ASF'), "*.wmv *.asf"), (tr('Todos'), "*.*")])
                 if one else filedialog.askdirectory(title=tr('Carpeta de videos')))
            var = self.vid_video
        elif which == "wav":
            p = (filedialog.askopenfilename(title=tr('Tu audio (wav, mp3, ogg, flac…)'), filetypes=[(tr('Audio'), "*.wav *.flac *.mp3 *.ogg *.m4a"), (tr('Todos'), "*.*")])
                 if one else filedialog.askdirectory(title=tr('Carpeta de audios (mismo nombre que cada video)')))
            var = self.vid_wav
        else:
            p = filedialog.askdirectory(title=tr('Carpeta de salida'))
            var = self.vid_out
        if p:
            var.set(p)

    def _video_tools(self):
        """(ffmpeg, ffprobe, WMAEncodeRS) como rutas, o None: Ajustes > assets\\ > junto al programa > PATH."""
        wmv, st = self.wmv, self.settings
        ff = wmv.find_tool(("ffmpeg.exe", "ffmpeg"), (st.get("ffmpeg") or "").strip())
        fp = None
        if ff:
            cand = Path(ff).with_name("ffprobe.exe" if ff.lower().endswith(".exe") else "ffprobe")
            fp = str(cand) if cand.is_file() else None
        fp = fp or wmv.find_tool(("ffprobe.exe", "ffprobe"))
        wm = (st.get("wmaencode") or "").strip()
        wm = wm if wm and Path(wm).is_file() else None
        if not wm and self.core is not None:
            f = self.core.find_wma_encoder()
            wm = str(f) if f else None
        wm = wm or wmv.find_tool(("WMAEncodeRS.exe", "WMAEncodeRS"))
        return ff, fp, wm

    def _refresh_video_tools(self):
        if self.wmv is None:
            return
        ff, fp, wm = self._video_tools()
        missing = [n for n, v in (("ffmpeg", ff), ("ffprobe", fp), ("WMAEncodeRS", wm)) if not v]
        if missing:
            self.vid_tools_lbl.configure(text=tr('Falta: {0} (ponelo en la carpeta assets o indicalo en Ajustes).', ", ".join(missing)),
                                         text_color="#e0b050")
        else:
            self.vid_tools_lbl.configure(text=tr('Listo: ffmpeg, ffprobe y WMAEncodeRS encontrados.'), text_color="#8fbf8f")

    def _video_start(self, kind):
        wmv = self.wmv
        ff, fp, wm = self._video_tools()
        if not ff or not fp:
            messagebox.showerror(tr('Falta ffmpeg'), tr('No encuentro ffmpeg y ffprobe: ponelos en la carpeta assets (junto al programa) o indicá ffmpeg en Ajustes.'))
            return
        vp, wp, od = self.vid_video.get().strip(), self.vid_wav.get().strip(), self.vid_out.get().strip()
        one = self.vid_mode.get() == "one"
        if kind == "info":
            if not vp:
                self._status(tr('Elegí un video (o una carpeta con videos) primero.'))
                return
        else:
            if not wm:
                messagebox.showerror(tr('Falta WMAEncodeRS'), tr('No encuentro WMAEncodeRS.exe (hace falta para WMA Pro / estándar): ponelo en la carpeta assets o indicalo en Ajustes.'))
                return
            if not vp or not wp:
                self._status(tr('Indicá el video y tu audio primero.'))
                return
        br = self.vid_br.get().strip()
        bitrate = None
        if kind == "go" and br.lower() not in ("", "auto"):
            try:
                bitrate = int(br)
            except ValueError:
                self._status(tr('El bitrate debe ser un número (o auto).'))
                return
        fit, keep = bool(self.vid_fit.get()), bool(self.vid_keep.get())
        self.settings.update(wmv_bitrate=br or "auto", wmv_fit=fit, wmv_keep=keep)
        save_settings(self.settings)
        log = lambda m: self._uiq.put(("log", m))

        def work_info():
            files = [Path(vp)] if one else sorted(x for x in Path(vp).iterdir() if x.suffix.lower() in wmv.VIDEO_EXTS)
            for f in files:
                log(f"{f.name}: {wmv.describe(wmv.probe(fp, f))}")
                log(tr('  cabecera ASF: {0}', wmv.describe_asf(f)))
            return len(files), 0

        def work_go():
            if one:
                pairs = [(Path(vp), Path(wp))]
            else:
                pairs, missing = wmv.pair_folder(vp, wp)
                for m in missing:
                    log(tr('Sin audio para {0}: se omite.', m.name))
                if not pairs:
                    log(tr('No hay ningún video con un audio del mismo nombre.'))
                    return 0, 0
            if od:
                Path(od).mkdir(parents=True, exist_ok=True)
            ok = bad = 0
            for v, w in pairs:
                log(f"{v.name}  +  {w.name}")
                dest = wmv.out_path_for(v, od)
                try:
                    wmv.replace_audio(v, w, dest, ff, fp, wm, bitrate=bitrate, fit=fit, keep=keep, log=log)
                    log(tr('  OK -> {0}', dest))
                    ok += 1
                except Exception as ex:
                    log(tr('ERROR: {0}', ex))
                    bad += 1
            return ok, bad

        def done(res, err):
            if err is not None:
                self._log(tr('ERROR: {0}', err))
                self._status(tr('ERROR: {0}', err))
                return
            if kind == "go":
                msg = tr('Terminado: {0} bien, {1} con error.', *res)
                self._log(msg)
                self._status(msg)
            else:
                self._status(tr('Información de video'))

        self._run_bg(tr('Información de video') if kind == "info" else tr('Reemplazando audio en video'),
                     work_info if kind == "info" else work_go, done)

    def _player_button(self, parent, text, cmd, col, primary=False):
        b = ctk.CTkButton(parent, text=text, command=cmd, height=34, corner_radius=8, font=self._font(12, "bold"),
                          fg_color=RED if primary else "#261414", hover_color=RED_HOT if primary else "#3a1d1d",
                          text_color=CREAM)
        b.grid(row=0, column=col, padx=6, pady=(10, 4), sticky="ew")
        return b

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
                self.prog_box.grid_configure(row=2, column=0, columnspan=11, sticky="w", padx=10)
            else:
                self.prog_box.grid_configure(row=0, column=10, columnspan=1, sticky="e", padx=10)
        wrap = max(220, (w // 3 if not stacked else w - 80) - 70)
        for lbl in (self.now_title, self.stats, self.rep_hint, self.rep_note, self.vid_note, self.vid_tools_lbl):
            lbl.configure(wraplength=wrap)
        self.link_lbl.configure(wraplength=max(200, w - 420))
        if abs(w - self._banner_w) > 20:
            self._banner_w = w
            self._update_banner(w)

    def _scaling(self):
        try:
            return float(self._get_window_scaling())
        except Exception:
            return 1.0

    def _update_banner(self, width_px):
        s = self._scaling()
        if self.game == "dp2":
            pil = make_banner_dp2(width_px, int(BANNER_H * s), self.art_dp2, self.logo_dp2)
        else:
            pil = make_banner(width_px, int(BANNER_H * s), self.fondo, self.logo)
        self._banner_img = ctk.CTkImage(light_image=pil, dark_image=pil,
                                        size=(max(1, int(width_px / s)), BANNER_H))
        self.banner.configure(image=self._banner_img)

    # ---------------------------------------------------------------- cambio de juego
    def _dp2_palette(self):
        return {"BASE": BG, "MANTLE": PANEL, "S0": PANEL2, "S1": EDGE, "TEXT": CREAM, "SUB": MUTED,
                "ACCENT": RED, "HOVER": RED_HOT, "ON_ACCENT": CREAM,
                "GREEN": "#8fd18f", "RED": "#e06c6c", "YELLOW": "#e0b862",
                "SEL": "#7a1111", "HEAD": "#2a0e0e", "HEAD_ACTIVE": "#3a1212", "ROW_HOVER": "#2d1717"}

    def _on_game(self, value):
        self._set_game("dp2" if value == GAME_DP2 else "dp1")

    def _set_game(self, game):
        if game == self.game:
            return
        if game == "dp2":
            if self.dp2_panel is None:
                try:
                    from dp2_panel import DP2Panel
                    self.dp2_panel = DP2Panel(self, status_cb=self._status, palette=self._dp2_palette(),
                                              app_dir=APP_DIR)
                except Exception as ex:
                    write_error_log("No se pudo cargar dp2_panel", traceback.format_exc())
                    messagebox.showerror(GAME_DP2, tr('No se pudo cargar el módulo de Deadly Premonition 2. Instalá: python -m pip install --upgrade UnityPy (y dejá dp2_panel.py junto a este archivo).\n\nDetalle: {0}', ex))
                    self.game_switch.set(GAME_DP1)
                    return
            self.bar.grid_remove()
            self.body.grid_remove()
            self.logbox.grid_remove()
            self.dp2_panel.grid(row=1, column=0, rowspan=3, sticky="nsew")
        else:
            self.dp2_panel.grid_remove()
            self.bar.grid()
            self.body.grid()
            self._toggle_log()
        self.game = game
        self.title("Deadly Premonition 2 · Audio Studio" if game == "dp2" else "Deadly Premonition · Audio Studio")
        self._banner_w = max(self.winfo_width(), 100)
        self._update_banner(self._banner_w)

    def _set_icon(self):
        try:
            from PIL import ImageTk
            if self.fondo is None:
                return
            cup = self.fondo.crop(CUP_BOX).resize((64, 64), Image.LANCZOS)
            self._icon = ImageTk.PhotoImage(cup)
            self.iconphoto(False, self._icon)
        except Exception:
            pass

    # ---------------------------------------------------------------- utilidades
    def _startup_hint(self):
        notes = []
        if self.core is None:
            notes.append("falta Deadly_Premonition_XBOX_Audio_extractor.py")
        else:
            tools = tool_status(self.core, self.settings)
            if not tools["ffmpeg"]:
                notes.append(tr('no se encontró ffmpeg (no se podrá escuchar XMA/xWMA ni convertir)'))
            if not tools["xma"]:
                notes.append(tr('sin xma2encode.exe (XMA2 se inyectaría como PCM)'))
            if not tools["wma"]:
                notes.append(tr('sin WMAEncodeRS.exe (no se podrá reemplazar audio WMA)'))
        if self.engine.backend is None:
            notes.append(tr('sin salida de audio: pip install pygame'))
        elif self.engine.backend == "winsound":
            notes.append(tr('sin pygame no hay pausa ni barra de tiempo (pip install pygame)'))
        return (tr('Listo. Abrí un .xwb para empezar.') if not notes else tr('Atención: ') + "; ".join(notes) + ".")

    def _status(self, msg):
        self.status.configure(text=msg)

    def _log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        self.logbox.configure(state="normal")
        self.logbox.insert("end", line)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _toggle_log(self):
        if self.show_log.get():
            self.logbox.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 4))
        else:
            self.logbox.grid_remove()

    def _entry(self, idx):
        return self.session.entries[idx] if idx is not None and 0 <= idx < len(self.session.entries) else None

    def _name(self, idx):
        e = self._entry(idx)
        if e is None:
            return ""
        return self.session.names.get(idx) or e["cue"]

    def _run_bg(self, label, work, done):
        """Ejecuta work() en un hilo; done(resultado, error) corre en el hilo de la interfaz."""
        if self._busy:
            self._status(tr('Hay otra operación en curso; esperá a que termine.'))
            return
        self._busy = True
        self._status(f"{label}…")
        self._log(f"{label}…")

        def runner():
            try:
                self._uiq.put(("bg", done, work(), None))
            except Exception as ex:
                self._uiq.put(("bg", done, None, ex))

        threading.Thread(target=runner, daemon=True).start()

    def _apply_settings_to_core(self):
        if self.core is not None:
            apply_settings(self.core, self.settings)

    # ---------------------------------------------------------------- ajustes
    def _open_settings(self):
        if self._settings_win is not None:
            try:
                self._settings_win.focus()
                return
            except Exception:
                self._settings_win = None
        win = ctk.CTkToplevel(self)
        self._settings_win = win
        win.title(tr('Ajustes'))
        win.geometry("640x640")
        win.minsize(420, 360)
        win.configure(fg_color=BG)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=1)
        sf = ctk.CTkScrollableFrame(win, fg_color=PANEL, scrollbar_button_color=EDGE, scrollbar_button_hover_color=RED)
        sf.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 4))
        sf.grid_columnconfigure(0, weight=1)
        st = self.settings
        tools = tool_status(self.core, st) if self.core is not None else dict(ffmpeg=None, xma=None, wma=None)
        v = dict(
            ffmpeg=tk.StringVar(value=st.get("ffmpeg", "")), xma2encode=tk.StringVar(value=st.get("xma2encode", "")),
            wmaencode=tk.StringVar(value=st.get("wmaencode", "")),
            xma_mode=tk.StringVar(value=st.get("xma_mode", "auto")),
            xma_quality=tk.StringVar(value=str(st.get("xma_quality", 75))),
            xma_block=tk.StringVar(value=str(st.get("xma_block", 64))),
            wma_bitrate=tk.StringVar(value=str(st.get("wma_bitrate", "auto"))),
            policy=tk.StringVar(value=POLICY_LABELS.get(st.get("policy"), POLICY_LABELS["same"])),
            backup=tk.BooleanVar(value=bool(st.get("backup", True))),
            lang=tk.StringVar(value=LANGS.get(st.get("lang", "es"), LANGS["es"])))
        row = [0]

        def section(text):
            ctk.CTkLabel(sf, text=text, font=self._title_font(16), text_color=CREAM, anchor="w").grid(
                row=row[0], column=0, sticky="ew", padx=12, pady=(14, 2))
            row[0] += 1

        def note(text, ok=None):
            color = MUTED if ok is None else ("#8fbf8f" if ok else "#e0b050")
            lbl = ctk.CTkLabel(sf, text=text, text_color=color, anchor="w", justify="left", font=self._font(11),
                               wraplength=520)
            lbl.grid(row=row[0], column=0, sticky="ew", padx=12)
            row[0] += 1
            return lbl

        def path_row(var, ftypes):
            fr = ctk.CTkFrame(sf, fg_color="transparent")
            fr.grid(row=row[0], column=0, sticky="ew", padx=8, pady=2)
            fr.grid_columnconfigure(0, weight=1)
            ctk.CTkEntry(fr, textvariable=var, fg_color=PANEL2, border_color=EDGE, text_color=CREAM,
                         font=self._font(12)).grid(row=0, column=0, sticky="ew", padx=4)
            ctk.CTkButton(fr, text=tr('Examinar…'), width=92, fg_color=PANEL2, hover_color="#2d1717", border_width=1,
                          border_color=EDGE, text_color=CREAM, font=self._font(12),
                          command=lambda: var.set(filedialog.askopenfilename(filetypes=ftypes) or var.get())).grid(
                row=0, column=1, padx=4)
            row[0] += 1

        def menu_row(label, var, values):
            fr = ctk.CTkFrame(sf, fg_color="transparent")
            fr.grid(row=row[0], column=0, sticky="ew", padx=8, pady=3)
            fr.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(fr, text=label, text_color=CREAM, font=self._font(12), anchor="w").grid(row=0, column=0, padx=4)
            ctk.CTkOptionMenu(fr, values=values, variable=var, fg_color=PANEL2, button_color=RED,
                              button_hover_color=RED_HOT, dropdown_fg_color=PANEL2, text_color=CREAM,
                              font=self._font(12)).grid(row=0, column=1, sticky="ew", padx=4)
            row[0] += 1

        def entry_row(label, var):
            fr = ctk.CTkFrame(sf, fg_color="transparent")
            fr.grid(row=row[0], column=0, sticky="ew", padx=8, pady=3)
            ctk.CTkLabel(fr, text=label, text_color=CREAM, font=self._font(12), anchor="w").grid(row=0, column=0, padx=4)
            ctk.CTkEntry(fr, textvariable=var, width=80, fg_color=PANEL2, border_color=EDGE, text_color=CREAM,
                         font=self._font(12)).grid(row=0, column=1, padx=4)
            row[0] += 1

        section("Idioma · Language · Язык")
        menu_row("Idioma / Language / Язык:", v["lang"], list(LANGS.values()))
        note(tr('Se aplica al reiniciar el programa.'))
        dep_state = {"cancel": None, "running": False, "q": queue.Queue()}
        assets_dir = APP_DIR / "assets"
        det = {}

        def refresh_notes():
            t = tool_status(self.core, self.settings) if self.core is not None else dict(ffmpeg=None, xma=None, wma=None)
            for key, miss in (("ffmpeg", tr('No se encontró en el PATH (indicá ffmpeg.exe).')),
                              ("xma", tr('No encontrado junto al programa (ni empaquetado).')),
                              ("wma", tr('No encontrado junto al programa (ni empaquetado).'))):
                if key in det:
                    det[key].configure(text=tr('Detectado: {0}', t[key]) if t[key] else miss,
                                       text_color="#8fbf8f" if t[key] else "#e0b050")

        section(tr('Dependencias'))
        if deps is None:
            note(tr('Falta dp_dependencies.py junto al programa: el descargador no está disponible.'), False)
        else:
            note(tr('Los programas de terceros (ffmpeg, ffprobe, ffplay, xma2encode, WMAEncodeRS y, para Deadly Premonition 2, fsbankcl y vgmstream) no vienen incluidos: se descargan desde sus fuentes y quedan en la carpeta assets.'))
            dep_lbl = note("")
            dep_bar = ctk.CTkProgressBar(sf, progress_color=RED_HOT, fg_color=PANEL2, height=8)
            dep_bar.set(0)
            dep_bar.grid(row=row[0], column=0, sticky="ew", padx=14, pady=(6, 2))
            row[0] += 1
            dep_msg = note("")

            def dep_status():
                lines = deps.status_lines(assets_dir)
                dep_lbl.configure(text="   ".join(("✔ " if ok else "✘ ") + n for n, ok in lines),
                                  text_color="#8fbf8f" if all(ok for _, ok in lines) else "#e0b050")

            def dep_finish(ok, err):
                dep_state["running"] = False
                dl_btn.configure(state="normal")
                ap = str(assets_dir)
                if ap not in os.environ.get("PATH", "").split(os.pathsep):
                    os.environ["PATH"] = ap + os.pathsep + os.environ.get("PATH", "")
                if self.core is not None:      # si el motor no mira esta carpeta (ajustes en %APPDATA%), ruta explícita
                    for key, fname, finder in (("xma2encode", "xma2encode.exe", self.core.find_xma2_encoder),
                                               ("wmaencode", "WMAEncodeRS.exe", self.core.find_wma_encoder)):
                        if not v[key].get().strip() and (assets_dir / fname).is_file() and not finder():
                            v[key].set(str(assets_dir / fname))
                            self.settings[key] = str(assets_dir / fname)
                self.ffmpeg = shutil.which("ffmpeg")
                self._apply_settings_to_core()
                self._refresh_replace_hint()
                self._refresh_video_tools()
                if self.dp2_panel is not None:
                    self.dp2_panel.check_tools()
                dep_status()
                refresh_notes()
                if err:
                    dep_msg.configure(text="\n".join(err), text_color="#e0b050")
                else:
                    dep_bar.set(1)
                    dep_msg.configure(text=tr('Listo: dependencias instaladas en assets.'), text_color="#8fbf8f")
                self._log(("; ".join(err)) if err else tr('Listo: dependencias instaladas en assets.'))

            def dep_poll():
                try:
                    while True:
                        m = dep_state["q"].get_nowait()
                        if m[0] == "p":
                            if m[1] is not None:
                                dep_bar.set(max(0.0, min(1.0, m[1])))
                            if m[2]:
                                dep_msg.configure(text=m[2], text_color=MUTED)
                        elif m[0] == "l":
                            self._log(m[1])
                        else:
                            dep_finish(m[1], m[2])
                except queue.Empty:
                    pass
                except Exception:
                    return                      # ventana cerrada
                if dep_state["running"]:
                    win.after(120, dep_poll)

            def dep_start():
                if dep_state["running"]:
                    return
                need = deps.missing(assets_dir)
                if not any(need.values()):
                    dep_msg.configure(text=tr('Ya están todas las dependencias.'), text_color="#8fbf8f")
                    return
                q = dep_state["q"]
                dep_state.update(running=True, cancel=threading.Event())
                dl_btn.configure(state="disabled")
                dep_bar.set(0)
                dep_msg.configure(text=tr('Descargando dependencias…'), text_color=MUTED)
                deps.run_in_thread(assets_dir, lambda f, t: q.put(("p", f, t)), lambda t: q.put(("l", t)),
                                   lambda ok, err: q.put(("d", ok, err)), dep_state["cancel"])
                dep_poll()

            def open_assets():
                assets_dir.mkdir(parents=True, exist_ok=True)
                if hasattr(os, "startfile"):
                    os.startfile(str(assets_dir))

            brow = ctk.CTkFrame(sf, fg_color="transparent")
            brow.grid(row=row[0], column=0, sticky="w", padx=8, pady=(4, 2))
            row[0] += 1
            dl_btn = ctk.CTkButton(brow, text=tr('Descargar dependencias'), command=dep_start, fg_color=RED,
                                   hover_color=RED_HOT, text_color=CREAM, font=self._font(13, "bold"), width=190)
            dl_btn.grid(row=0, column=0, padx=4)
            ctk.CTkButton(brow, text=tr('Abrir carpeta assets'), command=open_assets, fg_color=PANEL2,
                          hover_color="#2d1717", border_width=1, border_color=EDGE, text_color=CREAM,
                          font=self._font(12), width=150).grid(row=0, column=1, padx=4)
            note(tr('Fuentes: assets.zip y assets2 (MediaFire), ffmpeg/ffprobe/ffplay (gyan.dev, respaldo BtbN/GitHub) y vgmstream (GitHub).'))
            dep_status()
        section("ffmpeg")
        path_row(v["ffmpeg"], [("ffmpeg", "*.exe *"), (tr('Todos'), "*.*")])
        det["ffmpeg"] = note(tr('Detectado: {0}', tools['ffmpeg']) if tools["ffmpeg"] else tr('No se encontró en el PATH (indicá ffmpeg.exe).'), bool(tools["ffmpeg"]))
        section(tr('XMA2 · xma2encode.exe'))
        path_row(v["xma2encode"], [(tr('Ejecutable'), "*.exe"), (tr('Todos'), "*.*")])
        det["xma"] = note(tr('Detectado: {0}', tools['xma']) if tools["xma"] else tr('No encontrado junto al programa (ni empaquetado).'), bool(tools["xma"]))
        menu_row(tr('Modo:'), v["xma_mode"], ["auto", "xma2", "pcm"])
        entry_row(tr('Calidad (/Quality):'), v["xma_quality"])
        entry_row(tr('Bloque en KB (/BlockSize):'), v["xma_block"])
        note(tr('auto = XMA2 si hay encoder, si no PCM · xma2 = exigir el encoder · pcm = siempre PCM.'))
        section(tr('WMA Pro / estándar · WMAEncodeRS.exe'))
        path_row(v["wmaencode"], [(tr('Ejecutable'), "*.exe"), (tr('Todos'), "*.*")])
        det["wma"] = note(tr('Detectado: {0}', tools['wma']) if tools["wma"] else tr('No encontrado junto al programa (ni empaquetado).'), bool(tools["wma"]))
        menu_row(tr('Bitrate (kbps):'), v["wma_bitrate"], ["auto"] + [str(b) for b in self.core.VALID_XWMA_BITRATES]
                 if self.core is not None else ["auto"])
        note(tr('auto = el perfil más cercano al de la entrada original.'))
        section(tr('Al reemplazar'))
        menu_row(tr('Códec:'), v["policy"], list(POLICY_LABELS.values()))
        ctk.CTkSwitch(sf, text=tr('Renombrar el banco anterior como .bak (nunca pisa un backup existente)'),
                      variable=v["backup"], progress_color=RED_HOT, button_color=CREAM, button_hover_color="#ffffff",
                      fg_color=EDGE, text_color=CREAM, font=self._font(12)).grid(row=row[0], column=0, sticky="w",
                                                                                padx=14, pady=8)
        row[0] += 1
        section(tr('Personajes de Greenvale'))
        note(tr('Una línea por personaje; las líneas que empiezan con # son títulos de grupo. Podés agregar, quitar o renombrar. Los nombres ya usados en un JSON se conservan.'))
        roster_tb = ctk.CTkTextbox(sf, height=240, fg_color=PANEL2, text_color=CREAM, border_width=1,
                                   border_color=EDGE, font=ctk.CTkFont(family="Consolas", size=12))
        roster_tb.grid(row=row[0], column=0, sticky="ew", padx=12, pady=4)
        roster_tb.insert("1.0", roster_to_text(self.roster))
        row[0] += 1

        def restore_roster():
            roster_tb.delete("1.0", "end")
            roster_tb.insert("1.0", roster_to_text(ROSTER_DEFAULT))

        ctk.CTkButton(sf, text=tr('Restaurar la lista de Greenvale'), command=restore_roster, fg_color=PANEL2,
                      hover_color="#2d1717", border_width=1, border_color=EDGE, text_color=CREAM,
                      font=self._font(12)).grid(row=row[0], column=0, sticky="w", padx=12, pady=(2, 10))
        row[0] += 1

        def save():
            inv = {lab: key for key, lab in POLICY_LABELS.items()}
            self.settings.update(
                ffmpeg=v["ffmpeg"].get().strip(), xma2encode=v["xma2encode"].get().strip(),
                wmaencode=v["wmaencode"].get().strip(), xma_mode=v["xma_mode"].get(),
                xma_quality=_int(v["xma_quality"].get(), 75), xma_block=_int(v["xma_block"].get(), 64),
                wma_bitrate=v["wma_bitrate"].get(), policy=inv.get(v["policy"].get(), "same"),
                backup=bool(v["backup"].get()))
            lang_inv = {name: code for code, name in LANGS.items()}
            new_lang = lang_inv.get(v["lang"].get(), "es")
            lang_changed = new_lang != self.settings.get("lang", "es")
            self.settings["lang"] = new_lang
            self._apply_roster_text(roster_tb.get("1.0", "end"))
            save_settings(self.settings)
            self._apply_settings_to_core()
            self.ffmpeg = shutil.which("ffmpeg")
            self._refresh_replace_hint()
            self._refresh_video_tools()
            self._status(tr('Ajustes guardados.'))
            self._log(tr('Ajustes guardados.'))
            close()
            if lang_changed:
                messagebox.showinfo("Idioma / Language / Язык",
                                    "Language saved. Restart the program to apply it.\n"
                                    "Idioma guardado: reiniciá el programa para aplicarlo.\n"
                                    "Язык сохранён. Перезапустите программу, чтобы применить его.")

        def close():
            if dep_state["cancel"] is not None:
                dep_state["cancel"].set()
            self._settings_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", close)
        bt = ctk.CTkFrame(win, fg_color="transparent")
        bt.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        bt.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(bt, text=tr('Guardar'), command=save, fg_color=RED, hover_color=RED_HOT, text_color=CREAM,
                      font=self._font(13, "bold"), width=120).grid(row=0, column=1, padx=4)
        ctk.CTkButton(bt, text=tr('Cancelar'), command=close, fg_color=PANEL2, hover_color="#2d1717", border_width=1,
                      border_color=EDGE, text_color=CREAM, font=self._font(12), width=100).grid(row=0, column=2)

    # ---------------------------------------------------------------- banco / JSON
    def _open_bank(self):
        if self.core is None:
            messagebox.showerror(tr('Falta el lector de bancos'),
                                 tr('Poné Deadly_Premonition_XBOX_Audio_extractor.py junto a este archivo.'))
            return
        if self._busy:
            self._status(tr('Hay una operación en curso.'))
            return
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(title=tr('Abrir banco de ondas'),
                                          filetypes=[("XACT Wave Bank", "*.xwb"), (tr('Todos'), "*.*")])
        if not path:
            return
        self._status(tr('Leyendo banco…'))
        self.update_idletasks()
        try:
            wb = self.core.WaveBank(path)
        except Exception as ex:
            messagebox.showerror(tr('No se pudo abrir el banco'), str(ex))
            self._status(tr('Error al abrir el banco.'))
            return
        self._install_bank(path, wb, self.core.find_paired_xsb_for(path))

    def _pick_xsb(self):
        if not self.session.wb:
            self._status(tr('Primero abrí un banco.'))
            return
        path = filedialog.askopenfilename(title=tr('Elegir XSB'), filetypes=[("XACT Sound Bank", "*.xsb"), (tr('Todos'), "*.*")])
        if path:
            self.session.xsb_bank = None
            self._install_bank(self.session.bank_path, self.session.wb, Path(path), keep_labels=True)

    def _install_bank(self, path, wb, xsb, keep_labels=False):
        s = self.session
        old_labels = dict(s.labels) if keep_labels else {}
        old_names = dict(s.names) if keep_labels else {}
        old_json = s.json_path if keep_labels else None
        self.engine.stop()
        self.cache.clear()
        self.cache_bytes = 0
        s.bank_path, s.wb, s.bank_name, s.xsb_path = str(path), wb, wb.bank_name, (str(xsb) if xsb else None)
        if not keep_labels:
            s.xsb_bank = None
            side0 = s.default_json_path()
            if side0 and not side0.is_file() and s.legacy_json_path() and s.legacy_json_path().is_file():
                side0 = s.legacy_json_path()
            if side0 and side0.is_file():
                try:      # el JSON recuerda el .xsb y el banco que se eligieron a mano la vez anterior
                    meta = json.loads(side0.read_text(encoding="utf-8"))
                    if not xsb and meta.get("xsb"):
                        cand = Path(path).with_name(meta["xsb"])
                        if cand.is_file():
                            xsb = cand
                            s.xsb_path = str(cand)
                    if meta.get("banco_en_xsb"):
                        s.xsb_bank = meta["banco_en_xsb"]
                except Exception:
                    pass
        names, info = names_by_track(self.core, path, wb, xsb, s.xsb_bank)
        s.xsb_bank_used = info["bank"]
        s.entries = build_entries(self.core, wb, names)
        s.labels = old_labels
        s.names = old_names
        s.json_path = old_json
        s.dirty = False
        self.cur = None
        named = sum(1 for e in s.entries if not e["cue"].startswith("entry"))
        self.bank_lbl.configure(text=tr('{0}  ·  {1} entradas  ·  XSB: {2}', Path(path).name, len(s.entries), Path(xsb).name if xsb else tr('ninguno')))
        msg = tr("Banco '{0}' abierto: {1} entradas, {2} con nombre.", wb.bank_name, len(s.entries), named)
        side = s.default_json_path()
        if side and not side.is_file() and s.legacy_json_path() and s.legacy_json_path().is_file():
            side = s.legacy_json_path()          # JSON guardado con el nombre antiguo
        if not keep_labels and side and side.is_file():
            try:
                ok, dropped, diff = s.load(side)
                if side != s.default_json_path():
                    s.json_path = s.default_json_path()   # al guardar, ya sale como <banco>.json
                msg += tr(' JSON anterior cargado ({0} etiquetas', ok) + (tr(', {0} descartadas', dropped) if dropped else "") + \
                       (tr(', {0} con nombre distinto', diff) if diff else "") + ")."
            except Exception as ex:
                msg += tr(' (No se pudo leer {0}: {1})', side.name, ex)
        self._apply_link_ui(info)
        self._sync_roster_with_labels()
        self._refresh_filter_menu()
        self._refresh_list()
        self._update_progress()
        self._status(msg)
        self._log(msg)
        self._show_entry(None)

    def _reload_bank(self, select=None):
        """Relee el banco desde disco (despues de reemplazar) conservando etiquetas, nombres y XSB."""
        s = self.session
        try:
            wb = self.core.WaveBank(s.bank_path)
        except Exception as ex:
            messagebox.showerror(tr('No se pudo releer el banco'), str(ex))
            return
        self._install_bank(s.bank_path, wb, Path(s.xsb_path) if s.xsb_path else None, keep_labels=True)
        if select is not None and self._entry(select) is not None:
            self._select(select, play=self.auto_play.get(), scroll=True)

    def _apply_link_ui(self, info):
        s = self.session
        banks = info.get("banks") or []
        self.bank_menu.configure(values=[AUTO_BANK] + banks)
        self.bank_menu.set(s.xsb_bank if s.xsb_bank in banks else AUTO_BANK)
        warn = (not info.get("ok")) and bool(s.xsb_path)
        self.link_lbl.configure(text=info.get("text", ""),
                                text_color="#e0b050" if warn else "#8fbf8f" if s.xsb_path else MUTED)

    def _on_bank_choice(self, value):
        """Elegir en el .xsb el banco cuyos nombres se aplican a este .xwb (p.ej. bgm.xsb -> scnd2)."""
        s = self.session
        if not s.wb:
            return
        s.xsb_bank = None if value == AUTO_BANK else value
        names, info = names_by_track(self.core, s.bank_path, s.wb, s.xsb_path, s.xsb_bank)
        s.xsb_bank_used = info["bank"]
        s.entries = build_entries(self.core, s.wb, names)
        s.dirty = True
        self._apply_link_ui(info)
        self._refresh_list(keep_idx=self.cur)
        self._show_entry(self.cur)
        self._autosave()
        self._status(info["text"])
        self._log(info["text"])

    def _confirm_discard(self):
        s = self.session
        if s.dirty and not self.autosave.get():
            ans = messagebox.askyesnocancel(tr('Cambios sin guardar'), tr('Hay etiquetas sin guardar. ¿Guardar el JSON antes de seguir?'))
            if ans is None:
                return False
            if ans:
                self._save_json()
        return True

    def _autosave(self):
        if self.autosave.get() and self.session.wb:
            try:
                self.session.save()
            except Exception as ex:
                self._status(tr('No se pudo autoguardar: {0}', ex))

    def _save_json(self):
        s = self.session
        if not s.wb:
            self._status(tr('No hay nada que guardar: abrí un banco primero.'))
            return
        try:
            p = s.save()
        except Exception as ex:
            messagebox.showerror(tr('No se pudo guardar'), str(ex))
            return
        self._status(tr('Guardado: {0}  ({1} clasificadas)', p, len(s.labels)))
        self._log(tr('JSON guardado: {0}', p))
        self._update_title()

    def _load_json(self):
        s = self.session
        if not s.wb:
            self._status(tr('Primero abrí el banco al que corresponde el JSON.'))
            return
        path = filedialog.askopenfilename(title=tr('Cargar JSON'), filetypes=[("JSON", "*.json"), (tr('Todos'), "*.*")])
        if not path:
            return
        try:
            ok, dropped, diff = s.load(path)
        except Exception as ex:
            messagebox.showerror(tr('No se pudo cargar'), str(ex))
            return
        self._sync_roster_with_labels()
        self._refresh_filter_menu()
        self._refresh_list(keep_idx=self.cur)
        self._update_progress()
        self._refresh_detail()
        msg = tr('JSON cargado: {0} etiquetas', ok) + (tr(', {0} descartadas', dropped) if dropped else "") + \
              (tr(', {0} con nombre distinto al banco', diff) if diff else "") + "."
        self._status(msg)
        self._log(msg)

    # ---------------------------------------------------------------- lista
    def _refresh_list(self, keep_idx=None, keep_sel=None):
        s = self.session
        q = self.search.get().strip().lower()
        flt = self.filter_var.get()
        self.visible = []
        self._suppress_select = True
        try:
            self.tree.delete(*self.tree.get_children())
            for e in s.entries:
                i = e["idx"]
                who = s.labels.get(i)
                if flt == FILTER_NONE and who:
                    continue
                if flt not in (FILTER_ALL, FILTER_NONE) and who != flt:
                    continue
                name = self._name(i)
                if q and q not in name.lower() and q not in e["cue"].lower() and q != str(i):
                    continue
                self.visible.append(i)
                dur = fmt_time(e["secs"]) if e["secs"] else "—"
                shown = name + (" ✎" if i in s.names else "")
                self.tree.insert("", "end", iid=str(i), tags=((self._tag(who),) if who else ()),
                                 values=(i, shown, e["fmt"], dur, disp(who) if who else ""))
            if keep_sel:
                vis = set(self.visible)
                sel = [str(i) for i in keep_sel if i in vis]
                if sel:
                    self.tree.selection_set(sel)
                    self.tree.see(sel[0])
            elif keep_idx is not None and keep_idx in self.visible:
                self.tree.selection_set(str(keep_idx))
                self.tree.see(str(keep_idx))
        finally:
            self._suppress_select = False

    def _target_idxs(self):
        """Entradas sobre las que actuar: todas las marcadas en la lista (Ctrl/Mayús+clic) o, si no hay, la actual."""
        try:
            sel = [int(i) for i in self.tree.selection()]
        except (ValueError, tk.TclError):
            sel = []
        if sel:
            return sel
        return [self.cur] if self.cur is not None else []

    def _on_tree_select(self, _event):
        if self._suppress_select:
            return
        sel = self.tree.selection()
        if len(sel) == 1:
            self._select(int(sel[0]), play=self.auto_play.get())
        elif len(sel) > 1:
            self._status(tr('{0} entradas seleccionadas (usá «Extraer las seleccionadas»).', len(sel)))

    # ---------------------------------------------------------------- seleccion y audio
    def _select(self, idx, play=False, scroll=False):
        e = self._entry(idx)
        if e is None:
            return
        self.cur = idx
        self._token += 1
        self.engine.stop()
        self._show_entry(idx)
        if scroll and idx in self.visible:
            self._suppress_select = True
            try:
                self.tree.selection_set(str(idx))
                self.tree.see(str(idx))
            finally:
                self._suppress_select = False
        if idx in self.cache:
            self._audio_ready(idx, self.cache[idx], play)
            return
        if not self.ffmpeg:
            self._status(tr('Falta ffmpeg en el PATH: no puedo decodificar este audio.'))
            return
        self._status(tr('Decodificando {0}…', self._name(idx)))
        token, wb, core, ffmpeg, rate, ch = self._token, self.session.wb, self.core, self.ffmpeg, \
            self.engine.rate, self.engine.channels
        entry = wb.entries[idx]

        def work():
            try:
                ext, data = core.extract_entry_bytes(wb, entry, "raw")
                pcm = decode_to_pcm(ffmpeg, data, ext, rate, ch)
                self._uiq.put(("pcm", token, idx, pcm, play))
            except Exception as ex:
                self._uiq.put(("err", token, idx, str(ex), play))

        threading.Thread(target=work, daemon=True).start()

    def _audio_ready(self, idx, pcm, play):
        if idx not in self.cache:
            self.cache[idx] = pcm
            self.cache_bytes += len(pcm)
            while self.cache_bytes > 150_000_000 and len(self.cache) > 1:
                victim = next(k for k in self.cache if k != idx)
                self.cache_bytes -= len(self.cache.pop(victim))
        if idx != self.cur:
            return
        self.engine.load(pcm)
        self._update_player_ui()
        if self.engine.backend is None:
            self._status(tr('No hay salida de audio disponible: instalá pygame (pip install pygame).'))
            return
        e = self._entry(idx)
        self._status(tr('{0}  ·  {1}  ·  {2} canal(es)  ·  {3:.1f} s', self._name(idx), e['fmt'], e['ch'], self.engine.duration))
        if play:
            self.engine.play()
            self._update_player_ui()

    def _show_entry(self, idx):
        e = self._entry(idx) if idx is not None else None
        if e is None:
            self.now_title.configure(text=tr('Elegí una entrada'))
            self.now_meta.configure(text="")
            self.slider.set(0)
            self.time_lbl.configure(text="00:00 / 00:00")
            self.rename_entry.delete(0, "end")
        else:
            self.now_title.configure(text=self._name(idx))
            dur = f"{e['secs']:.1f} s" if e["secs"] else tr('duración ?')
            self.now_meta.configure(text=tr('#{0}  ·  {1}  ·  {2} canal(es)  ·  {3} Hz  ·  {4}', e['idx'], e['fmt'], e['ch'], e['rate'], dur))
            self.slider.set(0)
            self.time_lbl.configure(text=f"00:00 / {fmt_time(e['secs'])}")
            self.rename_entry.delete(0, "end")
            self.rename_entry.insert(0, self._name(idx))
        self._refresh_detail()
        self._refresh_replace_hint()
        self._update_player_ui()

    def _refresh_replace_hint(self):
        s = self.session
        if self.core is None or self.cur is None or not s.wb:
            self.rep_hint.configure(text=tr('Elegí una entrada para ver qué códec usa.'), text_color=MUTED)
            return
        text, ok = replace_hint(self.core, self.settings, s.wb.entries[self.cur], tool_status(self.core, self.settings))
        self.rep_hint.configure(text=text, text_color="#8fbf8f" if ok else "#e0b050")

    def _refresh_detail(self):
        who = self.session.labels.get(self.cur) if self.cur is not None else None
        if who:
            self.now_who.configure(text=tr('Personaje: {0}', disp(who)), text_color=self._color(who))
        else:
            self.now_who.configure(text=tr('Sin clasificar') if self.cur is not None else "", text_color=MUTED)
        for name, b in self.char_btns.items():
            on = (name == who)
            b.configure(border_color=self._color(name) if on else EDGE, border_width=3 if on else (1 if name == OTHER_LABEL else 2),
                        fg_color="#2b1414" if on else PANEL)
        self._highlight_current()
        others = shares_voice(who) if who else []
        self.voice_hint.configure(text=(tr('Comparte actor de voz con: ') + ", ".join(others) + tr(' (según los créditos)'))
                                  if others else "")
        self._update_stats()

    def _update_stats(self):
        s = self.session
        total = len(s.entries)
        if not total:
            self.stats.configure(text="")
            return
        counts = {}
        for who in s.labels.values():
            counts[who] = counts.get(who, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:8]
        txt = "   ".join(f"{disp(c)}: {n}" for c, n in top)
        more = len(counts) - len(top)
        if more > 0:
            txt += tr('   (+{0} personajes más)', more)
        self.stats.configure(text=(txt + "   ·   " if txt else "") + tr('Sin clasificar: {0}', total - len(s.labels)))

    def _update_progress(self):
        s = self.session
        total, done = len(s.entries), len(s.labels)
        self.prog_lbl.configure(text=tr('{0} / {1} clasificadas', done, total))
        self.prog_bar.set(done / total if total else 0)
        self._update_stats()
        self._update_title()

    def _update_title(self):
        mark = "*" if (self.session.dirty and not self.autosave.get()) else ""
        name = Path(self.session.bank_path).name if self.session.bank_path else ""
        self.title(f"{mark}Deadly Premonition · Audio Studio" + (f"  ·  {name}" if name else ""))

    # ---------------------------------------------------------------- reproductor
    def _toggle_play(self):
        if self.cur is None:
            return
        if self.engine.state == "playing":
            self.engine.pause()
        elif self.engine.pcm and self.cur in self.cache:
            self.engine.play()
        else:
            self._select(self.cur, play=True)
        self._update_player_ui()

    def _stop(self):
        self.engine.stop()
        self.slider.set(0)
        self._update_player_ui()

    def _on_slider(self, value):
        if not self.engine.pcm or not self.engine.can_seek:
            return
        if self._seek_job:
            self.after_cancel(self._seek_job)
        self._seek_job = self.after(120, lambda v=float(value): self._do_seek(v))

    def _do_seek(self, frac):
        self._seek_job = None
        if self.engine.pcm and self.engine.can_seek:
            self.engine.play(start=frac * self.engine.duration)
            self._update_player_ui()

    def _update_player_ui(self):
        playing = self.engine.state == "playing"
        self.btn_play.configure(text=tr('❚❚ Pausar') if playing and self.engine.can_seek else
                                (tr('■ Detener') if playing else tr('▶ Reproducir')))

    def _prev(self):
        self._step(-1)

    def _next(self):
        self._step(+1)

    def _step(self, delta):
        if not self.visible:
            return
        try:
            pos = self.visible.index(self.cur)
        except ValueError:
            pos = -1 if delta > 0 else len(self.visible)
        pos = max(0, min(len(self.visible) - 1, pos + delta))
        self._select(self.visible[pos], play=self.auto_play.get(), scroll=True)

    # ---------------------------------------------------------------- clasificar y renombrar
    def _assign(self, name):
        s = self.session
        targets = self._target_idxs()
        if not targets or not s.wb:
            self._status(tr('Elegí una entrada de la lista primero.'))
            return
        multi = len(targets) > 1
        old_visible = list(self.visible)
        pos_of = {i: n for n, i in enumerate(old_visible)}
        last = max(targets, key=lambda i: pos_of.get(i, -1))      # la que queda mas abajo en la lista
        pos = pos_of.get(last, 0)
        for i in targets:
            if name is None:
                s.labels.pop(i, None)
            else:
                s.labels[i] = name
        s.dirty = True
        self._autosave()
        self._refresh_filter_menu()
        advance = self.auto_adv.get() and name is not None
        if multi:
            self._refresh_list(keep_sel=targets)
        else:
            self._refresh_list(keep_idx=targets[0])
        self._update_progress()
        self._refresh_detail()
        if multi:
            self._status(tr('{0} entradas clasificadas como «{1}».', len(targets), disp(name))
                         if name is not None else tr('Etiqueta quitada de {0} entradas.', len(targets)))
        if advance and self.visible:
            if last in self.visible:
                nxt = self.visible[min(self.visible.index(last) + 1, len(self.visible) - 1)]
            else:
                nxt = self.visible[min(pos, len(self.visible) - 1)]
            if nxt != last or last not in self.visible:
                self._select(nxt, play=self.auto_play.get(), scroll=True)

    def _rename(self):
        s = self.session
        targets = self._target_idxs()
        if not targets or not s.wb:
            self._status(tr('Elegí una entrada de la lista primero.'))
            return
        new = self.rename_entry.get().strip()
        if len(targets) == 1:
            i = targets[0]
            orig = s.entries[i]["cue"]
            if not new or new == orig:
                s.names.pop(i, None)
            else:
                s.names[i] = new
            s.dirty = True
            self._autosave()
            self._refresh_list(keep_idx=i)
            self._show_entry(i)
            self._status(tr('#{0} ahora se llama «{1}».', i, self._name(i)))
            return
        # varias entradas: mismo nombre base + numero correlativo (en el orden de la lista)
        order = [i for i in self.visible if i in set(targets)] or sorted(targets)
        if not new:
            for i in order:
                s.names.pop(i, None)
        else:
            width = max(2, len(str(len(order))))
            for n, i in enumerate(order, 1):
                s.names[i] = f"{new}_{n:0{width}d}"
        s.dirty = True
        self._autosave()
        self._refresh_list(keep_sel=order)
        if self.cur in order:
            self._show_entry(self.cur)
        self._status(tr('{0} entradas renombradas como «{1}_NN».', len(order), new)
                     if new else tr('Nombre original restaurado en {0} entradas.', len(order)))

    def _import_names(self):
        """Pone a las entradas del banco los nombres de una carpeta de archivos ya bien nombrados (p.ej. la
        copia extraida de Xbox), emparejando por el CONTENIDO del audio (no importa el codec ni el orden).
        Los nombres quedan en el JSON (campo 'nombres') y se usan al extraer."""
        s = self.session
        if self.core is None or not s.wb:
            self._status(tr('Primero abrí un banco.'))
            return
        if self._busy:
            self._status(tr('Hay otra operación en curso; esperá a que termine.'))
            return
        if not self.ffmpeg:
            self._status(tr('Hace falta ffmpeg para comparar los audios.'))
            return
        folder = filedialog.askdirectory(title=tr('Carpeta de referencia (archivos con los nombres correctos)'))
        if not folder:
            return
        refs = [f for f in Path(folder).rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
        if not refs:
            messagebox.showinfo(tr('Sin archivos'), tr('No encontré archivos de audio en esa carpeta (ni en sus subcarpetas).'))
            return
        self.engine.stop()
        core, wb, ffmpeg, q = self.core, s.wb, self.ffmpeg, self._uiq
        total = len(refs) + len(wb.entries)

        def work():
            ref_env, ref_name, n = {}, {}, 0
            for f in refs:
                n += 1
                if n % 10 == 0 or n == total:
                    q.put(("status", tr('Analizando referencia {0}/{1}…', n, total)))
                try:
                    pcm = decode_to_pcm(ffmpeg, f.read_bytes(), f.suffix, 8000, 1)
                except Exception:
                    continue
                ref_env[str(f)] = (len(pcm) / 16000.0, envelope(pcm))
                ref_name[str(f)] = f.stem
            ent_env = {}
            for i in range(len(wb.entries)):
                n += 1
                if n % 10 == 0 or n == total:
                    q.put(("status", tr('Analizando banco {0}/{1}…', n, total)))
                try:
                    ext, data = core.extract_entry_bytes(wb, wb.entries[i], "raw")
                    pcm = decode_to_pcm(ffmpeg, data, ext, 8000, 1)
                except Exception:
                    continue
                ent_env[i] = (len(pcm) / 16000.0, envelope(pcm))
            q.put(("status", tr('Comparando audios…')))
            res = match_by_content(ent_env, ref_env)
            res["names"] = ref_name
            res["n_refs"] = len(ref_env)
            return res

        def done(res, err):
            if err is not None:
                self._log(tr('ERROR al importar nombres: {0}', err))
                messagebox.showerror(tr('No se pudieron importar los nombres'), str(err))
                return
            names, matches, doubtful = res["names"], res["matches"], res["doubtful"]
            for i, (rk, sc) in sorted(doubtful.items()):
                self._log(tr('  Dudoso #{0} ({1}): parece «{2}» (similitud {3:.2f}).', i, self._name(i), names[rk], sc))
            for i in res["unmatched"][:30]:
                self._log(tr('  Sin pareja: #{0} ({1})', i, self._name(i)))
            summary = (tr('{0} entradas emparejadas con seguridad\n{1} dudosas\n{2} sin pareja\n{3} archivos de referencia sin usar', len(matches), len(doubtful), len(res['unmatched']), len(res['unused'])))
            self._log(summary.replace("\n", " · "))
            apply_safe = bool(matches) and messagebox.askyesno(tr('Importar nombres'), summary + tr('\n\n¿Aplicar los {0} nombres seguros?', len(matches)))
            apply_doubt = False
            if doubtful and (apply_safe or not matches):
                apply_doubt = messagebox.askyesno(
                    tr('Entradas dudosas'),
                    tr('Quedan {0} entradas dudosas: casi siempre el mejor candidato es el correcto, pero si hay frases idénticas con distinto nombre puede confundirse.\n\n¿Aplicar también el mejor candidato de cada una? (quedan anotadas en el registro para revisarlas)', len(doubtful)))
            if not apply_safe and not apply_doubt:
                self._status(tr('Importación de nombres cancelada.'))
                return
            todo = dict(matches) if apply_safe else {}
            if apply_doubt:
                todo.update(doubtful)
                for i, (rk, sc) in sorted(doubtful.items()):
                    self._log(tr('  Aplicado (dudoso) #{0} -> «{1}» ({2:.2f})', i, names[rk], sc))
            for i, (rk, sc) in todo.items():
                if names[rk] == s.entries[i]["cue"]:
                    s.names.pop(i, None)
                else:
                    s.names[i] = names[rk]
            s.dirty = True
            self._autosave()
            self._refresh_list(keep_idx=self.cur)
            self._show_entry(self.cur)
            self._update_progress()
            self._status(tr('{0} nombres importados y guardados en el JSON.', len(todo)))
            self._log(tr('{0} nombres importados desde {1}', len(todo), folder))

        self._run_bg(tr('Importando nombres desde {0}', Path(folder).name), work, done)

    def _on_key(self, event):
        if self.game == "dp2":
            return None
        try:
            w = self.focus_get()
        except Exception:      # tkinter a veces lanza KeyError con los menus desplegables
            w = None
        if isinstance(w, (tk.Entry, tk.Text)):
            return None
        k = (event.keysym or "").lower()
        if k in KEYMAP:
            self._assign(KEYMAP[k])
        elif k in ("delete", "backspace"):
            self._assign(None)
        elif k == "space":
            self._toggle_play()
        elif k in ("down", "up") and w is self.tree:
            return None     # el Treeview ya mueve la seleccion solo
        elif k in ("down", "right", "n"):
            self._next()
        elif k in ("up", "left", "p"):
            self._prev()
        else:
            return None
        return "break"

    # ---------------------------------------------------------------- reemplazar
    def _replace_one(self):
        s = self.session
        if self.core is None or not s.wb or self.cur is None:
            self._status(tr('Elegí una entrada de la lista primero.'))
            return
        if self._busy:
            self._status(tr('Hay otra operación en curso; esperá a que termine.'))
            return
        idx = self.cur
        path = filedialog.askopenfilename(
            title=tr('Audio nuevo para #{0} · {1}', idx, self._name(idx)),
            filetypes=[(tr('Audio'), " ".join("*" + x for x in AUDIO_EXTS)), (tr('Todos'), "*.*")])
        if not path:
            return
        self._apply_settings_to_core()
        self.engine.stop()
        core, bank, backup = self.core, s.bank_path, bool(self.settings.get("backup", True))

        def work():
            wb = core.WaveBank(bank)
            out = Path(bank).with_name(Path(bank).name + ".new")
            try:
                old, new_fmt, new_len, delta, warnings = core.inject_entry(wb, idx, path, str(out))
                bak = core.commit_new_bank(bank, out, backup=backup)
            finally:
                out.unlink(missing_ok=True)
            return dict(old=core.codec_label(old), new=core.FMT_NAMES.get(new_fmt, "?"), old_len=old["play_len"],
                        new_len=new_len, delta=delta, warnings=warnings, bak=bak)

        def done(res, err):
            if err is not None:
                self._log(tr('ERROR al reemplazar #{0}: {1}', idx, err))
                self._status(tr('No se pudo reemplazar (el banco original no se tocó).'))
                messagebox.showerror(tr('No se pudo reemplazar'), str(err))
                return
            self._log(tr('#{0}: {1} ({2} bytes) -> {3} ({4} bytes), diferencia {5:+d} bytes.', idx, res['old'], res['old_len'], res['new'], res['new_len'], res['delta']))
            for w in res["warnings"]:
                self._log(tr('  ATENCIÓN: {0}', w))
            self._log(tr('Banco escrito: {0}', bank) + (tr('  ·  backup: {0}', Path(res['bak']).name) if res["bak"] else ""))
            self._reload_bank(select=idx)
            self._status(tr('#{0} reemplazado.', idx) + (tr(' Backup: {0}', Path(res['bak']).name) if res["bak"] else ""))

        self._run_bg(tr('Reemplazando #{0} con {1}', idx, Path(path).name), work, done)

    def _replace_folder(self):
        s = self.session
        if self.core is None or not s.wb:
            self._status(tr('Primero abrí un banco.'))
            return
        if self._busy:
            self._status(tr('Hay otra operación en curso; esperá a que termine.'))
            return
        folder = filedialog.askdirectory(title=tr('Carpeta con los audios nuevos'))
        if not folder:
            return
        repl, unmatched = match_folder_files(folder, s.entries, s.names)
        if not repl:
            messagebox.showinfo(tr('Sin coincidencias'), tr('Ningún archivo de esa carpeta se llama como una entrada del banco (su nombre, el del .xsb o entryNNN).'))
            return
        extra = tr('\n{0} archivo(s) sin pareja se ignoran.', len(unmatched)) if unmatched else ""
        if not messagebox.askyesno(tr('Reemplazar desde carpeta'),
                                   tr('{0} archivo(s) coinciden con entradas del banco.{1}\n\nSe convertirán al códec de cada entrada y se creará el banco nuevo. ¿Continuar?', len(repl), extra)):
            return
        self._apply_settings_to_core()
        self.engine.stop()
        core, bank, backup = self.core, s.bank_path, bool(self.settings.get("backup", True))

        def work():
            wb = core.WaveBank(bank)
            out = Path(bank).with_name(Path(bank).name + ".new")
            try:
                report = core.batch_inject_entries(wb, {i: str(p) for i, p in repl.items()}, str(out))
                bak = core.commit_new_bank(bank, out, backup=backup)
            finally:
                out.unlink(missing_ok=True)
            return dict(report=report, bak=bak)

        def done(res, err):
            if err is not None:
                self._log(tr('ERROR en el reemplazo por carpeta: {0}', err))
                self._status(tr('No se pudo reemplazar (el banco original no se tocó).'))
                messagebox.showerror(tr('No se pudo reemplazar'), str(err))
                return
            rep = res["report"]
            for r in rep:
                for w in r.get("warnings", []):
                    self._log(tr('  #{0} ATENCIÓN: {1}', r['index'], w))
            self._log(tr('{0} entradas reemplazadas.', len(rep)) + (tr('  ·  backup: {0}', Path(res['bak']).name) if res["bak"] else ""))
            self._reload_bank(select=self.cur)
            self._status(tr('{0} entradas reemplazadas.', len(rep)) + (tr(' Backup: {0}', Path(res['bak']).name) if res["bak"] else ""))

        self._run_bg(tr('Reemplazando {0} entradas', len(repl)), work, done)

    # ---------------------------------------------------------------- extraer
    def _fmt_key(self):
        inv = {label: key for key, label in EXTRACT_FORMATS.items()}
        return inv.get(self.fmt_var.get(), "raw")

    def _extract(self, scope):
        s = self.session
        if self.core is None or not s.wb:
            self._status(tr('Primero abrí un banco.'))
            return
        if self._busy:
            self._status(tr('Hay otra operación en curso; esperá a que termine.'))
            return
        if scope == "sel":
            idxs = [int(i) for i in self.tree.selection()] or ([self.cur] if self.cur is not None else [])
        else:
            idxs = list(range(len(s.entries)))
        if not idxs:
            self._status(tr('No hay entradas seleccionadas.'))
            return
        outdir = filedialog.askdirectory(title=tr('Carpeta de destino'))
        if not outdir:
            return
        fmt, split = self._fmt_key(), bool(self.split_var.get())
        self.settings.update(extract_format=fmt, split_by_char=split)
        save_settings(self.settings)
        core, wb = self.core, s.wb
        names = {i: self._name(i) for i in idxs}
        labels = dict(s.labels)
        q = self._uiq

        def work():
            ok, errors, used = 0, [], set()
            for n, i in enumerate(idxs, 1):
                try:
                    ext, data = core.extract_entry_bytes(wb, wb.entries[i], fmt)
                    sub = Path(outdir) / (safe_filename(labels.get(i, tr('Sin clasificar'))) if split else "")
                    sub.mkdir(parents=True, exist_ok=True)
                    base = safe_filename(names[i])
                    path = sub / (base + ext)
                    if str(path).lower() in used:
                        path = sub / f"{base}_{i}{ext}"
                    used.add(str(path).lower())
                    path.write_bytes(data)
                    ok += 1
                except Exception as ex:
                    errors.append(f"#{i}: {ex}")
                if n % 20 == 0 or n == len(idxs):
                    q.put(("status", tr('Extrayendo {0}/{1}…', n, len(idxs))))
            return dict(ok=ok, errors=errors)

        def done(res, err):
            if err is not None:
                self._log(tr('ERROR al extraer: {0}', err))
                messagebox.showerror(tr('No se pudo extraer'), str(err))
                return
            for e in res["errors"][:10]:
                self._log(tr('  ERROR {0}', e))
            msg = tr('{0} archivos extraídos en {1}', res['ok'], outdir) + (tr(' ({0} con error)', len(res['errors'])) if res["errors"] else "")
            self._log(msg)
            self._status(msg)

        self._run_bg(tr('Extrayendo {0} entradas', len(idxs)), work, done)

    # ---------------------------------------------------------------- bucle de eventos
    def _poll(self):
        if not self._alive:
            return
        try:
            while True:
                msg = self._uiq.get_nowait()
                kind = msg[0]
                if kind == "pcm":
                    _k, token, idx, pcm, play = msg
                    self._audio_ready(idx, pcm, play and token == self._token)
                elif kind == "err":
                    _k, token, idx, text, _play = msg
                    if token == self._token:
                        self._status(tr('No se pudo decodificar #{0}: {1}', idx, text))
                elif kind == "log":
                    self._log(msg[1])
                elif kind == "status":
                    self._status(msg[1])
                elif kind == "bg":
                    _k, done, res, err = msg
                    self._busy = False
                    try:
                        done(res, err)
                    except Exception as ex:
                        self._log(tr('ERROR interno: {0}', ex))
        except queue.Empty:
            pass
        if self.engine.pcm:
            pos = self.engine.position()
            if self.engine.duration > 0:
                self.slider.set(min(1.0, pos / self.engine.duration))
            self.time_lbl.configure(text=f"{fmt_time(pos)} / {fmt_time(self.engine.duration)}")
            self._update_player_ui()
        self.after(100, self._poll)

    def report_callback_exception(self, exc, val, tb):
        """Errores dentro de los eventos de la ventana: al archivo de errores y al registro, sin cerrar la app."""
        text = "".join(traceback.format_exception(exc, val, tb))
        write_error_log("Error en la interfaz", text)
        print(text, file=sys.stderr)
        try:
            self._log(tr('ERROR interno: {0}  (detalle en {1})', val, ERROR_LOG.name))
        except Exception:
            pass

    def _on_close(self):
        if self._busy and not messagebox.askyesno(tr('Operación en curso'), tr('Hay una operación en curso. ¿Salir igual?')):
            return
        if not self._confirm_discard():
            return
        self._alive = False
        self.engine.close()
        self.destroy()


ERROR_LOG = APP_DIR / "dp_studio_error.log"


def write_error_log(title, tb):
    try:
        import platform
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} · {title} ===\n")
            f.write(f"Python {platform.python_version()} · {platform.platform()} · "
                    f"customtkinter {getattr(ctk, '__version__', '?')}\n{tb}\n")
    except OSError:
        pass


def main():
    try:
        ver = tuple(int(x) for x in str(getattr(ctk, "__version__", "0.0")).split(".")[:2])
        if ver < (5, 1):
            raise RuntimeError(tr('customtkinter {0} es demasiado viejo (hace falta 5.1 o más): python -m pip install --upgrade customtkinter', getattr(ctk, '__version__', '?')))
        core = load_core()
        app = App(core)
    except Exception:
        tb = traceback.format_exc()
        write_error_log("Error al iniciar", tb)
        print(tb)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(tr('No se pudo iniciar Audio Studio'), tb[-1500:] + tr('\n\nDetalle en {0}', ERROR_LOG))
            root.destroy()
        except Exception:
            pass
        raise SystemExit(1)
    app.mainloop()


if __name__ == "__main__":
    main()
