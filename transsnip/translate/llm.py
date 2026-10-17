"""Shared plumbing for LLM-backed translators (Claude, Gemini, OpenRouter).

Every LLM provider does the same dance around its SDK call: find the API key
(keyring → env var), check the optional SDK is installed, pick plain vs
Learning-mode prompt, parse the reply, and wrap it in a TranslationResult.
`LLMTranslator` owns that; a provider only implements `_complete()` — one
system + user turn in, reply text out — and optionally `_complete_image()`.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from transsnip.translate.base import (
    TranslationContext,
    TranslationError,
    TranslationResult,
    Translator,
)
from transsnip.translate.prompts import (
    BREAKDOWN_SYSTEM_PROMPT,
    build_system_prompt,
    build_user_turn,
    build_vision_prompt,
    looks_untranslated,
    parse_vision_reply,
)

if TYPE_CHECKING:
    from PIL import Image

log = logging.getLogger(__name__)

# Upper bound for any single provider round-trip. Without it a black-holed
# connection pins a QThreadPool slot forever (popup stuck at "Đang dịch…").
REQUEST_TIMEOUT_S = 30.0
VISION_TIMEOUT_S = 45.0
MAX_OUTPUT_TOKENS = 2048


def _module_available(name: str) -> bool:
    """Whether `name` is importable, without paying for the import itself
    (the SDKs are heavy and only needed on the first real call)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # parent package of a dotted name missing
        return False


class LLMTranslator(Translator):
    """Template for chat-style LLM providers. Subclasses set the class attrs
    below and implement `_complete()`."""

    default_model: str = ""
    env_var: str = ""             # dev fallback when keyring has no key
    sdk_module: str = ""          # importable module name of the optional SDK
    sdk_package: str = ""         # pip name, for the "not installed" message
    missing_key_message: str = "API key chưa set — mở Settings và paste key."

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        self._model = model or self.default_model
        self._api_key = api_key or self._lookup_key()
        self._client: Any | None = None
        self._sdk_ok = _module_available(self.sdk_module)
        if not self._sdk_ok:
            log.warning("%s not installed — %s translator disabled. Run: pip install %s",
                        self.sdk_package, self.name, self.sdk_package)

    @property
    def model(self) -> str:
        return self._model

    @property
    def cache_id(self) -> str:
        # Model is part of the identity: switching models must not serve the
        # previous model's cached output.
        return f"{self.name}:{self._model}"

    def _lookup_key(self) -> str | None:
        # Priority: keyring (set by the Settings window) → env var (for dev).
        from transsnip.config.keyring_store import get_api_key
        return get_api_key(self.name) or (os.environ.get(self.env_var) if self.env_var else None)

    def is_available(self) -> bool:
        return self._sdk_ok and bool(self._api_key)

    def _check_ready(self) -> None:
        if not self._sdk_ok:
            raise TranslationError(
                f"{self.sdk_package} not installed — run: pip install {self.sdk_package}"
            )
        if not self._api_key:
            raise TranslationError(self.missing_key_message)

    # ── Provider hooks ──────────────────────────────────────────────────────

    @abstractmethod
    def _complete(self, system: str, user: str) -> str:
        """One round-trip: system prompt + user turn → reply text.

        Raise anything on SDK failure — `translate()` wraps it into
        TranslationError so the retry layer can classify it.
        """

    def _complete_image(self, prompt: str, image: Image.Image) -> str:
        raise NotImplementedError(f"{self.name} doesn't support vision input")

    def _provider_label(self) -> str:
        """Shown in the popup header / history. Override to surface the model."""
        return self.name

    # ── Translator API ──────────────────────────────────────────────────────

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        self._check_ready()
        from transsnip.linguistic.word_breakdown import build_breakdown_prompt, parse_breakdown

        # Learning mode: ask for the per-word breakdown JSON instead of a plain
        # translation. Shared prompt/parser so every provider behaves the same.
        if ctx.want_word_breakdown:
            system, user = BREAKDOWN_SYSTEM_PROMPT, build_breakdown_prompt(text, ctx)
        else:
            system, user = build_system_prompt(ctx), build_user_turn(text, ctx)
        raw = self._call(system, user)
        if not ctx.want_word_breakdown and raw and looks_untranslated(raw, ctx.target_lang):
            # Model answered in the source script instead of translating — one
            # retry usually fixes it (sampling), and costs nothing when it doesn't fire.
            log.info("%s replied in the source language — retrying once", self.name)
            retry = self._call(system, user)
            raw = retry if retry and not looks_untranslated(retry, ctx.target_lang) else raw

        words = None
        translation = raw
        if ctx.want_word_breakdown:
            parsed, parsed_words = parse_breakdown(raw)
            # JSON parse failed → degrade to showing the raw reply as plain text.
            translation = parsed or raw
            words = parsed_words or None
        if not translation:
            raise TranslationError(f"{self.name} returned empty response")

        return TranslationResult(
            source_text=text,
            translated_text=translation,
            source_lang=ctx.source_lang or "auto",
            target_lang=ctx.target_lang,
            provider=self._provider_label(),
            words=words,
        )

    def _call(self, system: str, user: str) -> str:
        try:
            return (self._complete(system, user) or "").strip()
        except TranslationError:
            raise
        except Exception as exc:  # SDKs raise many unrelated types
            raise TranslationError(f"{self.name} API call failed: {exc}") from exc

    def translate_image(self, image: Image.Image, ctx: TranslationContext) -> TranslationResult:
        self._check_ready()
        try:
            raw = (self._complete_image(build_vision_prompt(ctx), image) or "").strip()
        except (TranslationError, NotImplementedError):
            raise
        except Exception as exc:
            raise TranslationError(f"{self.name} vision call failed: {exc}") from exc
        if not raw:
            raise TranslationError(f"{self.name} vision returned empty response")

        original, translation = parse_vision_reply(raw)
        if not translation:
            # Couldn't parse JSON — show the whole reply as the translation and
            # leave source empty (the popup hides an empty source gracefully).
            original, translation = "", raw
        return TranslationResult(
            source_text=original,
            translated_text=translation,
            source_lang=ctx.source_lang or "auto",
            target_lang=ctx.target_lang,
            provider=f"{self._provider_label()}-vision",
        )
