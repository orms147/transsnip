"""with_retry + transient classifier."""
import pytest

from transsnip.translate.registry import is_transient_translation_error
from transsnip.utils.retry import with_retry


def test_succeeds_first_try():
    calls = []
    assert with_retry(lambda: calls.append(1) or "ok", sleep=lambda _d: None) == "ok"
    assert len(calls) == 1


def test_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("503 temporary")
        return "done"

    out = with_retry(flaky, retries=2, sleep=lambda _d: None)
    assert out == "done" and calls["n"] == 3


def test_raises_after_exhausting_retries():
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise RuntimeError("still broken")

    with pytest.raises(RuntimeError):
        with_retry(always_fail, retries=2, sleep=lambda _d: None)
    assert calls["n"] == 3  # 1 + 2 retries


def test_permanent_error_fails_fast():
    calls = {"n": 0}

    def auth_fail():
        calls["n"] += 1
        raise RuntimeError("invalid API key")

    with pytest.raises(RuntimeError):
        with_retry(
            auth_fail, retries=3,
            transient=is_transient_translation_error,
            sleep=lambda _d: None,
        )
    assert calls["n"] == 1  # not retried — permanent


def test_transient_classifier():
    assert is_transient_translation_error(Exception("connection reset")) is True
    assert is_transient_translation_error(Exception("503 Service Unavailable")) is True
    assert is_transient_translation_error(Exception("API key not set")) is False
    assert is_transient_translation_error(Exception("quota exhausted")) is False
