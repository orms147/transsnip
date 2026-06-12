from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from transsnip.translate.base import (
    Translator,
    TranslationContext,
    TranslationResult,
)

if TYPE_CHECKING:
    from PIL import Image
from transsnip.translate.cache import TranslationCache
from transsnip.translate.claude import ClaudeTranslator
from transsnip.translate.gemini import GeminiTranslator
from transsnip.translate.google_free import GoogleTranslateFree
from transsnip.translate.openrouter import OpenRouterTranslator

log = logging.getLogger(__name__)


# Substrings that mark a PERMANENT failure — retrying these just wastes the
# user's time (same error, slower). Providers wrap their SDK exceptions into
# TranslationError(f"... {exc}"), so we match against the message text.
_PERMANENT_MARKERS = (
    "api key", "api_key", "apikey", "chưa set", "not installed", "sdk not installed",
    "unauthorized", "authentication", "permission", "forbidden", "invalid", "quota",
    "exhausted", "billing", "not found", "401", "403", "404",
)


def is_transient_translation_error(exc: Exception) -> bool:
    """True if `exc` looks worth retrying (network/5xx/rate-limit), not permanent.

    Defaults to transient (retry) unless the message clearly names a permanent
    problem — better to retry an ambiguous error once than to surface a flake.
    """
    msg = str(exc).lower()
    return not any(marker in msg for marker in _PERMANENT_MARKERS)


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata describing one translation backend for the UI."""

    key: str
    display_name: str
    needs_api_key: bool
    api_key_hint: str  # where the user gets the key — shown in settings
    factory: Callable[[], Translator]


PROVIDER_REGISTRY: dict[str, ProviderInfo] = {
    "google_free": ProviderInfo(
        key="google_free",
        display_name="Google Translate (free, no key)",
        needs_api_key=False,
        api_key_hint="",
        factory=GoogleTranslateFree,
    ),
    "gemini": ProviderInfo(
        key="gemini",
        display_name="Google Gemini (free tier 1500/day)",
        needs_api_key=True,
        api_key_hint="Lấy free tại aistudio.google.com → Get API key",
        factory=GeminiTranslator,
    ),
    "claude": ProviderInfo(
        key="claude",
        display_name="Anthropic Claude (premium, paid)",
        needs_api_key=True,
        api_key_hint="Lấy tại console.anthropic.com → API Keys",
        factory=ClaudeTranslator,
    ),
    "openrouter": ProviderInfo(
        key="openrouter",
        display_name="OpenRouter (300+ models, free tier available)",
        needs_api_key=True,
        api_key_hint="Lấy free tại openrouter.ai → Keys (có nhiều model miễn phí)",
        factory=OpenRouterTranslator,
    ),
}


class TranslationPipeline:
    """Wraps a `Translator` with a `TranslationCache`.

    Cache lookup runs before the provider call. On miss, the provider is invoked and
    the result is written back. Pipeline doesn't chain providers — the active one is
    chosen at construction time from settings.
    """

    def __init__(
        self,
        translator: Translator,
        cache: TranslationCache | None = None,
    ) -> None:
        self._translator = translator
        self._cache = cache or TranslationCache()

    @property
    def provider_name(self) -> str:
        return self._translator.name

    def is_available(self) -> bool:
        return self._translator.is_available()

    def supports_vision(self) -> bool:
        return self._translator.supports_vision()

    def translate_image(self, image: "Image.Image", ctx: TranslationContext) -> TranslationResult:
        """Vision path — skips OCR + cache, sends image directly to a vision-capable provider.

        We don't cache image translations: hashing arbitrary screenshots produces near-zero
        hit rate (users rarely capture pixel-identical regions twice). The text path still
        caches, which catches the more common "re-translate the same text" pattern.
        """
        log.info("Vision translation via %s", self._translator.name)
        return self._translator.translate_image(image, ctx)

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        provider = self._translator.name
        cached = self._cache.get(text, ctx, provider)
        if cached is not None:
            log.info("Translation cache hit (%s)", provider)
            return cached

        log.info("Translation cache miss — calling %s", provider)
        # Retry transient network failures (dropped connection, 503, rate-limit)
        # with backoff; permanent failures (bad key, missing SDK) fail fast.
        from transsnip.utils.retry import with_retry
        result = with_retry(
            lambda: self._translator.translate(text, ctx),
            retries=2,
            transient=is_transient_translation_error,
            label=f"translate({provider})",
        )
        self._cache.put(text, ctx, provider, result)
        return result


def build_pipeline(
    provider_key: str,
    cache: TranslationCache | None = None,
    *,
    openrouter_model: str | None = None,
) -> TranslationPipeline:
    """Construct a pipeline using the named provider.

    Falls back to `google_free` if the requested provider key is unknown — keeps
    the app usable when settings.json references a provider that was removed.

    `openrouter_model` is forwarded to the OpenRouter provider so the model the
    user picked in Settings is actually used at runtime (without it the provider
    silently fell back to its hardcoded default — the saved choice did nothing).
    """
    info = PROVIDER_REGISTRY.get(provider_key)
    if info is None:
        log.warning("Unknown provider %r — falling back to google_free", provider_key)
        info = PROVIDER_REGISTRY["google_free"]
    if info.key == "openrouter" and openrouter_model:
        translator = info.factory(model=openrouter_model)  # type: ignore[call-arg]
    else:
        translator = info.factory()
    return TranslationPipeline(translator, cache)


def default_pipeline() -> TranslationPipeline:
    """Build the standard pipeline using whatever the user picked in settings."""
    # Lazy import — settings depends on pydantic, this module is hit early at startup.
    from transsnip.config.settings import load_settings
    s = load_settings()
    return build_pipeline(s.translate.provider, openrouter_model=s.translate.openrouter_model)
