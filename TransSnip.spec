# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TransSnip (onedir bundle).

Build:  pyinstaller --noconfirm --clean TransSnip.spec
Output: dist\\TransSnip\\TransSnip.exe  (ship the whole dist\\TransSnip folder,
        or wrap it with installer.iss to produce TransSnip-Setup.exe)

The tricky bits for this app:
- rapidocr (3.x) ships its config YAML + bundled dicts as package data;
  collect_all gathers them or RapidOCR crashes at first recognize().
- onnxruntime ships native DLLs that must be collected as binaries.
- The PP-OCRv5 .onnx models + dicts live in resources/models/ (gitignored,
  fetched via scripts/fetch_models.py) — bundle them so the frozen app is
  fully offline. transsnip/ocr/models.py resolves them via sys._MEIPASS.
- winsdk provides the WinRT projection used by the Windows OCR engine.
- keyring resolves its Windows Credential backend via plugin submodules.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

for _pkg in ("rapidocr", "onnxruntime", "winsdk"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# wordninja is a SINGLE-FILE module whose word-frequency list lives in a
# `wordninja/` SUBDIR next to it (it loads `<dir(__file__)>/wordninja/
# wordninja_words.txt.gz`). collect_all can't grab that, so bundle it explicitly
# into a matching `wordninja/` dir — in the frozen app dir(__file__) is the
# bundle root, so this resolves correctly. Without it, English run-on
# segmentation (ocr/segment.py) crashes at runtime.
import os as _os  # noqa: E402

import wordninja as _wn  # noqa: E402

_wn_gz = _os.path.join(
    _os.path.dirname(_os.path.abspath(_wn.__file__)), "wordninja", "wordninja_words.txt.gz"
)
if _os.path.exists(_wn_gz):
    datas.append((_wn_gz, "wordninja"))
hiddenimports.append("wordninja")

# Bundle the PP-OCRv5 model files under resources/models/ → resources/models/
# in the frozen tree (matches models_dir() which joins sys._MEIPASS with that
# relative path). Fails loudly at build time if fetch_models.py wasn't run.
_models = Path("resources/models")
_model_files = list(_models.glob("*.onnx")) + list(_models.glob("*.txt"))
if not _model_files:
    raise SystemExit(
        "resources/models/ is empty — run `python scripts/fetch_models.py` "
        "before building so the OCR models get bundled into the .exe."
    )
datas += [(str(p), "resources/models") for p in _model_files]

# keyring picks its backend (Windows Credential Manager) at runtime via
# entry-point plugins — pull the backend submodules in explicitly.
hiddenimports += collect_submodules("keyring.backends")

a = Analysis(
    ["run_transsnip.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TransSnip",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # tray app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                # set to "assets\\app.ico" once an icon exists
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TransSnip",
)
