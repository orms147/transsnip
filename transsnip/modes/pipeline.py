"""Building blocks shared by the live subtitle modes (video OCR + audio ASR).

- `TranslateWorker`: a coalescing translator thread — always translates the
  MOST RECENT submitted line, dropping intermediate ones queued while a slow
  network call was in flight, so subtitle lag stays bounded to about one
  translation instead of growing a backlog. Right for VIDEO subtitles: only
  the line currently on screen matters.
- `OrderedTranslateWorker`: for AUDIO, where every utterance is content —
  translates up to 3 lines concurrently, emits them in spoken order, and only
  drops lines when a backlog builds up.
- `PipelineControllerBase`: stop-safety for controllers that own QThreads.
"""
from __future__ import annotations

import contextlib
import logging
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace

from PySide6.QtCore import QObject, QThread, Signal

from transsnip.linguistic.langdetect import effective_source
from transsnip.translate.base import TranslationContext
from transsnip.translate.registry import TranslationPipeline, is_transient_translation_error

log = logging.getLogger(__name__)

_IDLE_MS = 40            # translate worker idle poll when nothing pending
_PARALLEL = 3            # ordered worker: concurrent translation requests
_MAX_BACKLOG = 4         # ordered worker: queued-not-started lines kept
_RETRY_STEP_MS = 500     # video worker: pause before retrying a failed line (× failures)
_RETRY_MAX_STEPS = 6     # …capped at 3 s


def failure_notice(exc: Exception) -> str:
    """What the subtitle bar says when a line can't be translated — without it
    a dead connection looks exactly like "the app reads nothing"."""
    if is_transient_translation_error(exc):
        return "Mất kết nối tới máy chủ dịch — đang thử lại…"
    return f"Không dịch được: {str(exc)[:90]}"


def ctx_for_line(ctx: TranslationContext, src: str) -> TranslationContext:
    """Auto mode: pin the source language per line when the script is
    unambiguous (kana / plain Latin) — see linguistic.langdetect."""
    if ctx.source_lang:
        return ctx
    lang, confident = effective_source(None, src)
    return replace(ctx, source_lang=lang) if confident else ctx


class TranslateWorker(QThread):
    """Coalescing translator: always translates the LATEST submitted line,
    dropping any intermediate ones queued while it was busy.

    A line that fails (network down) is retried while it is still the newest
    one, and `problem` tells the user why nothing is showing."""

    text_ready = Signal(str)
    problem = Signal(str)

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
        fails = 0
        while self._running:
            with self._lock:
                src = self._pending
                self._pending = None
            if src is None or src == last_done:
                self.msleep(_IDLE_MS)
                continue
            try:
                result = self._translator.translate(src, ctx_for_line(self._ctx, src))
            except Exception as exc:  # noqa: BLE001 — TranslationError or worse
                fails += 1
                log.warning("subtitle translate failed (%d in a row): %s", fails, exc)
                if self._running:
                    self.problem.emit(failure_notice(exc))
                with self._lock:
                    if self._pending is None:
                        self._pending = src   # still the newest line — try it again
                for _ in range(min(fails, _RETRY_MAX_STEPS) * _RETRY_STEP_MS // _IDLE_MS):
                    if not self._running:
                        break
                    self.msleep(_IDLE_MS)
                continue
            fails = 0
            last_done = src
            if self._running:
                self.text_ready.emit(result.translated_text)


class OrderedTranslateWorker(QThread):
    """Translates every submitted line, several at once, emitting in order.

    Audio subtitles used the coalescing worker: a 2-4 s network translation
    meant utterances that arrived meanwhile were silently skipped, and each
    line waited for the previous one. Here up to `_PARALLEL` requests run at
    once and results are released strictly in submission order (a fast reply
    to line 3 waits for line 2), so the two-line subtitle bar reads naturally.
    If lines pile up faster than they translate, the oldest NOT-yet-started
    ones are dropped (`_MAX_BACKLOG`) so the subtitles never fall far behind.
    """

    text_ready = Signal(str)
    problem = Signal(str)

    def __init__(self, translator: TranslationPipeline, ctx: TranslationContext) -> None:
        super().__init__()
        self._translator = translator
        self._ctx = ctx
        self._lock = threading.Lock()
        self._queue: deque[str] = deque()
        self._running = True
        self._last_submitted: str | None = None

    def submit(self, src: str) -> None:
        with self._lock:
            if src == self._last_submitted:
                return
            self._last_submitted = src
            self._queue.append(src)
            while len(self._queue) > _MAX_BACKLOG:
                dropped = self._queue.popleft()
                log.info("audio subtitle backlog — dropping %r", dropped[:40])

    def stop(self) -> None:
        self._running = False

    def _translate(self, src: str) -> str | None:
        try:
            return self._translator.translate(src, ctx_for_line(self._ctx, src)).translated_text
        except Exception as exc:  # noqa: BLE001 — TranslationError or worse
            log.warning("subtitle translate failed: %s", exc)
            if self._running:
                self.problem.emit(failure_notice(exc))
            return None

    def run(self) -> None:
        in_flight: deque[Future[str | None]] = deque()   # submission order
        pool = ThreadPoolExecutor(max_workers=_PARALLEL, thread_name_prefix="sub-tr")
        try:
            while self._running:
                with self._lock:
                    while self._queue and len(in_flight) < _PARALLEL:
                        in_flight.append(pool.submit(self._translate, self._queue.popleft()))
                # Release finished results strictly from the head (keeps order).
                while in_flight and in_flight[0].done():
                    text = in_flight.popleft().result()
                    if text and self._running:
                        self.text_ready.emit(text)
                self.msleep(_IDLE_MS)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


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
        for sig_name in ("new_source", "status", "error", "text_ready", "problem"):
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
