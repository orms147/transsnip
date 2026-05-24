from __future__ import annotations

import asyncio
import io
import logging
import sys

from PIL import Image, ImageEnhance, ImageFilter

from transsnip.ocr.base import OCRBlock, OCREngine, OCRError, OCRResult, _join_blocks_smart

log = logging.getLogger(__name__)

# Minimum image width fed to Windows OCR. CJK glyphs need ~18-22px tall to
# recognize reliably; on a 1.5x DPI capture of dense Discord/Slack text the
# raw char height is only 12-15px, which causes the engine to silently drop
# whole lines. Upscaling the image before recognition recovers them.
_OCR_TARGET_WIDTH = 2000


def _preprocess(image: Image.Image) -> Image.Image:
    """Upscale + light enhancement so Windows OCR sees crisper glyph boundaries.

    Only upscales (never downscales) — large captures are already fine. Sharpen
    helps anti-aliased web fonts; the 1.3x contrast bump separates faint strokes
    from the background, which matters for the thin / dense areas where bullet
    lists and small punctuation otherwise vanish from the result.
    """
    w, h = image.size
    if w < _OCR_TARGET_WIDTH:
        scale = _OCR_TARGET_WIDTH / w
        image = image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    image = image.filter(ImageFilter.SHARPEN)
    image = ImageEnhance.Contrast(image).enhance(1.3)
    return image


class WindowsOCR(OCREngine):
    """OCR via the built-in Windows.Media.Ocr API (free, no model download).

    Accuracy is solid for Latin scripts and most installed language packs (CJK,
    Vietnamese with diacritics, etc.). For languages not pre-installed on the
    host machine, `recognize()` falls back to `OCRError` so the pipeline can try
    the next engine.

    Language packs install via Windows Settings → Time & Language → Languages →
    Add a language (toggle "Optical character recognition" optional feature).
    """

    name = "windows"

    def __init__(self) -> None:
        self._import_ok = self._try_import()

    @staticmethod
    def _try_import() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winsdk.windows.media.ocr  # noqa: F401
            return True
        except ImportError:
            log.warning("winsdk not installed — Windows OCR disabled. Run: pip install winsdk")
            return False

    def is_available(self) -> bool:
        return self._import_ok

    def supported_languages(self) -> set[str]:
        if not self._import_ok:
            return set()
        from winsdk.windows.media.ocr import OcrEngine
        return {lang.language_tag for lang in OcrEngine.available_recognizer_languages}

    def recognize(self, image: Image.Image, lang: str | None = None) -> OCRResult:
        if not self._import_ok:
            raise OCRError("winsdk not installed")
        try:
            return asyncio.run(self._recognize_async(image, lang))
        except OCRError:
            raise
        except Exception as exc:  # winsdk raises various OSError / RuntimeError types
            raise OCRError(f"Windows OCR failed: {exc}") from exc

    async def _recognize_async(self, image: Image.Image, lang_tag: str | None) -> OCRResult:
        from winsdk.windows.globalization import Language
        from winsdk.windows.media.ocr import OcrEngine

        if not lang_tag:
            # Use the user's system language preferences — works correctly for
            # Vietnamese users without forcing them into Settings.
            engine = OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                # User profile didn't yield an OCR-capable language → fall back to en.
                engine = OcrEngine.try_create_from_language(Language("en"))
            if engine is None:
                raise OCRError(
                    "Không tạo được Windows OCR engine. Cài language pack qua "
                    "Settings → Time & Language → Languages → Optical character recognition."
                )
        else:
            language = Language(lang_tag)
            if not OcrEngine.is_language_supported(language):
                installed = sorted(
                    lang.language_tag for lang in OcrEngine.available_recognizer_languages
                )
                raise OCRError(
                    f"Windows OCR pack '{lang_tag}' chưa cài. "
                    f"Đang có: {installed or '(none)'}. "
                    f"Cách cài: Windows Settings → Time & Language → Languages → "
                    f"chọn ngôn ngữ → Options → bật 'Optical character recognition' "
                    f"trong Optional features. RapidOCR fallback sẽ tự kick in."
                )
            engine = OcrEngine.try_create_from_language(language)
            if engine is None:
                raise OCRError(f"Failed to create OcrEngine for '{lang_tag}'")

        bitmap = await self._pil_to_software_bitmap(_preprocess(image))
        result = await engine.recognize_async(bitmap)

        # Emit ONE block per detected line, with the words within each line
        # already joined via the CJK-aware joiner. This preserves Windows OCR's
        # own line detection — re-grouping words by y-coordinate downstream
        # would mistakenly merge adjacent short lines (e.g. two bullet items
        # whose y-centers fall within tolerance).
        blocks: list[OCRBlock] = []
        for line in result.lines or []:
            words = list(line.words or [])
            if not words:
                continue
            texts: list[str] = []
            xs: list[int] = []
            ys: list[int] = []
            x_rights: list[int] = []
            y_bots: list[int] = []
            for word in words:
                rect = word.bounding_rect
                texts.append(word.text or "")
                xs.append(int(rect.x))
                ys.append(int(rect.y))
                x_rights.append(int(rect.x + rect.width))
                y_bots.append(int(rect.y + rect.height))
            line_text = _join_blocks_smart(texts).strip()
            if not line_text:
                continue
            x_min, y_min = min(xs), min(ys)
            x_max, y_max = max(x_rights), max(y_bots)
            blocks.append(
                OCRBlock(
                    text=line_text,
                    bbox=(x_min, y_min, x_max - x_min, y_max - y_min),
                )
            )
        log.debug(
            "Windows OCR %s: %d lines, %d chars total",
            lang_tag, len(blocks), sum(len(b.text) for b in blocks),
        )
        # Per-line dump (debug only) — invaluable when diagnosing "OCR missed
        # this line": shows whether the engine returned the line at all, and
        # at what bbox, so we can tell engine-side drops from downstream
        # grouping/join issues.
        if log.isEnabledFor(logging.DEBUG):
            for i, b in enumerate(blocks):
                log.debug("  block[%d] bbox=%s text=%r", i, b.bbox, b.text)
        return OCRResult(engine=self.name, blocks=blocks)

    @staticmethod
    async def _pil_to_software_bitmap(image: Image.Image):
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        # Encode the PIL image to PNG bytes, then let the Windows runtime decoder
        # turn those bytes into a SoftwareBitmap. This avoids manually wrangling
        # pixel formats / strides.
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        # `write_bytes` requires a bytes-like object (bytes / bytearray / memoryview),
        # not a list. The PNG payload is already `bytes`, so pass it straight through.
        writer.write_bytes(png_bytes)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)

        decoder = await BitmapDecoder.create_async(stream)
        return await decoder.get_software_bitmap_async()
