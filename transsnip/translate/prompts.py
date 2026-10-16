"""Prompt text + reply parsing shared by every LLM translation provider.

Claude / Gemini / OpenRouter used to each carry their own copy of the language
table and system prompt, and the copies drifted (OpenRouter grew the "reply in
the target language, translate as-is" rules after fragmented OCR/ASR input made
small models answer in the source language — the others never got them).
Keeping one copy here means a prompt fix reaches every provider at once.
"""
from __future__ import annotations

import json
import re
from typing import Any

from transsnip.translate.base import TranslationContext

# BCP-47 → English name. LLMs follow language *names* more reliably than raw
# tags, so prompts say "Vietnamese", not "vi". Unknown tags pass through.
LANG_NAMES: dict[str, str] = {
    "vi": "Vietnamese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "th": "Thai",
    "ru": "Russian",
    "ar": "Arabic",
    "pt": "Portuguese",
    "it": "Italian",
}

# System prompt for Learning mode — the actual instructions travel in the user
# turn (see linguistic.word_breakdown.build_breakdown_prompt).
BREAKDOWN_SYSTEM_PROMPT = "You are a translator and language tutor. Reply with JSON only."


def lang_name(code: str | None) -> str:
    return LANG_NAMES.get(code or "", code or "")


def _context_lines(ctx: TranslationContext, *, bullet: str = "") -> list[str]:
    """Source-language hint + preset prompt + glossary, shared by every prompt."""
    lines: list[str] = []
    if ctx.source_lang:
        lines.append(f"{bullet}The source is {lang_name(ctx.source_lang)}.")
    if ctx.system_prompt.strip():
        lines.append(f"{bullet}{ctx.system_prompt.strip()}")
    if ctx.glossary:
        entries = "; ".join(f"{src} → {tgt}" for src, tgt in ctx.glossary.items())
        lines.append(f"{bullet}Use this glossary when the source matches: {entries}.")
    return lines


def build_system_prompt(ctx: TranslationContext) -> str:
    """System prompt for plain text translation (user turn = the raw text)."""
    target = lang_name(ctx.target_lang)
    parts: list[str] = [
        f"You are a professional translator. Translate the user's text into {target}.",
        f"Your ENTIRE response MUST be written in {target}. Never reply in the "
        f"source language; if the text is already in {target}, return it unchanged.",
        "Translate exactly what is given even if it is fragmented, incomplete, or "
        "contains transcription/OCR errors — do NOT fix, rephrase, complete, or "
        "comment on the source; just translate it as-is.",
        "Output ONLY the translation — no quotes, no markdown fences, no preface, "
        "no explanation.",
        "Preserve formatting (line breaks, lists). Keep proper nouns and code "
        "identifiers in their original form.",
    ]
    parts += _context_lines(ctx)
    return "\n".join(parts)


def build_vision_prompt(ctx: TranslationContext) -> str:
    """Instruction for single-pass image → {original, translation} JSON."""
    target = lang_name(ctx.target_lang)
    lines: list[str] = [
        f"Read every piece of text visible in this image and translate it into {target}.",
        "",
        "Rules:",
        "- Merge wrapped lines into single sentences. Keep paragraph breaks where "
        "the source clearly has them.",
        "- Preserve proper nouns, code identifiers, brand names in their original form.",
        "- Output ONLY a JSON object with this exact shape — no markdown fences, "
        "no commentary:",
        '  {"original": "<the source text exactly as it appears, normalized>",',
        '   "translation": "<faithful translation into ' + target + '>"}',
    ]
    lines += _context_lines(ctx, bullet="- ")
    return "\n".join(lines)


_FENCE_OPEN = re.compile(r"^```(?:json)?\s*")
_FENCE_CLOSE = re.compile(r"\s*```$")


def parse_json_object(raw: str) -> dict[str, Any] | None:
    """Parse a model reply that should be one JSON object.

    Models wrap JSON in ```json fences despite being told not to — strip those
    first. Returns None on anything that isn't a JSON object so callers can
    degrade to treating the raw reply as plain text.
    """
    cleaned = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", raw.strip())).strip()
    try:
        data = json.loads(cleaned)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_vision_reply(raw: str) -> tuple[str, str]:
    """{"original", "translation"} reply → (original, translation); ("", "") on failure."""
    data = parse_json_object(raw)
    if data is None:
        return "", ""
    return str(data.get("original", "")).strip(), str(data.get("translation", "")).strip()
