from __future__ import annotations

import logging
import os
from typing import Any

from transsnip.translate.base import (
    Translator,
    TranslationContext,
    TranslationError,
    TranslationResult,
)

log = logging.getLogger(__name__)


# Haiku 4.5: cheapest + fastest of the Claude 4 family. Sufficient for short
# screen-translation snippets. Power users can override via the constructor or
# (later) the settings UI.
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# BCP-47 → English name, used in the system prompt because LLMs interpret
# language names more reliably than raw tags.
_LANG_NAMES: dict[str, str] = {
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


class ClaudeTranslator(Translator):
    """Anthropic Claude provider. API key comes from `ANTHROPIC_API_KEY` env var
    until the settings UI lands (keyring storage is milestone 7).
    """

    name = "claude"

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        self._model = model or _DEFAULT_MODEL
        self._api_key = api_key or self._lookup_key()
        self._client: Any | None = None
        self._import_ok = self._try_import()

    @staticmethod
    def _lookup_key() -> str | None:
        # Priority: keyring (set by Settings window) → env var (for dev).
        try:
            from transsnip.config.keyring_store import get_api_key
            stored = get_api_key("claude")
            if stored:
                return stored
        except ImportError:
            pass
        return os.environ.get("ANTHROPIC_API_KEY")

    @staticmethod
    def _try_import() -> bool:
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            log.warning(
                "anthropic SDK not installed — Claude translator disabled. "
                "Run: pip install anthropic"
            )
            return False

    def is_available(self) -> bool:
        return self._import_ok and bool(self._api_key)

    def _ensure_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self._api_key)
        return self._client

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        if not self._import_ok:
            raise TranslationError("anthropic SDK not installed")
        if not self._api_key:
            raise TranslationError(
                "ANTHROPIC_API_KEY chưa set. Lấy key tại console.anthropic.com → "
                "PowerShell: $env:ANTHROPIC_API_KEY = 'sk-...' rồi chạy lại app."
            )

        # Learning mode: per-word breakdown JSON (shared prompt/parser).
        want_breakdown = ctx.want_word_breakdown
        if want_breakdown:
            from transsnip.linguistic.word_breakdown import build_breakdown_prompt
            system_prompt = "You are a translator and language tutor. Reply with JSON only."
            user_content = build_breakdown_prompt(text, ctx)
        else:
            system_prompt = self._build_system_prompt(ctx)
            user_content = text
        try:
            response = self._ensure_client().messages.create(
                model=self._model,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as exc:  # anthropic raises various subclasses
            raise TranslationError(f"Claude API call failed: {exc}") from exc

        raw = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()

        words = None
        if want_breakdown:
            from transsnip.linguistic.word_breakdown import parse_breakdown
            translation, parsed_words = parse_breakdown(raw)
            if not translation:
                translation = raw  # JSON parse failed → degrade to plain text
            words = parsed_words or None
        else:
            translation = raw

        if not translation:
            raise TranslationError("Claude returned empty response")

        log.debug(
            "Claude translation: in=%d tokens, out=%d tokens",
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        return TranslationResult(
            source_text=text,
            translated_text=translation,
            source_lang=ctx.source_lang or "auto",
            target_lang=ctx.target_lang,
            provider=self.name,
            words=words,
        )

    @staticmethod
    def _build_system_prompt(ctx: TranslationContext) -> str:
        target_name = _LANG_NAMES.get(ctx.target_lang, ctx.target_lang)
        parts: list[str] = [
            f"You are a professional translator. Translate the user's text into {target_name}.",
            "Output ONLY the translation — no quotes, no markdown fences, no preface, no explanation.",
            "Preserve formatting (line breaks, lists). Keep proper nouns and code identifiers in their original form.",
        ]
        if ctx.source_lang:
            source_name = _LANG_NAMES.get(ctx.source_lang, ctx.source_lang)
            parts.append(f"The source is {source_name}.")
        if ctx.system_prompt.strip():
            parts.append(ctx.system_prompt.strip())
        if ctx.glossary:
            entries = "; ".join(f"{src} → {tgt}" for src, tgt in ctx.glossary.items())
            parts.append(f"Use this glossary when the source matches: {entries}.")
        return "\n".join(parts)
