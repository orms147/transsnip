from __future__ import annotations

import logging

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Signal

from transsnip.ocr.base import OCRError, OCRResult
from transsnip.ocr.registry import OCRPipeline

log = logging.getLogger(__name__)


class OCRWorkerSignals(QObject):
    """Owned by an OCRWorker; carries the worker's result back to the main thread.

    Signals are a QObject feature, but QRunnable is not a QObject — so we keep the
    signal carrier as a separate object that callers can `connect()` to before
    submitting the worker.
    """

    done = Signal(object)  # OCRResult
    failed = Signal(str)


class OCRWorker(QRunnable):
    """Runs `pipeline.recognize(image, lang)` on a worker thread.

    Use `QThreadPool.globalInstance().start(worker)` to submit. Connect to
    `worker.signals.done` / `worker.signals.failed` before starting.
    """

    def __init__(self, image: Image.Image, lang: str | None, pipeline: OCRPipeline) -> None:
        super().__init__()
        self._image = image
        self._lang = lang
        self._pipeline = pipeline
        self.signals = OCRWorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._pipeline.recognize(self._image, self._lang)
        except OCRError as exc:
            log.warning("OCR pipeline failed: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — worker must never raise
            log.exception("Unexpected OCR error")
            self.signals.failed.emit(f"Unexpected: {exc}")
            return
        self.signals.done.emit(result)
