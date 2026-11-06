"""Script-based source-language detection for "auto" mode (zh / ja / en focus).

When Settings leaves the source language on auto, OCR and ASR text arrives
with no language — and a lot of the app keys off it: English run-on
segmentation and IPA, the popup's language chip, TTS voice, history, the
translation prompt's "The source is …" hint, Whisper's zh script choice.

The scripts themselves settle most cases, deterministically and in
microseconds: Japanese always carries kana, Korean is Hangul, plain-ASCII
Latin is English. The one genuinely ambiguous case is Han-only text — a
kanji-only Japanese line ("東京都知事選挙") looks exactly like Chinese — so it
is reported as zh but NOT confident, and callers leave the translator on its
own auto-detect rather than force a possibly-wrong source.
"""
from __future__ import annotations

from dataclasses import dataclass

# Kana among Han+kana at or above this → Japanese. Real Japanese prose runs
# ~30-70% kana; Chinese text has none, so a small floor tolerates a stray
# katakana loanword quoted inside Chinese.
_KANA_MIN_RATIO = 0.05


@dataclass(frozen=True)
class Detection:
    lang: str | None   # BCP-47 tag as used in Settings ("ja", "zh-Hans", …)
    confident: bool    # safe to pin the translator's source language


def _counts(text: str) -> tuple[int, int, int, int, int]:
    han = kana = hangul = latin = latin_ext = 0
    for ch in text:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9D:
            kana += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
            han += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            hangul += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
        elif ch.isalpha() and o < 0x0250:  # Latin-1 / Extended-A/B letters (é, ơ, ß…)
            latin_ext += 1
    return han, kana, hangul, latin, latin_ext


def _han_variant(text: str) -> str:
    """zh-Hant if converting to Simplified changes a meaningful share of chars."""
    try:
        import zhconv
    except ImportError:
        return "zh-Hans"
    han = [c for c in text if 0x4E00 <= ord(c) <= 0x9FFF]
    if not han:
        return "zh-Hans"
    simp = zhconv.convert("".join(han), "zh-cn")
    changed = sum(a != b for a, b in zip(han, simp, strict=False))
    return "zh-Hant" if changed / len(han) >= 0.08 else "zh-Hans"


def detect_lang(text: str) -> Detection:
    han, kana, hangul, latin, latin_ext = _counts(text)
    cjk = han + kana
    if kana and kana / max(cjk, 1) >= _KANA_MIN_RATIO:
        return Detection("ja", True)
    if hangul and hangul >= cjk:
        return Detection("ko", True)
    if han and han >= latin // 3:            # CJK words are ~1-2 chars vs 5 Latin
        return Detection(_han_variant(text), False)
    if latin >= 3 and latin_ext <= latin * 0.02:
        return Detection("en", True)
    return Detection(None, False)


def effective_source(setting: str | None, text: str) -> tuple[str | None, bool]:
    """(language to treat the text as, whether it's safe to pin for translation).

    A language picked in Settings always wins (and is "pinned"); auto falls
    back to detection.
    """
    if setting:
        return setting, True
    d = detect_lang(text)
    return d.lang, d.confident
