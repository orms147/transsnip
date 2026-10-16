"""Run a blocking call on the global QThreadPool and get the result back on the
main thread via signals.

OCR, translation and vision calls all block for 0.2-5 s, so they run off the
GUI thread. They used to be three near-identical QRunnable classes; this is
the one generic version.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class _WorkerSignals(QObject):
    """Signal carrier for `FnWorker`.

    Signals are a QObject feature, but QRunnable is not a QObject — so the
    carrier is a separate object. It's created on the main thread (in
    `FnWorker.__init__`), which makes every connected slot — including plain
    lambdas/partials — run on the main thread via a queued connection.
    """

    done = Signal(object)
    failed = Signal(str)


class FnWorker(QRunnable):
    """Calls `fn()` on a pool thread; emits `signals.done(result)` or
    `signals.failed(message)`. Never raises out of `run()`.

    Exceptions of an `expected` type are reported with their own message (a
    known failure mode, e.g. OCRError / TranslationError); anything else is
    logged with a traceback and reported as "Unexpected: …".
    """

    def __init__(
        self,
        fn: Callable[[], Any],
        *,
        expected: tuple[type[BaseException], ...] = (),
        label: str = "task",
    ) -> None:
        super().__init__()
        self._fn = fn
        self._expected = expected
        self._label = label
        self.signals = _WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._fn()
        except self._expected as exc:
            log.warning("%s failed: %s", self._label, exc)
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:  # worker must never raise
            log.exception("Unexpected %s error", self._label)
            self.signals.failed.emit(f"Unexpected: {exc}")
            return
        self.signals.done.emit(result)


def run_in_pool(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_failed: Callable[[str], None],
    *,
    expected: tuple[type[BaseException], ...] = (),
    label: str = "task",
) -> None:
    """Submit `fn` to the global QThreadPool; callbacks fire on the main thread."""
    worker = FnWorker(fn, expected=expected, label=label)
    signals = worker.signals
    # Keep the carrier alive until its result is DELIVERED, not just emitted.
    # With autoDelete the worker (and its only reference to `signals`) dies
    # right after run(); for a plain lambda/partial the carrier is the queued
    # call's only context, so Qt silently dropped the pending call — the
    # Alt+F overlay never appeared. Bound methods of a live QObject survived
    # by luck (the receiver, not the carrier, owns the queued event).
    _inflight.add(signals)

    def release(*_: object) -> None:
        _inflight.discard(signals)

    signals.done.connect(on_done)
    signals.failed.connect(on_failed)
    # Connected last → runs after the user callback (same-sender order).
    signals.done.connect(release)
    signals.failed.connect(release)
    QThreadPool.globalInstance().start(worker)


_inflight: set[_WorkerSignals] = set()
