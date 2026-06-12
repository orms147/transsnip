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
_VOWELS = set("aeiouAEIOU")
_MIN_VOWEL_RATIO = 0.18   # below this a token reads as a code, not English words
_MIN_LONG_SEG_RATIO = 0.5  # ≥half the split pieces must be "word-like" (len ≥ 3)
_DOMINANT_SEG_RATIO = 0.7  # one piece covering ≥70% ⇒ a single word + junk tail


def segment_english_runon(text: str) -> str:
    """Re-insert spaces into any run-on Latin tokens longer than the threshold.

    Idempotent — already-spaced text passes through unchanged because each
    token is short enough to skip the segment step. Preserves whitespace
    layout (multiple spaces, newlines) verbatim; only the content of long
    pure-alphanumeric runs is rewritten.

    Random ID-like runs (video IDs, hashes, SKUs such as "XRCCN8DFDZKMUXBJ")
    are deliberately left untouched: wordninja would otherwise shred them into
    "X RC CN 8 DFD Z KM UX BJ". Two cheap guards catch these — a vowel-ratio
    test (real English has vowels; codes mostly don't) and a split-quality
    test (a genuine concatenation splits into mostly real words, a code splits
    into a pile of 1-2 char fragments).
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
            and not _looks_like_code(token)
        ):
            segments = wordninja.split(token)
            if (
                len(segments) >= 2
                and _split_is_wordlike(segments)
                and not _is_oversplit_word(token, segments)
            ):
                out.append(_recase(token, segments))
                continue
        out.append(token)
    return "".join(out)


def _is_oversplit_word(token: str, segments: list[str]) -> bool:
    """True if `segments` look like ONE real word that got a tiny tail shaved off.

    wordninja splits "Disassembler" → ["disassemble", "r"]: the first piece is
    11 of 12 chars. A genuine run-on ("OpeningTitle" → opening/title) has no
    single dominant piece. If one segment covers ≥70% of the token, treat it as
    a normal word that was already spaced correctly and leave it untouched.
    """
    longest = max(len(s) for s in segments)
    return longest >= _DOMINANT_SEG_RATIO * len(token)


def _looks_like_code(token: str) -> bool:
    """True if `token` reads like a random ID/hash rather than joined words.

    Heuristic: real English (even run-on) keeps a healthy vowel ratio; a code
    like "XRCCN8DFDZKMUXBJ" is almost all consonants + digits. We measure
    vowels against the *letters* only (digits don't count either way).
    """
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return True  # all digits/symbols → never a word run
    vowel_ratio = sum(c in _VOWELS for c in letters) / len(letters)
    return vowel_ratio < _MIN_VOWEL_RATIO


def _split_is_wordlike(segments: list[str]) -> bool:
    """True if a wordninja split looks like real words, not code fragments.

    A good split ("OpeningTitle" → opening/title) is mostly pieces of length
    ≥ 3. A bad one ("XRCCN8…" → x/rc/cn/8/dfd/…) is mostly length 1-2. We keep
    the split only when at least half the pieces are word-like.
    """
    long_pieces = sum(len(s) >= 3 for s in segments)
    return long_pieces / len(segments) >= _MIN_LONG_SEG_RATIO


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
