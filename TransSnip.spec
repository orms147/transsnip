# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for TransSnip (onedir bundle).

Build:  pyinstaller --noconfirm --clean TransSnip.spec
Output: dist\\TransSnip\\TransSnip.exe  (ship the whole dist\\TransSnip folder,
        or wrap it with installer.iss to produce TransSnip-Setup.exe)

The tricky bits for this app:
- rapidocr_onnxruntime ships its .onnx models + config YAML as package data;
  collect_all gathers them or RapidOCR crashes at first recognize().
- onnxruntime ships native DLLs that must be collected as binaries.
- winsdk provides the WinRT projection used by the Windows OCR engine.
- keyring resolves its Windows Credential backend via plugin submodules.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

for _pkg in ("rapidocr_onnxruntime", "onnxruntime", "winsdk"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

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
