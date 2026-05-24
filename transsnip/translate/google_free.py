from __future__ import annotations

import logging
import re

from transsnip.translate.base import (
    Translator,
    TranslationContext,
    TranslationError,
    TranslationResult,
)

log = logging.getLogger(__name__)


# Map BCP-47 to the codes `deep_translator` expects for Google Translate.
# Most BCP-47 tags pass through; CJK and a couple of regional ones differ.
_GOOGLE_CODE: dict[str, str] = {
    "vi": "vi",
    "en": "en",
    "ja": "ja",
    "ko": "ko",
    "zh-Hans": "zh-CN",
    "zh-Hant": "zh-TW",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "th": "th",
    "ru": "ru",
    "ar": "ar",
    "pt": "pt",
    "it": "it",
    "auto": "auto",
}


class GoogleTranslateFree(Translator):
    """Free, no-API-key translator via `deep_translator` (unofficial Google Translate).

    Why we keep this around alongside Gemini / Claude:
    - **Zero setup** — works the moment the user installs the app, no signup
    - **Truly free**, no quota credit card concern
    - Adequate quality for casual / general-purpose text

    Limitations:
    - No `system_prompt` / glossary support (the underlying endpoint is text-only)
    - Google may rate-limit aggressively on heavy / abusive use
    - No Learning-mode word breakdown (not an LLM)

    Glossary is applied as a *post-process* string replace, since the endpoint can't
    accept instructions. Best-effort, not perfect.
    """

    name = "google_free"

    def __init__(self) -> None:
        self._import_ok = self._try_import()

    @staticmethod
    def _try_import() -> bool:
        try:
            import deep_translator  # noqa: F401
            return True
        except ImportError:
            log.warning(
                "deep-translator not installed — Google Translate (free) disabled. "
                "Run: pip install deep-translator"
            )
            return False

    def is_available(self) -> bool:
        return self._import_ok

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        if not self._import_ok:
            raise TranslationError("deep-translator not installed")

        source = _GOOGLE_CODE.get(ctx.source_lang or "auto", "auto")
        target = _GOOGLE_CODE.get(ctx.target_lang, ctx.target_lang)

        try:
            from deep_translator import GoogleTranslator as _GT
            translator = _GT(source=source, target=target)
            translation = translator.translate(text)
        except Exception as exc:  # the library raises bare Exception subclasses
            raise TranslationError(f"Google Translate (free) failed: {exc}") from exc

        if not translation:
            raise TranslationError("Google Translate returned empty")

        translation = self._apply_glossary(translation, ctx.glossary)

        return TranslationResult(
            source_text=text,
            translated_text=translation.strip(),
            source_lang=ctx.source_lang or "auto",
            target_lang=ctx.target_lang,
            provider=self.name,
        )

    @staticmethod
    def _apply_glossary(text: str, glossary: dict[str, str]) -> str:
        # Best-effort whole-word replacement. Falls short of an LLM that can decide
        # WHEN a glossary term applies in context, but covers obvious cases.
        if not glossary:
            return text
        for src, tgt in glossary.items():
            pattern = re.compile(rf"\b{re.escape(src)}\b", re.IGNORECASE)
            text = pattern.sub(tgt, text)
        return text
