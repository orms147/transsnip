"""Regression: Windows OCR (pywinrt) running before RapidOCR must not break
onnxruntime's DLL init. Needs a fresh interpreter — DLL load order is
process-global, so it can't be checked inside the pytest process."""
import importlib.util
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only DLL issue")

_SCRIPT = """
from transsnip.ocr.windows_ocr import WindowsOCR
WindowsOCR()                 # first winrt import, as at app start
import onnxruntime           # what RapidOCR imports on its first use
print("ok")
"""


def test_onnxruntime_loads_after_winrt() -> None:
    # find_spec, not importorskip: importing both here would itself trigger
    # the bug inside the pytest process.
    for mod in ("winrt", "onnxruntime"):
        if importlib.util.find_spec(mod) is None:
            pytest.skip(f"{mod} not installed")
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0 and out.stdout.strip().endswith("ok"), out.stderr[-2000:]
