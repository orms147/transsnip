<div align="center">

# TransSnip

**Hotkey-driven screen translation for Windows.**
Snip a region, translate a full screen, or auto-translate video subtitles — without leaving what you're doing.

OCR + multi-provider translation (Google · Gemini · Claude · OpenRouter) with context-aware prompts, text-to-speech, and a language-learning mode.

### 🌐 [Try the interactive demo →](https://orms147.github.io/transsnip-demo/)

No install needed — the browser demo walks through the region-capture → OCR → translate flow.

</div>

---

## What it does

You're reading a Japanese article, a Chinese video, an English research paper. Instead of *screenshot → switch to browser → paste into Google Translate → read*, you press one hotkey and the translation appears in place.

TransSnip lives in the system tray and stays out of your way until you call it.

| Mode | Hotkey | What happens |
|------|--------|--------------|
| **Region translate** | `Alt+T` | Drag a box (snipping-tool style) → a floating popup shows the translation next to it |
| **Full-screen translate** | `Alt+F` | OCRs the whole screen → overlays each translated block on top of the original text |
| **Video subtitle** | `Alt+V` | Pick the subtitle area once → a live bar below it keeps translating on-screen subtitles in real time |
| **Audio subtitle** | `Alt+A` | Translate the *spoken audio* of a video that has **no subtitles** → live bar at the bottom of the screen (Whisper ASR). *Optional* |
| **Open Settings** | `Ctrl+Alt+S` | Settings window (all hotkeys are rebindable) |

> Hotkeys are global — they work even while another app has focus, and can be changed in **Settings → Hotkeys**.
>
> **Playing fullscreen games?** Turn on **Settings → Hotkeys → Chế độ game (ưu tiên cao)**. It catches the hotkey with a low-level keyboard hook (before the game — or any other app that grabbed the combo — sees it) and freezes the screen the moment you press `Alt+T`, so a game that minimizes on focus loss still gets snipped from the correct frame. If the game runs as Administrator, run TransSnip as Administrator too. For exclusive-fullscreen titles, borderless/windowed fullscreen still gives the smoothest overlay experience.
>
> **Audio subtitle** is optional + heavier: install the extra (`pip install -e ".[audio]"`), then just press **Alt+A** (no enable flag — pressing it is the opt-in). On first use it downloads a Whisper model (~460 MB for `small`) to `%APPDATA%\transsnip\whisper-models`. Runs on-device: CPU by default (~3–8 s latency), or an NVIDIA GPU automatically if CUDA libs are present (`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`). Pick the model size in **Settings → Audio**. Not bundled in the default installer.

## Features

- **Runs in the tray** — no main window; opened on hotkey, dismissed with `Esc` or click-outside.
- **Multi-provider translation** — switch freely in Settings:
  - **Google Translate** (free, no API key) — fastest, great default.
  - **Google Gemini** (free tier ~1500/day) · **Anthropic Claude** (premium) · **OpenRouter** (300+ models, free tier) — context-aware LLM translation.
- **Offline-capable OCR** — Windows OCR (uses installed language packs) with a bundled **PP-OCRv6 / RapidOCR** fallback: one multilingual model reads Chinese, Japanese, English and Latin scripts (plus a PP-OCRv5 Korean model) with no internet.
- **Context presets** — per-domain system prompts + glossary (Gaming, Programming, Medical…) so the LLM keeps proper nouns and uses the right tone.
- **Three display modes** (Settings → Translation):
  - **Simple** — translation only.
  - **Standard** — adds 🔊 buttons to hear the source and the translation.
  - **Learning** — per-word **IPA** + meaning under the English source, click any word to hear it.
- **Text-to-speech** — Microsoft Edge neural voices (free, online) with an offline Windows SAPI fallback; voice / speed / volume configurable.
- **Học tiếng Trung (Chinese study mode)** — opt-in (Settings → Tiếng Trung). When the source is Chinese, every word shows
  **pinyin** (tone-coloured) and its **Hán-Việt** reading, plus the whole sentence in Hán-Việt
  (chosen per pronunciation in context: 董事**长** → trưởng, **长**城 → trường). Click a word for the
  **word card**: Vietnamese meaning, HSK level, each character's Hán-Việt / radical / components,
  **stroke-order animation** (optional ~30 MB download), and **AI usage notes** with example
  sentences (on demand, cached). Save words to the **vocabulary notebook** and review them with
  spaced repetition (Anki-style), or export to Anki. Offline dictionary — see
  `resources/zh/NOTICE.md` for data sources and licences.
