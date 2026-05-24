from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Signal

from transsnip.translate.base import TranslationContext, TranslationError
from transsnip.translate.registry import TranslationPipeline

if TYPE_CHECKING:
    from PIL import Image

log = logging.getLogger(__name__)


class TranslationWorkerSignals(QObject):
    """Signal carrier for `TranslationWorker`. See OCR worker for the rationale."""

    done = Signal(object)  # TranslationResult
    failed = Signal(str)


class TranslationWorker(QRunnable):
    """Runs `pipeline.translate(text, ctx)` on a worker thread.

    Submit with `QThreadPool.globalInstance().start(worker)`. Connect to
    `worker.signals.done` / `worker.signals.failed` before starting.
    """

    def __init__(
        self,
        text: str,
        ctx: TranslationContext,
        pipeline: TranslationPipeline,
    ) -> None:
        super().__init__()
        self._text = text
        self._ctx = ctx
        self._pipeline = pipeline
        self.signals = TranslationWorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._pipeline.translate(self._text, self._ctx)
        except TranslationError as exc:
            log.warning("Translation failed: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — worker must never raise
            log.exception("Unexpected translation error")
            self.signals.failed.emit(f"Unexpected: {exc}")
            return
        self.signals.done.emit(result)


class VisionWorker(QRunnable):
    """Runs `pipeline.translate_image(image, ctx)` on a worker thread.

    Used when the active provider supports single-pass image translation (e.g.
    Gemini Vision). Same signal shape as `TranslationWorker` so the
    AppController can route both kinds of result through the same slot.
    """

    def __init__(
        self,
        image: "Image.Image",
        ctx: TranslationContext,
        pipeline: TranslationPipeline,
    ) -> None:
        super().__init__()
        self._image = image
        self._ctx = ctx
        self._pipeline = pipeline
        self.signals = TranslationWorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._pipeline.translate_image(self._image, self._ctx)
        except TranslationError as exc:
            log.warning("Vision translation failed: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        except NotImplementedError as exc:
            log.warning("Provider doesn't support vision: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — worker must never raise
            log.exception("Unexpected vision error")
            self.signals.failed.emit(f"Unexpected: {exc}")
            return
        self.signals.done.emit(result)
