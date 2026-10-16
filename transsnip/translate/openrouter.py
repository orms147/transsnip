from __future__ import annotations

import logging
from typing import Any

from transsnip.translate.llm import MAX_OUTPUT_TOKENS, REQUEST_TIMEOUT_S, LLMTranslator

log = logging.getLogger(__name__)

_API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-3.6-flash"

# Curated list shown in the Settings model dropdown ("Fetch" pulls the full
# live catalog). IDs checked against openrouter.ai/api/v1/models, 2026-10.
# Format: (display_name, model_id)
OPENROUTER_MODELS: list[tuple[str, str]] = [
    # --- Free models (không tốn credit) ---
    ("Gemma 4 31B (free)", "google/gemma-4-31b-it:free"),
    ("Gemma 4 26B A4B (free)", "google/gemma-4-26b-a4b-it:free"),
    # --- Paid models ---
    ("Gemini 3.6 Flash", "google/gemini-3.6-flash"),
    ("Gemini 3.5 Flash-Lite", "google/gemini-3.5-flash-lite"),
    ("Claude Haiku 5.5", "anthropic/claude-haiku-5.5"),
    ("Claude Sonnet 5.5", "anthropic/claude-sonnet-5.5"),
    ("GPT-4o Mini", "openai/gpt-4o-mini"),
]

# Shut-down model IDs still sitting in users' settings.json → live successor,
# so an upgrade doesn't leave OpenRouter failing on every request.
_RETIRED_MODELS: dict[str, str] = {
    "google/gemini-2.0-flash-001": DEFAULT_MODEL,
    "google/gemini-2.0-flash-001:free": DEFAULT_MODEL,
    "google/gemini-2.5-flash-preview": DEFAULT_MODEL,
    "google/gemini-2.5-pro-preview": DEFAULT_MODEL,
}


class OpenRouterTranslator(LLMTranslator):
    """OpenRouter provider — exposes 300+ models via a single OpenAI-compatible API.

    API key from keyring (key "openrouter") or env var OPENROUTER_API_KEY.
    The model comes from settings (`translate.openrouter_model`) via
    `registry.build_pipeline`.
    """

    name = "openrouter"
    default_model = DEFAULT_MODEL
    env_var = "OPENROUTER_API_KEY"
    sdk_module = "openai"
    sdk_package = "openai"
    missing_key_message = "OpenRouter API key chưa set. Lấy key miễn phí tại openrouter.ai → Keys"

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        if model in _RETIRED_MODELS:
            log.info("OpenRouter model %s is retired — using %s", model, _RETIRED_MODELS[model])
            model = _RETIRED_MODELS[model]
        super().__init__(model=model, api_key=api_key)

    def _ensure_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=_API_BASE,
                timeout=REQUEST_TIMEOUT_S,
                default_headers={
                    "HTTP-Referer": "https://github.com/transsnip",
                    "X-Title": "TransSnip",
                },
            )
        return self._client

    def _complete(self, system: str, user: str) -> str:
        response = self._ensure_client().chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.1,
        )
        if response.usage:
            log.debug(
                "OpenRouter [%s]: in=%d out=%d tokens",
                self._model, response.usage.prompt_tokens, response.usage.completion_tokens,
            )
        choice = response.choices[0] if response.choices else None
        return (choice.message.content or "") if choice else ""

    def _provider_label(self) -> str:
        return f"openrouter/{self._model.split('/')[-1]}"
