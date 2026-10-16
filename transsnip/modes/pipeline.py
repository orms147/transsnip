"""Building blocks shared by the live subtitle modes (video OCR + audio ASR).

- `TranslateWorker`: a coalescing translator thread — always translates the
  MOST RECENT submitted line, dropping intermediate ones queued while a slow
  network call was in flight, so subtitle lag stays bounded to about one
  translation instead of growing a backlog.
- `PipelineControllerBase`: stop-safety for controllers that own QThreads.
"""
from __future__ import annotations

import contextlib
import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal

from transsnip.translate.base import TranslationContext
from transsnip.translate.registry import TranslationPipeline

log = logging.getLogger(__name__)

_IDLE_MS = 40            # translate worker idle poll when nothing pending


class TranslateWorker(QThread):
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
            except Exception as exc:  # noqa: BLE001 — TranslationError or worse
                log.debug("subtitle translate skip: %s", exc)
                continue  # transient — the next new line will try again
            last_done = src
            if self._running:
                self.text_ready.emit(result.translated_text)


class PipelineControllerBase(QObject):
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
                with contextlib.suppress(RuntimeError):  # already had no receivers
                    sig.disconnect()
        self._zombies.append(thread)
        thread.finished.connect(lambda t=thread: self._release_zombie(t))
        thread.stop()
        if thread.wait(2000):
            self._release_zombie(thread)
        else:
            log.warning("%s still running after stop — parked until it finishes",
                        type(thread).__name__)

    def _release_zombie(self, thread: QThread) -> None:
        with contextlib.suppress(ValueError):
            self._zombies.remove(thread)
