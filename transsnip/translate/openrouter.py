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

_API_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "google/gemini-2.0-flash-001"

# Curated list shown in the Settings model dropdown.
# Format: (display_name, model_id)
OPENROUTER_MODELS: list[tuple[str, str]] = [
    # --- Free models (không tốn credit) ---
    ("DeepSeek V4 Flash (free)", "deepseek/deepseek-v4-flash:free"),
    ("Gemini 2.0 Flash (free)", "google/gemini-2.0-flash-001:free"),
    ("DeepSeek R1 (free)", "deepseek/deepseek-r1:free"),
    ("DeepSeek V3 (free)", "deepseek/deepseek-chat-v3-5:free"),
    ("Llama 4 Maverick (free)", "meta-llama/llama-4-maverick:free"),
    ("Llama 4 Scout (free)", "meta-llama/llama-4-scout:free"),
    ("Mistral Small 3.2 (free)", "mistralai/mistral-small-3.2-24b-instruct:free"),
    ("Qwen3 30B A3B (free)", "qwen/qwen3-30b-a3b:free"),
    ("Qwen3 8B (free)", "qwen/qwen3-8b:free"),
    # --- Paid models ---
    ("Gemini 2.5 Flash", "google/gemini-2.5-flash-preview"),
    ("Gemini 2.5 Pro", "google/gemini-2.5-pro-preview"),
    ("Claude Haiku 4.5", "anthropic/claude-haiku-4-5"),
    ("Claude Sonnet 4.5", "anthropic/claude-sonnet-4-5"),
    ("GPT-4o Mini", "openai/gpt-4o-mini"),
    ("GPT-4o", "openai/gpt-4o"),
]

_LANG_NAMES: dict[str, str] = {
    "vi": "Vietnamese", "en": "English", "ja": "Japanese",
    "ko": "Korean", "zh-Hans": "Simplified Chinese", "zh-Hant": "Traditional Chinese",
    "fr": "French", "de": "German", "es": "Spanish", "th": "Thai",
    "ru": "Russian", "ar": "Arabic", "pt": "Portuguese", "it": "Italian",
}


class OpenRouterTranslator(Translator):
    """OpenRouter provider — exposes 300+ models via a single OpenAI-compatible API.

    API key from keyring (key "openrouter") or env var OPENROUTER_API_KEY.
    Model is stored in settings as `openrouter_model` (defaults to Gemini Flash free).
    """

    name = "openrouter"

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        self._api_key = api_key or self._lookup_key()
        self._model = model or self._lookup_model()
        self._client: Any | None = None
        self._import_ok = self._try_import()

    @staticmethod
    def _lookup_key() -> str | None:
        try:
            from transsnip.config.keyring_store import get_api_key
            stored = get_api_key("openrouter")
            if stored:
                return stored
        except ImportError:
            pass
        return os.environ.get("OPENROUTER_API_KEY")

    @staticmethod
    def _lookup_model() -> str:
        try:
            from transsnip.config.settings import load_settings
            s = load_settings()
            return getattr(s.translate, "openrouter_model", None) or _DEFAULT_MODEL
        except Exception:
            return _DEFAULT_MODEL

    @staticmethod
    def _try_import() -> bool:
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            log.warning(
                "openai SDK not installed — OpenRouter disabled. Run: pip install openai"
            )
            return False

    def is_available(self) -> bool:
        return self._import_ok and bool(self._api_key)

    def _ensure_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=_API_BASE,
                default_headers={
                    "HTTP-Referer": "https://github.com/transsnip",
                    "X-Title": "TransSnip",
                },
            )
        return self._client

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        if not self._import_ok:
            raise TranslationError("openai SDK not installed — run: pip install openai")
        if not self._api_key:
            raise TranslationError(
                "OpenRouter API key chưa set. Lấy key miễn phí tại openrouter.ai → Keys"
            )

        system_prompt = self._build_system_prompt(ctx)
        try:
            response = self._ensure_client().chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=2048,
                temperature=0.1,
            )
        except Exception as exc:
            raise TranslationError(f"OpenRouter API call failed: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        translation = (choice.message.content or "").strip() if choice else ""

        if not translation:
            raise TranslationError("OpenRouter returned empty response")

        usage = response.usage
        if usage:
            log.debug(
                "OpenRouter [%s]: in=%d out=%d tokens",
                self._model, usage.prompt_tokens, usage.completion_tokens,
            )

        return TranslationResult(
            source_text=text,
            translated_text=translation,
            source_lang=ctx.source_lang or "auto",
            target_lang=ctx.target_lang,
            provider=f"openrouter/{self._model.split('/')[-1]}",
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
