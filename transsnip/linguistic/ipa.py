"""IPA (International Phonetic Alphabet) lookup for English words.

Wraps `eng-to-ipa` (CMU pronouncing dictionary + g2p fallback) into a small,
cached helper. Returns `None` for words the dictionary doesn't know so the
caller can fall back to "no IPA shown" instead of garbage symbols.

Why offline (CMU dict) instead of fetching from Oxford / Cambridge online:
- Works without internet — fits the "snipe-translate as you read" use case
- No rate-limiting, no ToS issues
- Sub-millisecond lookup → can render IPA inline in the popup at OCR speed

CMU dict only covers ~135k North American English words; rare proper nouns
or made-up tokens return None and we just skip the IPA for them.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

log = logging.getLogger(__name__)

# Strip surrounding punctuation/quotes; preserve the word itself so the caller
# can still display "hello," without losing the comma after the IPA gloss.
_WORD_BODY_RE = re.compile(r"^[\W_]*([\w'-]+)[\W_]*$", re.UNICODE)


@lru_cache(maxsize=4096)
def get_ipa(word: str) -> str | None:
    """Return IPA for `word` (without surrounding slashes), or None if unknown.

    Cached because the same words recur constantly in real OCR'd text and the
    dictionary lookup, while cheap, isn't free at the rate we render popups.
    """
    if not word:
        return None
    try:
        import eng_to_ipa
    except ImportError:
        log.warning("eng-to-ipa not installed; IPA disabled")
        return None

    body = _word_body(word)
    if not body:
        return None
    try:
        # `convert(word, keep_punct=False, stress_marks='primary')` returns
        # the IPA string with a trailing `*` for unknown words. We detect the
        # `*` marker and return None so callers can skip those words instead
        # of showing a literal asterisk.
        result = eng_to_ipa.convert(body, keep_punct=False, stress_marks="primary")
    except Exception as exc:  # noqa: BLE001 — library raises on weird input
        log.debug("IPA lookup failed for %r: %s", body, exc)
        return None
    if not result or result.endswith("*"):
        return None
    return result.strip()


def _word_body(token: str) -> str:
    """Strip leading/trailing punctuation, keeping internal apostrophes/hyphens.

    e.g. `"Hello,"` → `"Hello"`, `"don't"` → `"don't"`, `"--well--"` → `"well"`.
    """
    match = _WORD_BODY_RE.match(token)
    return match.group(1) if match else ""
