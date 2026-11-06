from __future__ import annotations

import asyncio
import logging
import sys

from PIL import Image, ImageEnhance, ImageFilter

from transsnip.ocr.base import OCRBlock, OCREngine, OCRError, OCRResult, _join_blocks_smart
from transsnip.utils.win_dll import preload_msvcp140

log = logging.getLogger(__name__)

# Minimum image width fed to Windows OCR. CJK glyphs need ~18-22px tall to
# recognize reliably; on a 1.5x DPI capture of dense Discord/Slack text the
# raw char height is only 12-15px, which causes the engine to silently drop
# whole lines. Upscaling the image before recognition recovers them.
_OCR_TARGET_WIDTH = 2000
# ...but never by more than this. The uncapped width rule blew a 330px-wide
# region up 6x (2000x3000 px, ~310 ms) and a 200px UI snippet ~10x, and the
# over-upscaled glyphs actually OCR *worse* (doubled letters on subtitles:
# "II never said…"). Measured with scripts/ocr_bench.py: capping at 2x cut
# mean CER 2.4% → 1.2% and total latency 855 → 324 ms, with no loss on
# 10-12 px text; 1.5x and 2.5x were both worse.
_MAX_UPSCALE = 2.0


def _resolve_installed_tag(requested: str) -> str | None:
    """Map a Settings-supplied BCP-47 tag like 'en' or 'ja' to a tag actually
    present in `OcrEngine.available_recognizer_languages` (typically 'en-US',
    'ja-JP', 'vi-VN'). Returns None if no installed pack matches.

    Tries an exact match first, then primary-subtag match. Returning the
    installed tag verbatim (rather than the user's request) avoids relying
    on `is_language_supported(Language('en'))`, which is inconsistent across
    Windows builds.
    """
    if not requested:
        return None
    try:
        from winrt.windows.media.ocr import OcrEngine
    except ImportError:
        return None
    requested_lc = requested.lower()
    requested_primary = requested_lc.split("-")[0]
    available = [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    for tag in available:
        if tag.lower() == requested_lc:
            return tag
    for tag in available:
        if tag.lower().split("-")[0] == requested_primary:
            return tag
    return None


def _preprocess(image: Image.Image) -> Image.Image:
    """Upscale + light enhancement so Windows OCR sees crisper glyph boundaries.

    Only upscales (never downscales) — large captures are already fine. Sharpen
    helps anti-aliased web fonts; the 1.3x contrast bump separates faint strokes
    from the background, which matters for the thin / dense areas where bullet
    lists and small punctuation otherwise vanish from the result.
    """
    w, h = image.size
    if w < _OCR_TARGET_WIDTH:
        scale = min(_OCR_TARGET_WIDTH / w, _MAX_UPSCALE)
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
        # Must precede the first winrt import — see utils/win_dll.py (winrt's
        # bundled msvcp140 otherwise breaks onnxruntime / RapidOCR later).
        preload_msvcp140()
        try:
            import winrt.windows.media.ocr  # noqa: F401
            return True
        except ImportError:
            log.warning(
                "winrt packages not installed — Windows OCR disabled. "
                "Run: pip install transsnip[ocr]"
            )
            return False

    def is_available(self) -> bool:
        return self._import_ok

    def supported_languages(self) -> set[str]:
        if not self._import_ok:
            return set()
        from winrt.windows.media.ocr import OcrEngine
        return {lang.language_tag for lang in OcrEngine.available_recognizer_languages}

    def recognize(self, image: Image.Image, lang: str | None = None) -> OCRResult:
        if not self._import_ok:
            raise OCRError("winrt (Windows OCR) not installed")
        try:
            return asyncio.run(self._recognize_async(image, lang))
        except OCRError:
            raise
        except Exception as exc:  # winrt raises various OSError / RuntimeError types
            raise OCRError(f"Windows OCR failed: {exc}") from exc

    @staticmethod
    def _list_installed_tags() -> list[str]:
        from winrt.windows.media.ocr import OcrEngine
        return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]

    async def _recognize_async(self, image: Image.Image, lang_tag: str | None) -> OCRResult:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        # Build the list of (tag, engine) candidates to try on this image.
        #
        # A Windows OcrEngine is bound to EXACTLY ONE language — it reads only
        # that script and silently returns garbage (or nothing) for any other.
        # So "auto-detect" can't be a single engine: the old code used
        # try_create_from_user_profile_languages(), which on most machines
        # resolves to en-US and therefore only ever read Latin text — Japanese /
        # Chinese / Korean captures came back empty or as junk. Instead, when no
        # source language is pinned we run EVERY installed pack and keep whichever
        # recognizes the most text. That's a cheap, reliable language auto-detect
        # across the packs the user actually has (typically 1-3 → 1-3 passes).
        candidates: list[tuple[str, object]] = []
        if lang_tag:
            # Resolve to an actually-installed pack: user typically stores
            # primary subtags in Settings ("en", "ja"), Windows reports the
            # regional ones ("en-US", "ja-JP"). is_language_supported("en")
            # is true on some builds and false on others — picking from
            # available_recognizer_languages is more reliable across machines.
            resolved_tag = _resolve_installed_tag(lang_tag)
            if resolved_tag is None:
                installed = sorted(self._list_installed_tags())
                raise OCRError(
                    f"Windows OCR pack cho '{lang_tag}' chưa cài. "
                    f"Đang có: {installed or '(none)'}. "
                    f"Cách cài: Windows Settings → Time & Language → Languages → "
                    f"chọn ngôn ngữ → Options → bật 'Optical character recognition' "
                    f"trong Optional features. RapidOCR fallback sẽ tự kick in."
                )
            engine = OcrEngine.try_create_from_language(Language(resolved_tag))
            if engine is None:
                raise OCRError(f"Failed to create OcrEngine for '{resolved_tag}'")
            candidates.append((resolved_tag, engine))
        else:
            for tag in self._list_installed_tags():
                engine = OcrEngine.try_create_from_language(Language(tag))
                if engine is not None:
                    candidates.append((tag, engine))
            if not candidates:
                raise OCRError(
                    "Không tạo được Windows OCR engine (chưa có language pack nào "
                    "hỗ trợ OCR). Cài qua Settings → Time & Language → Languages → "
                    "Optical character recognition. RapidOCR fallback sẽ tự kick in."
                )

        preprocessed = _preprocess(image)
        # _preprocess upscales the image (≥2000px wide) to help recognition,
        # so winrt's bounding rects come back in PREPROCESSED-image coords.
        # The caller passed `image` and expects bboxes relative to THAT —
        # otherwise downstream features (fullscreen overlay placing boxes on
        # screen) would draw at the wrong location. Scale every coordinate
        # back by the same ratio we upscaled by.
        scale = preprocessed.width / image.width if image.width else 1.0
        bitmap = self._pil_to_software_bitmap(preprocessed)

        # Recognize with each candidate pack and keep the richest result.
        # Score = total recognized character count: on a Japanese capture the
        # ja pack returns dozens of chars while the en pack returns a handful of
        # junk, so ja wins; on an English capture the reverse holds. The bitmap
        # is reused across passes (recognition doesn't consume it).
        best_blocks: list[OCRBlock] = []
        best_tag: str | None = None
        best_score = -1
        for tag, engine in candidates:
            result = await engine.recognize_async(bitmap)  # type: ignore[attr-defined]
            blocks = self._blocks_from_result(result, scale)
            score = sum(len(b.text) for b in blocks)
            log.debug("Windows OCR pack %s: %d blocks, score=%d", tag, len(blocks), score)
            if score > best_score:
                best_score, best_blocks, best_tag = score, blocks, tag

        log.debug(
            "Windows OCR picked %s: %d lines, %d chars total (lang_tag=%s)",
            best_tag, len(best_blocks), best_score, lang_tag,
        )
        # Per-line dump (debug only) — invaluable when diagnosing "OCR missed
        # this line": shows whether the engine returned the line at all, and
        # at what bbox, so we can tell engine-side drops from downstream
        # grouping/join issues.
        if log.isEnabledFor(logging.DEBUG):
            for i, b in enumerate(best_blocks):
                log.debug("  block[%d] bbox=%s text=%r", i, b.bbox, b.text)
        return OCRResult(engine=self.name, blocks=best_blocks)

    @staticmethod
    def _blocks_from_result(result, scale: float) -> list[OCRBlock]:
        """Convert a winrt OcrResult into our OCRBlock list.

        Emit ONE block per detected line, with the words within each line
        already joined via the CJK-aware joiner. This preserves Windows OCR's
        own line detection — re-grouping words by y-coordinate downstream
        would mistakenly merge adjacent short lines (e.g. two bullet items
        whose y-centers fall within tolerance). Coordinates are divided by
        `scale` to map back from the upscaled preprocessing image to the
        caller's original image space.
        """
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
                # Scale each corner back to original image coords.
                xs.append(int(rect.x / scale))
                ys.append(int(rect.y / scale))
                x_rights.append(int((rect.x + rect.width) / scale))
                y_bots.append(int((rect.y + rect.height) / scale))
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
        return blocks

    @staticmethod
    def _pil_to_software_bitmap(image: Image.Image):
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap

        # Hand the raw BGRA8 pixels straight to SoftwareBitmap instead of the old
        # PNG encode -> BitmapDecoder round-trip: identical OCR output, ~2.5x
        # cheaper per call (no compression/decompression). BGRA8 is the format
        # OcrEngine accepts natively; tightly-packed rows (stride = 4*width) are
        # what create_copy_from_buffer expects, and pywinrt 3.x accepts any
        # bytes-like object where an IBuffer is required.
        raw = image.convert("RGBA").tobytes("raw", "BGRA")
        return SoftwareBitmap.create_copy_from_buffer(
            raw, BitmapPixelFormat.BGRA8, image.width, image.height
        )
