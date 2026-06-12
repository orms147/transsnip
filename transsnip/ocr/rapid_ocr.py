from __future__ import annotations

import logging
from typing import Any

from PIL import Image

from transsnip.ocr.base import OCRBlock, OCREngine, OCRError, OCRResult
from transsnip.ocr.models import (
    DET_MODEL,
    SUPPORTED_LANGS,
    RecModel,
    models_dir,
    rec_for_lang,
)

log = logging.getLogger(__name__)


class RapidOCREngine(OCREngine):
    """OCR via RapidOCR (PaddleOCR PP-OCRv5 models served by ONNX Runtime).

    This is the bundled, OS-independent fallback behind Windows OCR. Unlike
    Windows OCR — which can only read languages whose pack is installed on the
    host — RapidOCR ships its models *inside the app* (`resources/models/`),
    so it works on a bare machine with zero configuration.

    PP-OCRv5 over v4 (the previous bundle):
    - A single `ch` recognition model now spans Simplified/Traditional Chinese,
      Pinyin, English AND Japanese. The old v4 `ch` model dropped Japanese kana
      entirely (it read only the shared Han characters), which is exactly why
      Japanese captures failed before. See `ocr/models.py`.
    - Korean and the 45+ Latin-script languages get their own small models,
      selected per source language by `rec_for_lang()`.

    A separate `rapidocr.RapidOCR` instance is built per script family (each
    bundles its own det + rec) and cached for the process lifetime. Cold start
    is ~1-2s per family on first use; subsequent calls are ~300-800ms on CPU.
    """

    name = "rapid"

    def __init__(self) -> None:
        # One engine per recognition family ("ch" / "korean" / "latin"),
        # built lazily on first use of that family.
        self._engines: dict[str, Any] = {}
        self._import_ok = self._try_import()

    @staticmethod
    def _try_import() -> bool:
        try:
            import rapidocr  # noqa: F401
            return True
        except ImportError:
            log.warning(
                "rapidocr not installed — RapidOCR disabled. Run: pip install rapidocr"
            )
            return False

    def is_available(self) -> bool:
        # Also require the bundled models to be present — a checkout that never
        # ran the model-download step shouldn't advertise this engine.
        return self._import_ok and (models_dir() / DET_MODEL).exists()

    def supported_languages(self) -> set[str]:
        if not self._import_ok:
            return set()
        return set(SUPPORTED_LANGS)

    def _get_engine(self, rec: RecModel) -> Any:
        """Build (or fetch cached) a RapidOCR engine for a recognition family.

        All paths point at the bundled `resources/models/` files so nothing is
        downloaded at runtime — critical for an offline single-exe install. The
        angle classifier is disabled: screen text is upright, and skipping it
        avoids the rare 180° misflip on dense CJK lines while shaving latency.
        """
        cached = self._engines.get(rec.lang_type)
        if cached is not None:
            return cached

        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        mdir = models_dir()
        det_path = mdir / DET_MODEL
        rec_path = mdir / rec.model
        dict_path = mdir / rec.dict_file
        for p in (det_path, rec_path, dict_path):
            if not p.exists():
                raise OCRError(
                    f"Thiếu model OCR bundled: {p.name}. Chạy "
                    "`python scripts/fetch_models.py` để tải về resources/models/."
                )

        # engine_type defaults to onnxruntime (see rapidocr config.yaml) — leave
        # it unset so we don't have to import yet another enum.
        engine = RapidOCR(params={
            "Global.use_cls": False,
            "Det.model_path": str(det_path),
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.MOBILE,
            # CRITICAL for region captures: the default `limit_type: min` /
            # `limit_side_len: 736` upscales the *short* side to 736, which on a
            # wide single-line snippet balloons the image and makes the mobile
            # detector miss almost everything (verified: it returns one stray
            # glyph). `max`/960 instead caps the *long* side at 960 — det then
            # reliably finds the line. rec crops from the original image, so
            # this only affects detection geometry, not text resolution.
            "Det.limit_type": "max",
            "Det.limit_side_len": 960,
            "Rec.model_path": str(rec_path),
            "Rec.rec_keys_path": str(dict_path),
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec(rec.lang_type),
        })
        log.info("RapidOCR engine ready for family '%s' (%s)", rec.lang_type, rec.model)
        self._engines[rec.lang_type] = engine
        return engine

    def recognize(self, image: Image.Image, lang: str | None = None) -> OCRResult:
        if not self._import_ok:
            raise OCRError("rapidocr not installed")

        rec = rec_for_lang(lang)
        engine = self._get_engine(rec)

        # Pass the image at native resolution. Unlike the old v4 path we do NOT
        # pre-upscale here: PP-OCRv5's detector does its own internal resize
        # (capped at 960px on the long side, see `_get_engine`), and stacking
        # our 2000px upscale on top of that produced a double-resize that broke
        # detection. rec then crops from this same image, so boxes already come
        # back in input-image coordinates (no scale-back needed).
        try:
            import numpy as np

            arr = np.array(image.convert("RGB"))
            result = engine(arr)
        except Exception as exc:  # noqa: BLE001
            raise OCRError(f"RapidOCR failed: {exc}") from exc

        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or txts is None or len(txts) == 0:
            log.debug(
                "RapidOCR (%s) no detections on %dx%d image",
                rec.lang_type, image.width, image.height,
            )
            return OCRResult(engine=self.name, blocks=[])

        blocks: list[OCRBlock] = []
        for i, text in enumerate(txts):
            text = (text or "").strip()
            if not text:
                continue
            box = boxes[i]
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            x_min, y_min = int(min(xs)), int(min(ys))
            x_max, y_max = int(max(xs)), int(max(ys))
            confidence = float(scores[i]) if scores is not None and i < len(scores) else 0.0
            blocks.append(
                OCRBlock(
                    text=text,
                    bbox=(x_min, y_min, x_max - x_min, y_max - y_min),
                    confidence=confidence,
                )
            )
        log.debug("RapidOCR (%s): %d blocks", rec.lang_type, len(blocks))
        return OCRResult(engine=self.name, blocks=blocks)
