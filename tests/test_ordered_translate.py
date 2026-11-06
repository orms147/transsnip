"""Audio subtitles: every line translated, concurrently, released in order."""
import threading
import time

from transsnip.modes.pipeline import OrderedTranslateWorker
from transsnip.translate.base import TranslationContext, TranslationResult


class _SlowTranslator:
    """Line N takes delays[N] seconds — later lines can finish first."""

    def __init__(self, delays: dict[str, float]) -> None:
        self.delays, self.active, self.peak = delays, 0, 0
        self._lock = threading.Lock()

    def translate(self, text, ctx):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.delays.get(text, 0.05))
        with self._lock:
            self.active -= 1
        return TranslationResult(text, f"T({text})", "zh", "vi", "fake")


def _run(qapp, lines, delays):
    tr = _SlowTranslator(delays)
    w = OrderedTranslateWorker(tr, TranslationContext(target_lang="vi"))
    got: list[str] = []
    w.text_ready.connect(got.append)
    w.start()
    for ln in lines:
        w.submit(ln)
    deadline = time.monotonic() + 5
    while len(got) < len(lines) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    w.stop()
    w.wait(2000)
    return got, tr


def test_all_lines_emitted_in_order_even_if_later_ones_finish_first(qapp):
    got, tr = _run(qapp, ["a", "b", "c"], {"a": 0.4, "b": 0.1, "c": 0.05})
    assert got == ["T(a)", "T(b)", "T(c)"]
    assert tr.peak >= 2                         # really ran concurrently


def test_parallel_is_faster_than_sequential(qapp):
    t0 = time.monotonic()
    _run(qapp, ["a", "b", "c"], {"a": 0.3, "b": 0.3, "c": 0.3})
    assert time.monotonic() - t0 < 0.75         # sequential would be ≥ 0.9 s


def test_duplicate_consecutive_lines_are_translated_once(qapp):
    got, _ = _run(qapp, ["x", "x", "y"], {})
    assert got == ["T(x)", "T(y)"] or got[:2] == ["T(x)", "T(y)"]
