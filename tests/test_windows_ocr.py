"""Real Windows.Media.Ocr round-trip (skipped off-Windows / without an en pack)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("Windows OCR is Windows-only", allow_module_level=True)

ocr_mod = pytest.importorskip("winrt.windows.media.ocr")
pytest.importorskip("winrt.windows.graphics.imaging")
pytest.importorskip("winrt.windows.globalization")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from transsnip.ocr.windows_ocr import WindowsOCR  # noqa: E402

_FONT = Path(r"C:\Windows\Fonts\arial.ttf")
_HAS_EN = any(
    lang.language_tag.lower().startswith("en")
    for lang in ocr_mod.OcrEngine.available_recognizer_languages
)

pytestmark = [
    pytest.mark.skipif(not _HAS_EN, reason="no English Windows OCR pack installed"),
    pytest.mark.skipif(not _FONT.exists(), reason="arial.ttf not found"),
]


def _render() -> Image.Image:
    img = Image.new("RGB", (900, 220), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(_FONT), 56)
    draw.text((20, 20), "Hello world 123", fill="black", font=font)
    draw.text((20, 120), "Second line here", fill="black", font=font)
    return img


def test_recognize_english_two_lines() -> None:
    img = _render()
    result = WindowsOCR().recognize(img, "en")
    assert result.engine == "windows"
    texts = [b.text for b in result.blocks]
    assert len(texts) == 2, texts
    assert texts[0] == "Hello world 123"
    assert texts[1] == "Second line here"
    # bboxes are de-scaled back to the ORIGINAL (900px) image, not the 2000px
    # preprocessed one.
    for b in result.blocks:
        x, y, w, h = b.bbox
        assert x >= 0 and x + w <= img.width
        assert y >= 0 and y + h <= img.height
    assert result.blocks[0].bbox[1] < result.blocks[1].bbox[1]


def test_auto_language_picks_english() -> None:
    result = WindowsOCR().recognize(_render(), None)
    assert "Hello world 123" in [b.text for b in result.blocks]
