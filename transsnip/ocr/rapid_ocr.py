from __future__ import annotations

import logging
from typing import Any

from PIL import Image

from transsnip.ocr.base import OCRBlock, OCREngine, OCRError, OCRResult

log = logging.getLogger(__name__)


class RapidOCREngine(OCREngine):
    """OCR via RapidOCR (PaddleOCR models served by ONNX Runtime).

    Why this engine over full PaddleOCR:
    - ~12x smaller install (50MB vs 600MB) — same model accuracy
    - No PaddlePaddle framework / no CUDA dependency
    - Cold start ~3s (lazy-loaded once per process)
    - ~500-1500ms per recognize on CPU, ~200MB RAM resident

    Multilingual: the default RapidOCR model handles English, Vietnamese, Chinese
    (Simplified + Traditional), Japanese, Korean and a few others within a single
    model — `lang` is largely advisory.
    """

    name = "rapid"

    def __init__(self) -> None:
        self._engine: Any | None = None
        self._import_ok = self._try_import()

    @staticmethod
    def _try_import() -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except ImportError:
            log.warning(
                "rapidocr_onnxruntime not installed — RapidOCR disabled. "
                "Run: pip install rapidocr-onnxruntime"
            )
            return False

    def is_available(self) -> bool:
        return self._import_ok

    def supported_languages(self) -> set[str]:
        if not self._import_ok:
            return set()
        # The bundled multilingual model recognizes these; we return BCP-47 tags so
        # the pipeline's language filter doesn't reject this engine. PaddleOCR's own
        # codes (e.g. "ch", "japan") are an internal detail.
        return {"en", "vi", "zh-Hans", "zh-Hant", "ja", "ko", "th", "ru", "ar", "fr", "de", "es"}

    def _ensure_loaded(self) -> None:
        if self._engine is not None:
            return
        from rapidocr_onnxruntime import RapidOCR

        log.info("Loading RapidOCR model (first call ~3s, cached afterwards)...")
        self._engine = RapidOCR()
        log.info("RapidOCR ready")

    def recognize(self, image: Image.Image, lang: str | None = None) -> OCRResult:
        if not self._import_ok:
            raise OCRError("rapidocr_onnxruntime not installed")
        self._ensure_loaded()

        try:
            import numpy as np

            arr = np.array(image.convert("RGB"))
            raw_result, _elapse = self._engine(arr)
        except Exception as exc:  # noqa: BLE001
            raise OCRError(f"RapidOCR failed: {exc}") from exc

        if not raw_result:
            return OCRResult(engine=self.name, blocks=[])

        blocks: list[OCRBlock] = []
        for entry in raw_result:
            # RapidOCR yields [box, text, score]. Box is 4 corner points (top-left,
            # top-right, bottom-right, bottom-left), each as [x, y].
            box, text, score = entry[0], entry[1], entry[2]
            text = (text or "").strip()
            if not text:
                continue
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            x_min, y_min = int(min(xs)), int(min(ys))
            x_max, y_max = int(max(xs)), int(max(ys))
            blocks.append(
                OCRBlock(
                    text=text,
                    bbox=(x_min, y_min, x_max - x_min, y_max - y_min),
                    confidence=float(score),
                )
            )
        log.debug("RapidOCR: %d blocks", len(blocks))
        return OCRResult(engine=self.name, blocks=blocks)
