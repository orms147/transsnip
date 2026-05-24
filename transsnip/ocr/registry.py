from __future__ import annotations

import logging

from PIL import Image

from transsnip.ocr.base import OCREngine, OCRError, OCRResult
from transsnip.ocr.rapid_ocr import RapidOCREngine
from transsnip.ocr.windows_ocr import WindowsOCR

log = logging.getLogger(__name__)


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
                if supported and lang not in supported:
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
