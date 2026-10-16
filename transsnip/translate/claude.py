from __future__ import annotations

import logging
from typing import Any

from transsnip.translate.base import TranslationError
from transsnip.translate.llm import REQUEST_TIMEOUT_S, LLMTranslator

log = logging.getLogger(__name__)


# Haiku: cheapest + fastest tier — plenty for short screen-translation snippets.
# Haiku 5.5 thinks by default; "low" effort keeps a one-line translation fast
# (it can skip thinking entirely) instead of paying latency for reasoning.
_DEFAULT_MODEL = "claude-haiku-5-5"
_EFFORT = "low"
# Thinking tokens count toward max_tokens — leave room beyond the answer.
_MAX_TOKENS = 4096


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
            max_tokens=_MAX_TOKENS,
            system=system,
            output_config={"effort": _EFFORT},
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            raise TranslationError("Claude từ chối dịch đoạn này (safety filter).")
        log.debug(
            "Claude translation: in=%d tokens, out=%d tokens",
            response.usage.input_tokens, response.usage.output_tokens,
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
