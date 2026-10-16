from __future__ import annotations

import logging
from typing import Any

from transsnip.translate.llm import MAX_OUTPUT_TOKENS, REQUEST_TIMEOUT_S, LLMTranslator

log = logging.getLogger(__name__)

_API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-2.0-flash-001"

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
