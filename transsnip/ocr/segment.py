"""Word-segmentation post-process for OCR output.

Windows OCR (and most engines) sometimes merge a whole stylized title into
a single token, e.g. "JLPTN3JAPANESELISTENINGPRACTICETEST2024WITHANSWERS".
There's no whitespace for our smart joiner to lean on, so the translator
sees one giant pseudo-word and produces garbage.

`segment_english_runon` uses `wordninja` (Wikipedia frequency lookup) to
split such tokens back into real words while preserving the original case
of each character. Only applied to long run-on tokens to avoid mangling
normal English text that was OCR'd fine.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

_RUNON_MIN_LEN = 12       # tokens shorter than this are usually OCR'd correctly
_LATIN_RE = re.compile(r"^[A-Za-z0-9]+$")
_TOKEN_RE = re.compile(r"\S+|\s+")


def segment_english_runon(text: str) -> str:
    """Re-insert spaces into any run-on Latin tokens longer than the threshold.

    Idempotent — already-spaced text passes through unchanged because each
    token is short enough to skip the segment step. Preserves whitespace
    layout (multiple spaces, newlines) verbatim; only the content of long
    pure-alphanumeric runs is rewritten.
    """
    try:
        import wordninja
    except ImportError:
        log.warning("wordninja not installed; skipping English re-segmentation")
        return text

    out: list[str] = []
    for token in _TOKEN_RE.findall(text):
        if (
            len(token) >= _RUNON_MIN_LEN
            and _LATIN_RE.match(token)
            and " " not in token
        ):
            segments = wordninja.split(token)
            if len(segments) >= 2:
                out.append(_recase(token, segments))
                continue
        out.append(token)
    return "".join(out)


def _recase(original: str, segments: list[str]) -> str:
    """Re-apply the original string's case to the wordninja output.

    wordninja lowercases everything during splitting; we step through the
    original character-by-character to restore case so "JLPTN3JAPANESE"
    comes back as "JLPT N3 JAPANESE" instead of "jlpt n 3 japanese".
    """
    joined = " ".join(segments)
    result: list[str] = []
    src_idx = 0
    for ch in joined:
        if ch == " ":
            result.append(" ")
            continue
        if src_idx < len(original):
            result.append(original[src_idx])
            src_idx += 1
        else:
            result.append(ch)
    return "".join(result)
