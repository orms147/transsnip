# TransSnip

Hotkey-driven screen translation for Windows. OCR + multi-provider translation (Claude / OpenAI / Google / DeepL / NLLB) with context-aware results, TTS, and language-learning mode.

> Status: early development.

## Features

- **Hidden by default** — runs in system tray, opened on hotkey
- **Region translate** (Alt+T) — snipping-tool style selection → floating popup
- **Full-screen translate** (Alt+F) — overlay translations on top of source text
- **Video subtitle translate** (Alt+V, Phase 2) — auto-translate subtitle region in real time
- **Multi-provider** — switch between Claude, OpenAI, Google, DeepL, local NLLB in settings
- **Context-aware** — preset prompts and glossary for gaming, programming, medical, etc.
- **3 display modes** — Simple (translation only) / Standard (+ TTS) / Learning (+ IPA + per-word breakdown)

## Quick start (dev)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,ocr,translate,tts,learning]"
python -m transsnip --dev
```

## Project layout

```
transsnip/         # source
  capture/         # screen capture + region selector
  ocr/             # Windows OCR + RapidOCR
  translate/       # provider implementations + cache
  tts/             # Edge TTS + Windows SAPI
  linguistic/      # IPA + word breakdown
  display/         # popup + overlay + subtitle bar
  modes/           # flow orchestration per mode
  ui/              # settings window
.claude/skills/    # project-specific Claude Code skills
tests/
```

## License

MIT
