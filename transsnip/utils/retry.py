"""Tiny retry-with-backoff helper for flaky network calls.

Translation providers hit remote APIs that fail transiently — a dropped
connection, a 503, a momentary rate-limit. Retrying those once or twice with a
short backoff turns a user-visible error into an invisible hiccup. But we must
NOT retry *permanent* failures (bad API key, missing SDK, quota exhausted) —
that just makes the user wait longer for the same error. The caller supplies a
`transient` predicate to draw that line.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    *,
    retries: int = 2,
    base_delay: float = 0.4,
    transient: Callable[[Exception], bool] | None = None,
    label: str = "call",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn`, retrying on transient errors with exponential backoff.

    `retries` is the number of EXTRA attempts (retries=2 → up to 3 calls total).
    Backoff is `base_delay * 2**attempt` (0.4s, 0.8s, …). If `transient` is
    given and returns False for the raised exception, it's re-raised immediately
    (no retry). `sleep` is injectable so tests don't actually wait.
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — re-raised below
            last = exc
            is_last = attempt == retries
            if is_last or (transient is not None and not transient(exc)):
                raise
            delay = base_delay * (2 ** attempt)
            log.info("%s failed (%s) — retry %d/%d in %.1fs",
                     label, exc, attempt + 1, retries, delay)
            sleep(delay)
    # Unreachable (loop either returns or raises), but satisfies the type checker.
    raise last  # type: ignore[misc]
