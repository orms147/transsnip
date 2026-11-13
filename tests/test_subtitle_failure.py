"""Live subtitles: a dead connection must be visible (not silent), and the
video worker retries the line that failed while it is still the newest."""
import time

from transsnip.modes import pipeline
from transsnip.modes.pipeline import OrderedTranslateWorker, TranslateWorker, failure_notice
from transsnip.translate.base import TranslationContext, TranslationError, TranslationResult

_CONN = "openrouter API call failed: Connection error."


class _Flaky:
    """Fails the first `fail` calls, then translates."""

    def __init__(self, fail: int, message: str = _CONN) -> None:
        self.fail, self.message, self.calls = fail, message, []

    def translate(self, text, ctx):
        self.calls.append(text)
        if len(self.calls) <= self.fail:
            raise TranslationError(self.message)
        return TranslationResult(text, f"T({text})", "zh", "vi", "fake")


def _pump(qapp, done, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()


def _start(worker_cls, tr):
    w = worker_cls(tr, TranslationContext(target_lang="vi"))
    got: list[str] = []
    problems: list[str] = []
    w.text_ready.connect(got.append)
    w.problem.connect(problems.append)
    w.start()
    return w, got, problems


def test_video_line_is_retried_and_failure_is_reported(qapp, monkeypatch):
    monkeypatch.setattr(pipeline, "_RETRY_STEP_MS", 40)
    tr = _Flaky(fail=2)
    w, got, problems = _start(TranslateWorker, tr)
    w.submit("你好")
    _pump(qapp, lambda: bool(got))
    w.stop()
    w.wait(2000)
    assert got == ["T(你好)"]
    assert tr.calls == ["你好"] * 3
    assert len(problems) == 2 and "Mất kết nối" in problems[0]


def test_video_retry_gives_way_to_a_newer_line(qapp, monkeypatch):
    monkeypatch.setattr(pipeline, "_RETRY_STEP_MS", 200)
    tr = _Flaky(fail=1)
    w, got, problems = _start(TranslateWorker, tr)
    w.submit("old")
    _pump(qapp, lambda: bool(problems))
    w.submit("new")                      # the subtitle changed while backing off
    _pump(qapp, lambda: bool(got))
    w.stop()
    w.wait(2000)
    assert got == ["T(new)"]
    assert tr.calls == ["old", "new"]


def test_audio_failure_is_reported(qapp):
    tr = _Flaky(fail=1)
    w, got, problems = _start(OrderedTranslateWorker, tr)
    w.submit("a")
    w.submit("b")
    _pump(qapp, lambda: bool(got) and bool(problems))
    w.stop()
    w.wait(2000)
    assert len(problems) == 1 and len(got) == 1


def test_permanent_error_shows_its_reason():
    assert "Mất kết nối" in failure_notice(TranslationError("Connection error."))
    msg = failure_notice(TranslationError("401 Unauthorized: invalid api key"))
    assert msg.startswith("Không dịch được") and "401" in msg
