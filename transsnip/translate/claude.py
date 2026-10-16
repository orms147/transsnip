from __future__ import annotations

import logging
from typing import Any

from transsnip.translate.llm import MAX_OUTPUT_TOKENS, REQUEST_TIMEOUT_S, LLMTranslator

log = logging.getLogger(__name__)


# Haiku 4.5: cheapest + fastest of the Claude 4 family. Sufficient for short
# screen-translation snippets. Power users can override via the constructor or
# (later) the settings UI.
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class ClaudeTranslator(LLMTranslator):
    """Anthropic Claude provider. Key from keyring (`transsnip:claude`, set by
    the Settings window) or the `ANTHROPIC_API_KEY` env var."""

    name = "claude"
    default_model = _DEFAULT_MODEL
    env_var = "ANTHROPIC_API_KEY"
    sdk_module = "anthropic"
    sdk_package = "anthropic"
    missing_key_message = (
        "Claude API key chưa set. Lấy key tại console.anthropic.com → API Keys, "
        "rồi mở Settings trong tray và paste vào."
    )

    def _ensure_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self._api_key, timeout=REQUEST_TIMEOUT_S)
        return self._client

    def _complete(self, system: str, user: str) -> str:
        response = self._ensure_client().messages.create(
            model=self._model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        log.debug(
            "Claude translation: in=%d tokens, out=%d tokens",
            response.usage.input_tokens, response.usage.output_tokens,
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
