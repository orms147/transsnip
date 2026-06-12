"""Learning-mode word breakdown — shared LLM prompt + parser + offline fallback.

When the user picks display_mode = "learning", LLM providers ask for a richer
reply: not just the translation, but a per-word gloss (IPA + meaning + part of
speech). This module centralizes that so gemini / claude / openrouter don't each
reinvent the prompt + JSON parsing:

- `build_breakdown_prompt()` — the instruction that asks for the JSON shape.
- `parse_breakdown()`      — turn the model's reply into (translation, [WordInfo]).
- `local_breakdown()`      — offline fallback for non-LLM providers (google_free):
  IPA for English words via the CMU dict, no meanings.

Keeping it provider-agnostic means a future provider gets Learning mode for free
by calling these two helpers around its own SDK call.
"""
from __future__ import annotations

import json
import logging
import re

from transsnip.linguistic.ipa import get_ipa
from transsnip.translate.base import TranslationContext, WordInfo

log = logging.getLogger(__name__)

# Minimal target-language naming for the prompt; falls back to the raw code.
_LANG_NAMES: dict[str, str] = {
    "vi": "Vietnamese", "en": "English", "ja": "Japanese", "ko": "Korean",
    "zh-Hans": "Simplified Chinese", "zh-Hant": "Traditional Chinese",
    "fr": "French", "de": "German", "es": "Spanish", "th": "Thai", "ru": "Russian",
}


def build_breakdown_prompt(text: str, ctx: TranslationContext) -> str:
    """LLM instruction asking for translation + per-word gloss as strict JSON."""
    target = _LANG_NAMES.get(ctx.target_lang, ctx.target_lang)
    parts: list[str] = [
        f"You are a translator AND a language tutor. Translate the text below into {target}, "
        f"then break the SOURCE text into meaningful words/tokens and gloss each one.",
        "",
        "Output ONLY a JSON object (no markdown fences, no commentary) of this exact shape:",
        '{"translation": "<full translation into ' + target + '>",',
        ' "words": [{"token": "<source word>", "ipa": "<IPA or empty>",',
        '            "meaning": "<short meaning in ' + target + '>", "pos": "<noun/verb/adj/...>"}]}',
        "",
        "Rules:",
        "- One entry per meaningful word; skip pure punctuation.",
        "- `ipa` only for alphabetic languages (English etc.); use \"\" when not applicable.",
        "- `meaning` is a SHORT gloss in " + target + " (1-4 words), not a full sentence.",
        "- Keep the source token exactly as written (preserve case).",
    ]
    if ctx.source_lang:
        parts.append(f"- Source language: {_LANG_NAMES.get(ctx.source_lang, ctx.source_lang)}.")
    if ctx.system_prompt.strip():
        parts.append(f"- Extra instructions: {ctx.system_prompt.strip()}")
    if ctx.glossary:
        entries = "; ".join(f"{s} → {t}" for s, t in ctx.glossary.items())
        parts.append(f"- Glossary (prefer these): {entries}.")
    parts += ["", "Text:", text]
    return "\n".join(parts)


def parse_breakdown(raw: str) -> tuple[str, list[WordInfo]]:
    """Parse an LLM breakdown reply → (translation, words).

    Tolerant of ```json fences. Returns ("", []) if it can't parse JSON, so the
    caller can fall back to treating the raw reply as a plain translation.
    """
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return "", []
    if not isinstance(data, dict):
        return "", []
    translation = str(data.get("translation", "")).strip()
    words: list[WordInfo] = []
    for w in data.get("words", []) or []:
        if not isinstance(w, dict):
            continue
        token = str(w.get("token", "")).strip()
        if not token:
            continue
        words.append(WordInfo(
            token=token,
            ipa=(str(w.get("ipa", "")).strip() or None),
            meaning=(str(w.get("meaning", "")).strip() or None),
            pos=(str(w.get("pos", "")).strip() or None),
        ))
    return translation, words


def local_breakdown(text: str) -> list[WordInfo]:
    """Offline fallback for non-LLM providers: IPA per English word, no meanings.

    Tokenizes on whitespace and attaches IPA from the CMU dict where available.
    Meanings/pos are left None — a free translator can't produce them without
    extra API calls, and partial info (IPA only) still helps a learner.
    """
    words: list[WordInfo] = []
    for token in text.split():
        clean = token.strip()
        if not clean:
            continue
        words.append(WordInfo(token=clean, ipa=get_ipa(clean), meaning=None, pos=None))
    return words
