from __future__ import annotations

import importlib.util
import logging
import os
import threading
from typing import Any

from PIL import Image

from transsnip.ocr.base import OCRBlock, OCREngine, OCRError, OCRResult
from transsnip.ocr.models import (
    DET_MODEL,
    DET_TYPE,
    DET_VERSION,
    SUPPORTED_LANGS,
    RecModel,
    models_dir,
    rec_for_lang,
)

log = logging.getLogger(__name__)


class RapidOCREngine(OCREngine):
    """OCR via RapidOCR (PaddleOCR PP-OCRv6/v5 models served by ONNX Runtime).

    This is the bundled, OS-independent fallback behind Windows OCR. Unlike
    Windows OCR — which can only read languages whose pack is installed on the
    host — RapidOCR ships its models *inside the app* (`resources/models/`),
    so it works on a bare machine with zero configuration.

    Which model serves which language (and why v6 small) is in `ocr/models.py`.

    A separate `rapidocr.RapidOCR` instance is built per script family (each
    bundles its own det + rec) and cached for the process lifetime. Measured
    cold start: ~550 ms to import rapidocr + onnxruntime (~115 MB RSS), then
    ~220 ms to build a family's sessions; warm calls are ~20-100 ms per region.
    Neither is paid at app start: the SDK is only probed (not imported) here,
    and `warm_up()` pre-builds the family in the background when this engine
    is the one that will serve the configured source language.
    """

    name = "rapid"

    def __init__(self) -> None:
        # One engine per recognition family ("multi" / "korean"),
        # built lazily on first use of that family.
        self._engines: dict[str, Any] = {}
        # Guards lazy construction: a background warm-up and a user's first
        # snip can race to build the same family (doubling the ~220 ms build
        # and the memory). Recognition itself runs outside the lock —
        # onnxruntime sessions are safe to run concurrently.
        self._build_lock = threading.Lock()
        self._import_ok = self._try_import()

    @staticmethod
    def _try_import() -> bool:
        # find_spec, not import: importing rapidocr + onnxruntime costs ~0.5 s
        # and ~115 MB at app start, even on machines where Windows OCR serves
        # every capture and this fallback never runs.
        ok = all(importlib.util.find_spec(m) is not None for m in ("rapidocr", "onnxruntime"))
        if not ok:
            log.warning(
                "rapidocr/onnxruntime not installed — RapidOCR disabled. "
                "Run: pip install rapidocr onnxruntime"
            )
        return ok

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
        cached = self._engines.get(rec.family)
        if cached is not None:
            return cached
        with self._build_lock:
            cached = self._engines.get(rec.family)
            if cached is None:
                cached = self._engines[rec.family] = self._build_engine(rec)
        return cached

    def _build_engine(self, rec: RecModel) -> Any:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        mdir = models_dir()
        det_path = mdir / DET_MODEL
        rec_path = mdir / rec.model
        dict_path = mdir / rec.dict_file if rec.dict_file else None
        for p in (det_path, rec_path, dict_path):
            if p is None:
                continue
            if not p.exists():
                raise OCRError(
                    f"Thiếu model OCR bundled: {p.name}. Chạy "
                    "`python scripts/fetch_models.py` để tải về resources/models/."
                )

        # engine_type defaults to onnxruntime (see rapidocr config.yaml) — leave
        # it unset so we don't have to import yet another enum.
        params: dict[str, Any] = {
            # Runtime: measured with scripts/ocr_bench.py cases (2 runs, same
            # CER): arena on + ≤8 intra-op threads is ~25% faster overall than
            # the defaults (arena off, all cores) — subtitles 50 → 35 ms,
            # 1080p page 420 → 290 ms. All 32 threads of a big CPU spend more
            # time coordinating than computing on these small inputs, and the
            # cap leaves cores for the video player in subtitle mode.
            "EngineConfig.onnxruntime.enable_cpu_mem_arena": True,
            "EngineConfig.onnxruntime.intra_op_num_threads": min(8, os.cpu_count() or 4),
            "Global.use_cls": False,
            "Det.model_path": str(det_path),
            "Det.ocr_version": OCRVersion(DET_VERSION),
            "Det.model_type": ModelType(DET_TYPE),
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
            "Rec.ocr_version": OCRVersion(rec.ocr_version),
            "Rec.model_type": ModelType(rec.model_type),
            "Rec.lang_type": LangRec(rec.lang_type),
        }
        if dict_path is not None:
            params["Rec.rec_keys_path"] = str(dict_path)
        engine = RapidOCR(params=params)
        log.info("RapidOCR engine ready for family '%s' (%s)", rec.family, rec.model)
        return engine

    def warm_up(self, lang: str | None = None) -> None:
        """Build the family for `lang` and run one tiny inference.

        One real call matters: sessions/kernels initialise lazily, so building
        alone leaves part of the cold cost on the user's first snip.
        """
        if not self.is_available():
            return
        from PIL import ImageDraw

        img = Image.new("RGB", (160, 40), "white")
        ImageDraw.Draw(img).text((8, 12), "Warm up 123", fill="black")
        self.recognize(img, lang)

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
        except Exception as exc:
            raise OCRError(f"RapidOCR failed: {exc}") from exc

        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or txts is None or len(txts) == 0:
            log.debug(
                "RapidOCR (%s) no detections on %dx%d image",
                rec.family, image.width, image.height,
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
        log.debug("RapidOCR (%s): %d blocks", rec.family, len(blocks))
        return OCRResult(engine=self.name, blocks=blocks)
