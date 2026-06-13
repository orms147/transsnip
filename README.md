<div align="center">

# TransSnip

**Hotkey-driven screen translation for Windows.**
Snip a region, translate a full screen, or auto-translate video subtitles — without leaving what you're doing.

OCR + multi-provider translation (Google · Gemini · Claude · OpenRouter) with context-aware prompts, text-to-speech, and a language-learning mode.

</div>

---

## What it does

You're reading a Japanese article, a Chinese video, an English research paper. Instead of *screenshot → switch to browser → paste into Google Translate → read*, you press one hotkey and the translation appears in place.

TransSnip lives in the system tray and stays out of your way until you call it.

| Mode | Hotkey | What happens |
|------|--------|--------------|
| **Region translate** | `Alt+T` | Drag a box (snipping-tool style) → a floating popup shows the translation next to it |
| **Full-screen translate** | `Alt+F` | OCRs the whole screen → overlays each translated block on top of the original text |
| **Video subtitle** | `Alt+V` | Pick the subtitle area once → a live bar below it keeps translating subtitles in real time |
| **Open Settings** | `Ctrl+Alt+S` | Settings window (all hotkeys are rebindable) |

> Hotkeys are global — they work even while another app has focus, and can be changed in **Settings → Hotkeys**.

## Features

- **Runs in the tray** — no main window; opened on hotkey, dismissed with `Esc` or click-outside.
- **Multi-provider translation** — switch freely in Settings:
  - **Google Translate** (free, no API key) — fastest, great default.
  - **Google Gemini** (free tier ~1500/day) · **Anthropic Claude** (premium) · **OpenRouter** (300+ models, free tier) — context-aware LLM translation.
- **Offline-capable OCR** — Windows OCR (uses installed language packs) with a bundled **PP-OCRv5 / RapidOCR** fallback that reads Chinese, Japanese, Korean, English and Latin scripts with no internet.
- **Context presets** — per-domain system prompts + glossary (Gaming, Programming, Medical…) so the LLM keeps proper nouns and uses the right tone.
- **Three display modes** (Settings → Translation):
  - **Simple** — translation only.
  - **Standard** — adds 🔊 buttons to hear the source and the translation.
  - **Learning** — per-word **IPA** + meaning under the English source, click any word to hear it.
- **Text-to-speech** — Microsoft Edge neural voices (free, online) with an offline Windows SAPI fallback; voice / speed / volume configurable.
- **Translation cache** — repeated text is returned instantly and for free.
- **Translation history** — browse, copy and replay recent translations from the tray.
- **Light / dark / auto theme** (follows Windows).

## Install (end users)

Download **`TransSnip-Setup.exe`** from the [Releases](../../releases) page and run it.

- Per-user install (`%LOCALAPPDATA%\Programs\TransSnip`) — **no administrator rights needed**.
- Bundles everything (Python runtime + OCR models). No separate downloads.
- Windows SmartScreen may warn *"Unknown publisher"* (the build isn't code-signed) → **More info → Run anyway**.

After installing, launch TransSnip, open **Settings** (`Ctrl+Alt+S` or double-click the tray icon), pick a provider, and you're ready. Google Translate works with no key; for the LLM providers paste an API key (stored securely in Windows Credential Manager).

## Run from source (developers)

Requires **Python 3.11+** on **Windows**.

```bash
git clone <repo-url>
cd transsnip

python -m venv .venv
.venv\Scripts\activate

# Install the app with the feature extras you want
pip install -e ".[dev,ocr,translate,tts,learning]"

# Fetch the OCR models once (gitignored — they're large binary blobs)
python scripts/fetch_models.py

# Run
python -m transsnip
```

API keys are read from Windows Credential Manager (via `keyring`) — set them in **Settings → Translation**, never in a file.

### Build the installer

```bash
python scripts/fetch_models.py                  # ensure models are present
pyinstaller --noconfirm --clean TransSnip.spec  # → dist\TransSnip\ (onedir)
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss  # → dist\installer\TransSnip-Setup.exe
```

Details and the gotchas (bundling models + the wordninja wordlist) are in [`docs/mentor/42-build-packaging.md`](docs/mentor/42-build-packaging.md).

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
├─ ocr/                # Windows OCR + RapidOCR (PP-OCRv5), segmentation, model paths
├─ translate/          # provider clients (google_free / gemini / claude / openrouter) + cache + registry
├─ linguistic/         # IPA generation + per-word breakdown
├─ tts/                # Edge TTS + Windows SAPI fallback
├─ display/            # floating popup, inline overlay, subtitle bar
├─ modes/              # video subtitle pipeline (region/fullscreen wired in app.py)
├─ hotkeys/            # global hotkey manager
├─ tray/               # system tray icon + menu
├─ ui/                 # settings window, theme, icons, atoms
└─ config/             # pydantic settings, keyring store, history

docs/mentor/           # step-by-step learning docs (Vietnamese) — see below
scripts/fetch_models.py
tests/                 # pytest suite (pure-logic units)
TransSnip.spec         # PyInstaller spec
installer.iss          # Inno Setup script
```

## Learning docs

This project is built to be learned from. [`docs/mentor/`](docs/mentor/) contains step-by-step, mentor-style guides (in Vietnamese) covering every subsystem — from screen capture and OCR to async Qt, caching, packaging and a real debugging postmortem. Start at [`docs/mentor/README.md`](docs/mentor/README.md).

## Tech stack

Python 3.11+ · PySide6 (Qt6) · mss · winsdk / RapidOCR (ONNX Runtime) · edge-tts · pydantic · keyring · PyInstaller + Inno Setup.

## License

MIT
