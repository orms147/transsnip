from __future__ import annotations

import logging

from PIL import Image

from transsnip.ocr.base import OCREngine, OCRError, OCRResult
from transsnip.ocr.rapid_ocr import RapidOCREngine
from transsnip.ocr.windows_ocr import WindowsOCR

log = logging.getLogger(__name__)


def _lang_matches(requested: str, available: set[str]) -> bool:
    """BCP-47 primary-subtag match.

    Returns True if `requested` matches any tag in `available` either exactly
    (case-insensitive) or by primary subtag. e.g. requested="en" matches
    available={"en-US"}, requested="zh-Hans" matches available={"zh-CN"}
    only by primary subtag "zh".

    Why this matters: Windows OCR reports installed packs in their full
    regional form ("en-US", "ja-JP", "vi-VN"). The Settings combo stores
    primary subtags ("en", "ja", "vi"). Without this normalisation the
    pipeline filters Windows OCR out as if it didn't speak the language
    the user picked.
    """
    requested_lc = requested.lower()
    requested_primary = requested_lc.split("-")[0]
    for tag in available:
        tag_lc = tag.lower()
        if tag_lc == requested_lc:
            return True
        if tag_lc.split("-")[0] == requested_primary:
            return True
    return False


class OCRPipeline:
    """Tries OCR engines in priority order, falling back if one is unavailable or fails.

    "Fails" includes raising OCRError or returning an empty result — both signal that
    we should try the next engine. Only the first engine to produce non-empty text wins.
    """

    def __init__(self, engines: list[OCREngine]) -> None:
        if not engines:
            raise ValueError("OCRPipeline needs at least one engine")
        self._engines = engines

    def engines(self) -> list[OCREngine]:
        return list(self._engines)

    def recognize(self, image: Image.Image, lang: str | None = None) -> OCRResult:
        last_err: Exception | None = None
        attempted: list[str] = []
        for engine in self._engines:
            if not engine.is_available():
                log.debug("Skip unavailable engine: %s", engine.name)
                continue
            if lang:
                supported = engine.supported_languages()
                # Match BCP-47 by PRIMARY SUBTAG so "en" picks up an "en-US"
                # OCR pack (and vice-versa). Without this, Windows OCR — which
                # reports installed packs as "en-US" / "ja-JP" / "vi-VN" —
                # gets filtered out the moment the user picks "en" in
                # Settings, even though the engine handles it just fine.
                if supported and not _lang_matches(lang, supported):
                    log.debug("Engine %s doesn't support '%s'", engine.name, lang)
                    continue
            attempted.append(engine.name)
            try:
                result = engine.recognize(image, lang)
            except OCRError as exc:
                log.warning("Engine %s raised: %s", engine.name, exc)
                last_err = exc
                continue
            if result.text.strip():
                log.info("OCR success via %s (%d blocks)", engine.name, len(result.blocks))
                return result
            log.debug("Engine %s returned empty — trying next", engine.name)
        raise OCRError(
            f"No engine produced text. Tried: {attempted}. Last error: {last_err}"
        )


def default_pipeline() -> OCRPipeline:
    """Build the standard pipeline for TransSnip.

    Order:
      1. Windows OCR — built-in, fast (~200ms), but only handles languages whose
         OCR pack is installed on the host machine.
      2. RapidOCR — bundled multilingual ONNX models. Slower first call (~3s cold
         start) but works for every supported language without OS configuration.

    Each engine is tried in order; the first one to return non-empty text wins.
    """
    return OCRPipeline([WindowsOCR(), RapidOCREngine()])
