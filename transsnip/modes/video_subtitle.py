"""Video subtitle mode — live OCR + translate of a fixed screen region.

Flow: user draws the subtitle region once; a background pipeline then captures
that region, and only when something actually changes does it OCR + translate
and push the result to the floating `SubtitleBar`.

Two cheap gates keep it from hammering the CPU / translation API (see
`utils/image.py`):
  1. frame-diff  → skip OCR entirely on unchanged frames
  2. text-similarity → skip translate when OCR returns the same line

Why TWO threads (capture+OCR, and translate):
  A network translate call takes ~0.5-2s. If it ran inline in the capture loop,
  no new frames would be checked during that wait, so on fast dialogue the
  displayed translation falls further and further behind (a growing backlog).
  Instead the capture loop runs continuously and just *hands off* the latest
  detected line to a separate translate worker. The worker always picks the
  MOST RECENT pending line (coalescing — intermediate lines are dropped), so
  lag is bounded to roughly one translation instead of accumulating.

Capture gets an explicit `dpr` so the worker thread never calls QGuiApplication
(Qt GUI calls off the main thread are unsafe).
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QRect, QThread, Signal

from transsnip.capture.screen import capture_rect
from transsnip.ocr.base import OCRError
from transsnip.ocr.registry import OCRPipeline
from transsnip.translate.base import TranslationContext, TranslationError
from transsnip.translate.registry import TranslationPipeline
from transsnip.utils.image import frame_difference, text_similarity

log = logging.getLogger(__name__)

_POLL_MS = 200            # capture cadence (OCR usually dominates this anyway)
_IDLE_MS = 40            # translate worker idle poll when nothing pending
_FRAME_DIFF_THRESH = 0.012  # below → frame unchanged, skip OCR
_TEXT_SIM_THRESH = 0.90     # ≥ → same line as last, skip translate


class _CaptureLoop(QThread):
    """Capture → frame-diff → OCR. Emits each NEW subtitle line (never blocks
    on translation)."""

    new_source = Signal(str)

    def __init__(self, region: QRect, dpr: float, ocr: OCRPipeline, ctx: TranslationContext) -> None:
        super().__init__()
        self._region = region
        self._dpr = dpr
        self._ocr = ocr
        self._ctx = ctx
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        prev_frame = None
        last_src = ""
        while self._running:
            try:
                frame = capture_rect(self._region, dpr=self._dpr)
            except Exception as exc:  # noqa: BLE001 — capture must not kill the loop
                log.debug("subtitle capture failed: %s", exc)
                self.msleep(400)
                continue

            if prev_frame is not None and frame_difference(frame, prev_frame) < _FRAME_DIFF_THRESH:
                self.msleep(_POLL_MS)
                continue
            prev_frame = frame

            try:
                ocr_result = self._ocr.recognize(frame, self._ctx.source_lang)
            except (OCRError, Exception) as exc:  # noqa: BLE001
                log.debug("subtitle OCR skip: %s", exc)
                self.msleep(_POLL_MS)
                continue

            src = ocr_result.text.strip()
            if not src or text_similarity(src, last_src) >= _TEXT_SIM_THRESH:
                # Subtitle blank/unchanged — keep the last line on screen.
                self.msleep(_POLL_MS)
                continue
            last_src = src
            self.new_source.emit(src)   # hand off; do NOT wait for translation
            self.msleep(_POLL_MS)


class _TranslateWorker(QThread):
    """Coalescing translator: always translates the LATEST submitted line,
    dropping any intermediate ones queued while it was busy."""

    text_ready = Signal(str)

    def __init__(self, translator: TranslationPipeline, ctx: TranslationContext) -> None:
        super().__init__()
        self._translator = translator
        self._ctx = ctx
        self._lock = threading.Lock()
        self._pending: str | None = None
        self._running = True

    def submit(self, src: str) -> None:
        # Overwrite — only the most recent line matters (coalesce).
        with self._lock:
            self._pending = src

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        last_done: str | None = None
        while self._running:
            with self._lock:
                src = self._pending
                self._pending = None
            if src is None or src == last_done:
                self.msleep(_IDLE_MS)
                continue
            try:
                result = self._translator.translate(src, self._ctx)
            except (TranslationError, Exception) as exc:  # noqa: BLE001
                log.debug("subtitle translate skip: %s", exc)
                continue  # transient — the next new line will try again
            last_done = src
            if self._running:
                self.text_ready.emit(result.translated_text)


class _PipelineControllerBase(QObject):
    """Shared stop-safety for the subtitle pipeline controllers (video/audio).

    Dropping the last Python ref to a RUNNING QThread deletes the C++ object
    and hard-aborts the process ("QThread: Destroyed while thread is still
    running"). A pipeline thread can easily overrun the stop wait — a
    translate call hanging on the network, or the ASR loop mid multi-minute
    Whisper model download — so `_retire` parks such threads in `_zombies`
    (keeping them alive, signals detached) until `finished` fires.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._zombies: list[QThread] = []

    def _retire(self, thread) -> None:
        if thread is None:
            return
        # A parked thread must not keep feeding the UI / a retired sibling.
        for sig_name in ("new_source", "status", "error", "text_ready"):
            sig = getattr(thread, sig_name, None)
            if sig is not None:
                try:
                    sig.disconnect()
                except RuntimeError:
                    pass  # already had no receivers
        self._zombies.append(thread)
        thread.finished.connect(lambda t=thread: self._release_zombie(t))
        thread.stop()
        if thread.wait(2000):
            self._release_zombie(thread)
        else:
            log.warning("%s still running after stop — parked until it finishes",
                        type(thread).__name__)

    def _release_zombie(self, thread: QThread) -> None:
        try:
            self._zombies.remove(thread)
        except ValueError:
            pass


class VideoSubtitleController(_PipelineControllerBase):
    """Owns the capture loop + translate worker; re-emits their events on the
    main thread.

    `start()` spins up a fresh pair (stopping any prior); `stop()` halts both
    and waits so a subsequent start is clean.
    """

    text_ready = Signal(str)
    status = Signal(str)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._capture: _CaptureLoop | None = None
        self._translator_worker: _TranslateWorker | None = None

    def is_running(self) -> bool:
        return self._capture is not None and self._capture.isRunning()

    def start(
        self,
        region: QRect,
        dpr: float,
        ocr: OCRPipeline,
        translator: TranslationPipeline,
        ctx: TranslationContext,
    ) -> None:
        self.stop()
        worker = _TranslateWorker(translator, ctx)
        worker.text_ready.connect(self.text_ready)
        capture = _CaptureLoop(region, dpr, ocr, ctx)
        # new_source → worker.submit runs on the controller's (main) thread;
        # the lock guards the handoff to the worker thread.
        capture.new_source.connect(worker.submit)
        self._translator_worker = worker
        self._capture = capture
        worker.start()
        capture.start()
        log.info("Video subtitle pipeline started on region %s (dpr=%.2f)", region, dpr)

    def stop(self) -> None:
        if self._capture is None and self._translator_worker is None:
            return
        for t in (self._capture, self._translator_worker):
            self._retire(t)
        self._capture = None
        self._translator_worker = None
        log.info("Video subtitle pipeline stopped")
        self.stopped.emit()