- **Compact reading view** — long passages in study mode (Chinese or English IPA) flow like normal
  text; hover a word for its reading and meaning, click it for the word card / pronunciation.
- **Translation cache** — repeated text is returned instantly and for free.
- **Translation history** — browse, copy and replay recent translations from the tray.
- **Glass UI** — popup and windows blur what's behind them (toggle in Settings → Display);
  **light / dark / auto theme** (follows Windows).
- **Pin the popup** to keep it open while you work; unpinned, it closes on any click outside.
  The pin is remembered until you turn it off.

## Install (end users)

Download **`TransSnip-Setup-0.4.1.exe`** from the [latest release](../../releases/latest) and run it.

- Per-user install (`%LOCALAPPDATA%\Programs\TransSnip`) — **no administrator rights needed**.
- Bundles everything (Python runtime + OCR models). No separate downloads.
- Windows SmartScreen may warn *"Unknown publisher"* (the build isn't code-signed) → **More info → Run anyway**.

After installing, launch TransSnip, open **Settings** (`Ctrl+Alt+S` or double-click the tray icon), pick a provider, and you're ready. Google Translate works with no key; for the LLM providers paste an API key (stored securely in Windows Credential Manager).

## Run from source (developers)

Requires **Python 3.11+** on **Windows**.

```bash
git clone https://github.com/orms147/transsnip.git
cd transsnip

python -m venv .venv
.venv\Scripts\activate

# Install the app with the feature extras you want
pip install -e ".[dev,ocr,translate,tts,learning,zh]"

# Fetch the OCR models + build the Chinese dictionary once (gitignored binaries)
python scripts/fetch_models.py
python scripts/fetch_zh_data.py

# Run
python -m transsnip
```

API keys are read from Windows Credential Manager (via `keyring`) — set them in **Settings → Translation**, never in a file.

### Build the installer

```bash
python scripts/fetch_models.py                  # ensure models are present
python scripts/fetch_zh_data.py                 # ensure the Chinese dictionary is built
pyinstaller --noconfirm --clean TransSnip.spec  # → dist\TransSnip\ (onedir)
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss  # → dist\installer\TransSnip-Setup-<version>.exe
```

The spec bundles the OCR models into `resources/models/` and the wordninja wordlist; if the `.exe` is missing OCR data, re-run `scripts/fetch_models.py` before building.

### Run the tests

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

## How it works

```
 Hotkey  ─►  Capture (mss)  ─►  OCR (Windows OCR │ RapidOCR)  ─►  Translate (cache → provider)  ─►  Display
                                                                                                     ├─ popup (region)
                                                                                                     ├─ inline overlay (full-screen)
                                                                                                     └─ subtitle bar (video)
```

Everything heavy (OCR, network) runs off the Qt UI thread so the interface never freezes.

## Project layout

```
transsnip/
├─ app.py              # AppController — wires hotkeys → modes → display
├─ capture/            # screen capture (mss) + region selector overlay
├─ ocr/                # Windows OCR + RapidOCR (PP-OCRv6), segmentation, model paths
├─ translate/          # provider clients (google_free / gemini / claude / openrouter) + cache + registry
├─ linguistic/         # IPA generation + per-word breakdown
├─ tts/                # Edge TTS + Windows SAPI fallback
├─ display/            # floating popup, inline overlay, subtitle bar
├─ modes/              # video subtitle pipeline (region/fullscreen wired in app.py)
├─ hotkeys/            # global hotkey manager
├─ tray/               # system tray icon + menu
├─ ui/                 # settings window, theme, icons, atoms
└─ config/             # pydantic settings, keyring store, history

scripts/fetch_models.py
tests/                 # pytest suite (pure-logic units)
TransSnip.spec         # PyInstaller spec
installer.iss          # Inno Setup script
```

## Tech stack

Python 3.11+ · PySide6 (Qt6) · mss · Windows OCR (pywinrt) / RapidOCR (ONNX Runtime) · edge-tts · pydantic · keyring · PyInstaller + Inno Setup.

## License

MIT
