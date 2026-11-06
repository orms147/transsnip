"""Load the newest MSVC C++ runtime before anything pulls in pywinrt.

The `winrt-runtime` wheel ships its own msvcp140.dll (14.29, VS2019). Whichever
copy loads first is the one the whole process uses, so once a winrt module is
imported, onnxruntime (built against a newer runtime) fails with "DLL load
failed ... initialization routine failed" — i.e. RapidOCR dies the first time
it's needed after Windows OCR has run. Pinning the system's (newer,
backward-compatible) copy first lets both coexist.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_done = False


def preload_msvcp140() -> None:
    """Idempotent; call before the first `import winrt...`. No-op off Windows."""
    global _done
    if _done or sys.platform != "win32":
        return
    _done = True
    candidates = [Path(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "msvcp140.dll")]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # frozen build: PyInstaller may bundle the build machine's copy
        candidates.append(Path(meipass, "msvcp140.dll"))
    for path in candidates:
        if path.exists():
            try:
                ctypes.WinDLL(str(path))
                log.debug("Preloaded %s", path)
                return
            except OSError as exc:
                log.debug("Preload of %s failed: %s", path, exc)
