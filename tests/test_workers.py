from transsnip.utils.workers import FnWorker


class _Expected(Exception):
    pass


def _run(fn, expected=()):
    done, failed = [], []
    worker = FnWorker(fn, expected=expected)
    worker.signals.done.connect(done.append)
    worker.signals.failed.connect(failed.append)
    worker.run()  # synchronous: same thread → direct connection
    return done, failed


def test_done_carries_result() -> None:
    assert _run(lambda: 42) == ([42], [])


def test_expected_error_reports_its_message() -> None:
    def boom():
        raise _Expected("no text")

    assert _run(boom, expected=(_Expected,)) == ([], ["no text"])


def test_unexpected_error_never_escapes() -> None:
    def boom():
        raise ValueError("bad")

    assert _run(boom) == ([], ["Unexpected: bad"])


def test_run_in_pool_delivers_to_plain_callables(qapp) -> None:
    """Regression: lambda/partial callbacks were silently dropped because the
    signal carrier died with the auto-deleted runnable before delivery."""
    import functools
    import threading
    import time

    from transsnip.utils.workers import run_in_pool

    app = qapp
    main = threading.get_ident()
    got: list[tuple[str, object, bool]] = []

    def record(tag: str, value: object) -> None:
        got.append((tag, value, threading.get_ident() == main))

    run_in_pool(lambda: 1, lambda r: record("lambda", r), print)
    run_in_pool(lambda: 2, functools.partial(record, "partial"), print)
    run_in_pool(lambda: 1 / 0, print, functools.partial(record, "failed"))

    deadline = time.monotonic() + 5
    while len(got) < 3 and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert sorted(got, key=lambda g: g[0]) == [
        ("failed", "Unexpected: division by zero", True),
        ("lambda", 1, True),
        ("partial", 2, True),
    ]
