# DP Audio Studio

**[Español](#español) · [English](#english) · [Русский](#русский)**

---

## Español

**DP Audio Studio** es una herramienta de escritorio (Windows) para trabajar con el audio de **Deadly Premonition**: escuchar, nombrar, clasificar, extraer y **reemplazar** el audio de los bancos XACT (`.xwb` / `.xsb`), y cambiar la pista de audio de los videos `.wmv` / `.asf`.

### Funciones

- **Clasificar:** escucha cada entrada del banco, ponle nombre y asígnale un personaje (York, Emily, George, Otro o personajes propios). Se guarda en un JSON junto al banco (`scnd.json`, `bgm.json`, `voice.json`…).
- **Reemplazar:** tu audio nuevo se convierte solo **al mismo códec de la entrada original** (XMA2, WMA Pro / estándar, MS-ADPCM o PCM), se crea el banco nuevo y el anterior queda como `.bak`.
- **Extraer:** exporta las entradas con los nombres puestos, sin decodificar o como WAV / OGG / MP3, opcionalmente separadas por personaje.
- **Videos:** cambia el audio de un `.wmv` / `.asf` sin recodificar el video, con el mismo códec que tenía. Incluye botón para reproducir el video.
- Interfaz en **español, inglés y ruso**.

### Instalación (recomendada)

1. Descarga el `.zip` de la sección **[Releases](../../releases)** y descomprímelo.
2. Ejecuta `DP_Audio_Studio.exe`.
3. Ve a **Ajustes → Dependencias** y pulsa **Descargar dependencias**. Se descargan y se descomprimen solas en la carpeta `assets` junto al programa.

### Dependencias (no incluidas)

Este repositorio **no contiene ni distribuye programas de terceros**. Se descargan desde Ajustes, directamente de sus fuentes:

| Programa | Para qué sirve | Origen |
|---|---|---|
| `ffmpeg.exe`, `ffprobe.exe`, `ffplay.exe` | Conversión, lectura de audio/video y reproducción | Build oficial de Windows ([gyan.dev](https://www.gyan.dev/ffmpeg/builds/), respaldo: [BtbN](https://github.com/BtbN/FFmpeg-Builds)) |
| `xma2encode.exe`, `WMAEncodeRS.exe` | Codificar XMA2 y WMA Pro / estándar | Paquete `assets.zip` (MediaFire) |
| `XWBTool.exe`, `XwbStudio.exe` | Solo referencia; el programa no los usa | Paquete `assets.zip` (MediaFire) |

Cada programa pertenece a sus respectivos autores y se rige por su propia licencia. Este proyecto no está afiliado a ellos ni a los titulares de Deadly Premonition. Comprueba que su uso cumple las licencias que te apliquen.

### Ejecutar desde el código

```bash
pip install customtkinter pillow pygame
python DP_Audio_Studio.py
```

Compilar a `.exe` (sale liviano, sin programas de terceros):

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean DP_Audio_Studio.spec
```

### Atajos

`Y` / `E` / `G` / `O` = York / Emily / George / Otro · `Supr` = quitar etiqueta · `Espacio` = reproducir/pausar · flechas o `N` / `P` = siguiente / anterior · `Ctrl+S` = guardar JSON.

### Estructura

| Archivo | Contenido |
|---|---|
| `DP_Audio_Studio.py` | Programa principal (interfaz) |
| `Deadly_Premonition_XBOX_Audio_extractor.py` | Motor de lectura/escritura de bancos `.xwb` / `.xsb` |
| `WMV_Audio_Replacer.py` | Motor de la pestaña Videos (también funciona solo) |
| `dp_dependencies.py` | Descargador de dependencias |
| `assets/` | Imágenes e icono (los programas de terceros se descargan aquí) |
| `extras/` | Scripts antiguos |

---

## English

**DP Audio Studio** is a Windows desktop tool for working with the audio of **Deadly Premonition**: listen to, name, classify, extract and **replace** audio in XACT banks (`.xwb` / `.xsb`), and swap the audio track of `.wmv` / `.asf` videos.

### Features

- **Classify:** listen to each bank entry, name it and assign a character (York, Emily, George, Other, or your own). Saved as a JSON next to the bank (`scnd.json`, `bgm.json`, `voice.json`…).
- **Replace:** your new audio is automatically converted **to the same codec as the original entry** (XMA2, WMA Pro / standard, MS-ADPCM or PCM), the new bank is built and the old one is kept as `.bak`.
- **Extract:** export entries with their assigned names, undecoded or as WAV / OGG / MP3, optionally split by character.
- **Videos:** replace the audio of a `.wmv` / `.asf` without re-encoding the video, keeping the original codec. Includes a play button.
- Interface in **Spanish, English and Russian**.

### Installation (recommended)

1. Download the `.zip` from **[Releases](../../releases)** and extract it.
2. Run `DP_Audio_Studio.exe`.
3. Go to **Settings → Dependencies** and click **Download dependencies**. Everything is downloaded and extracted automatically into the `assets` folder next to the program.

### Dependencies (not included)

This repository **does not contain or distribute third-party programs**. They are downloaded from Settings, directly from their sources:

| Program | Purpose | Source |
|---|---|---|
| `ffmpeg.exe`, `ffprobe.exe`, `ffplay.exe` | Conversion, audio/video probing and playback | Official Windows build ([gyan.dev](https://www.gyan.dev/ffmpeg/builds/), fallback: [BtbN](https://github.com/BtbN/FFmpeg-Builds)) |
| `xma2encode.exe`, `WMAEncodeRS.exe` | Encoding XMA2 and WMA Pro / standard | `assets.zip` package (MediaFire) |
| `XWBTool.exe`, `XwbStudio.exe` | Reference only; the program does not use them | `assets.zip` package (MediaFire) |

Each program belongs to its respective authors and is governed by its own license. This project is not affiliated with them or with the rights holders of Deadly Premonition. Make sure your use complies with the licenses that apply to you.

### Run from source

```bash
pip install customtkinter pillow pygame
python DP_Audio_Studio.py
```

Build the `.exe` (lightweight, no third-party programs inside):

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean DP_Audio_Studio.spec
```

### Shortcuts

`Y` / `E` / `G` / `O` = York / Emily / George / Other · `Del` = clear label · `Space` = play/pause · arrows or `N` / `P` = next / previous · `Ctrl+S` = save JSON.

### Layout

| File | Contents |
|---|---|
| `DP_Audio_Studio.py` | Main program (UI) |
| `Deadly_Premonition_XBOX_Audio_extractor.py` | `.xwb` / `.xsb` bank read/write engine |
| `WMV_Audio_Replacer.py` | Videos tab engine (also runs standalone) |
| `dp_dependencies.py` | Dependency downloader |
| `assets/` | Images and icon (third-party programs are downloaded here) |
| `extras/` | Old scripts |

---

## Русский

**DP Audio Studio** — настольная программа (Windows) для работы со звуком **Deadly Premonition**: прослушивание, именование, классификация, извлечение и **замена** звука в банках XACT (`.xwb` / `.xsb`), а также замена аудиодорожки в видео `.wmv` / `.asf`.

### Возможности

- **Классификация:** прослушивайте каждую запись банка, давайте ей имя и назначайте персонажа (York, Emily, George, Другой или собственные). Данные сохраняются в JSON рядом с банком (`scnd.json`, `bgm.json`, `voice.json`…).
- **Замена:** ваш новый звук автоматически конвертируется **в тот же кодек, что и у исходной записи** (XMA2, WMA Pro / стандартный, MS-ADPCM или PCM), создаётся новый банк, а старый сохраняется как `.bak`.
- **Извлечение:** экспорт записей с назначенными именами — без декодирования или в WAV / OGG / MP3, при желании с разделением по персонажам.
- **Видео:** замена звука в `.wmv` / `.asf` без перекодирования видео, с сохранением исходного кодека. Есть кнопка воспроизведения.
- Интерфейс на **испанском, английском и русском**.

### Установка (рекомендуется)

1. Скачайте `.zip` из раздела **[Releases](../../releases)** и распакуйте его.
2. Запустите `DP_Audio_Studio.exe`.
3. Откройте **Настройки → Зависимости** и нажмите **Скачать зависимости**. Всё скачивается и распаковывается автоматически в папку `assets` рядом с программой.

### Зависимости (не включены)

Этот репозиторий **не содержит и не распространяет сторонние программы**. Они скачиваются из настроек напрямую из своих источников:

| Программа | Назначение | Источник |
|---|---|---|
| `ffmpeg.exe`, `ffprobe.exe`, `ffplay.exe` | Конвертация, анализ аудио/видео и воспроизведение | Официальная сборка для Windows ([gyan.dev](https://www.gyan.dev/ffmpeg/builds/), запасной вариант: [BtbN](https://github.com/BtbN/FFmpeg-Builds)) |
| `xma2encode.exe`, `WMAEncodeRS.exe` | Кодирование XMA2 и WMA Pro / стандартного | Пакет `assets.zip` (MediaFire) |
| `XWBTool.exe`, `XwbStudio.exe` | Только для справки; программа их не использует | Пакет `assets.zip` (MediaFire) |

Каждая программа принадлежит своим авторам и распространяется по собственной лицензии. Проект не связан ни с ними, ни с правообладателями Deadly Premonition. Убедитесь, что ваше использование соответствует применимым к вам лицензиям.

### Запуск из исходников

```bash
pip install customtkinter pillow pygame
python DP_Audio_Studio.py
```

Сборка `.exe` (лёгкая, без сторонних программ внутри):

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean DP_Audio_Studio.spec
```

### Горячие клавиши

`Y` / `E` / `G` / `O` = York / Emily / George / Другой · `Del` = снять метку · `Пробел` = воспроизведение/пауза · стрелки или `N` / `P` = следующая / предыдущая · `Ctrl+S` = сохранить JSON.

### Структура

| Файл | Назначение |
|---|---|
| `DP_Audio_Studio.py` | Основная программа (интерфейс) |
| `Deadly_Premonition_XBOX_Audio_extractor.py` | Движок чтения/записи банков `.xwb` / `.xsb` |
| `WMV_Audio_Replacer.py` | Движок вкладки «Видео» (работает и отдельно) |
| `dp_dependencies.py` | Загрузчик зависимостей |
| `assets/` | Изображения и значок (сторонние программы скачиваются сюда) |
| `extras/` | Старые скрипты |
