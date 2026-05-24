from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from transsnip.translate.base import (
    Translator,
    TranslationContext,
    TranslationError,
    TranslationResult,
)

if TYPE_CHECKING:
    from PIL import Image

log = logging.getLogger(__name__)


# Flash is the cheap + fast tier, has a generous free quota (1500 req/day at the
# time of writing). User upgrades to `gemini-2.5-pro` via settings if they want.
_DEFAULT_MODEL = "gemini-2.0-flash"


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


class GeminiTranslator(Translator):
    """Google Gemini provider via the `google-generativeai` SDK.

    Why this is the default-recommended LLM provider for TransSnip users:
    - Free tier (1500 req/day on Flash) without a credit card
    - API key signup needs only a Google account, works from Vietnam without VPN
    - Translation quality close to Claude Haiku for the languages we care about
    - Pricing after free is ~11x cheaper than Claude Haiku per million tokens

    API key sources, in priority order:
      1. Constructor `api_key` arg
      2. Keyring (`transsnip:gemini`) — populated by the settings UI
      3. Environment variable `GOOGLE_API_KEY`
    """

    name = "gemini"

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        self._model_name = model or _DEFAULT_MODEL
        self._api_key = api_key or self._lookup_key()
        self._model: Any | None = None
        self._import_ok = self._try_import()

    @staticmethod
    def _try_import() -> bool:
        try:
            import google.generativeai  # noqa: F401
            return True
        except ImportError:
            log.warning(
                "google-generativeai not installed — Gemini disabled. "
                "Run: pip install google-generativeai"
            )
            return False

    @staticmethod
    def _lookup_key() -> str | None:
        # Lazy import — config module is fine to load here but we keep it lazy so
        # tests can stub the lookup without dragging in keyring.
        try:
            from transsnip.config.keyring_store import get_api_key
            stored = get_api_key("gemini")
            if stored:
                return stored
        except ImportError:
            pass
        import os
        return os.environ.get("GOOGLE_API_KEY")

    def is_available(self) -> bool:
        return self._import_ok and bool(self._api_key)

    def _ensure_model(self) -> Any:
        if self._model is None:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(self._model_name)
        return self._model

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        if not self._import_ok:
            raise TranslationError("google-generativeai not installed")
        if not self._api_key:
            raise TranslationError(
                "Gemini API key chưa set. Lấy key miễn phí tại aistudio.google.com → "
                "mở Settings trong tray và paste vào, hoặc set env GOOGLE_API_KEY."
            )

        prompt = self._build_prompt(text, ctx)
        try:
            response = self._ensure_model().generate_content(prompt)
        except Exception as exc:  # SDK raises a variety of types
            raise TranslationError(f"Gemini API call failed: {exc}") from exc

        translation = (response.text or "").strip()
        if not translation:
            raise TranslationError("Gemini returned empty response")

        return TranslationResult(
            source_text=text,
            translated_text=translation,
            source_lang=ctx.source_lang or "auto",
            target_lang=ctx.target_lang,
            provider=self.name,
        )

    # ── Vision path ─────────────────────────────────────────────────────────

    def supports_vision(self) -> bool:
        return self._import_ok and bool(self._api_key)

    def translate_image(self, image: "Image.Image", ctx: TranslationContext) -> TranslationResult:
        if not self._import_ok:
            raise TranslationError("google-generativeai not installed")
        if not self._api_key:
            raise TranslationError(
                "Gemini API key chưa set. Mở Settings → paste key (lấy miễn phí tại "
                "aistudio.google.com → Get API key)."
            )

        prompt = self._build_vision_prompt(ctx)
        try:
            # `generate_content` accepts a mixed list of text + PIL.Image — the SDK
            # encodes the image as inline base64 automatically.
            response = self._ensure_model().generate_content([prompt, image])
        except Exception as exc:
            raise TranslationError(f"Gemini Vision call failed: {exc}") from exc

        raw = (response.text or "").strip()
        if not raw:
            raise TranslationError("Gemini Vision returned empty response")

        original, translation = self._parse_vision_response(raw)
        if not translation:
            # Couldn't parse JSON — treat the whole response as translation and
            # leave source empty. Popup will hide the source label gracefully.
            translation = raw
            original = ""

        return TranslationResult(
            source_text=original,
            translated_text=translation,
            source_lang=ctx.source_lang or "auto",
            target_lang=ctx.target_lang,
            provider="gemini-vision",
        )

    @staticmethod
    def _parse_vision_response(raw: str) -> tuple[str, str]:
        """Extract {"original": ..., "translation": ...} from a Gemini reply.

        Gemini sometimes wraps JSON in ```json fences despite the prompt saying not
        to — strip those before parsing. On any failure, return ("", "") and let
        the caller decide how to recover.
        """
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return "", ""
        if not isinstance(data, dict):
            return "", ""
        return str(data.get("original", "")).strip(), str(data.get("translation", "")).strip()

    def _build_vision_prompt(self, ctx: TranslationContext) -> str:
        target_name = _LANG_NAMES.get(ctx.target_lang, ctx.target_lang)
        lines: list[str] = [
            f"Read every piece of text visible in this image and translate it into {target_name}.",
            "",
            "Rules:",
            "- Merge wrapped lines into single sentences. Keep paragraph breaks where the source clearly has them.",
            "- Preserve proper nouns, code identifiers, brand names in their original form.",
            "- Output ONLY a JSON object with this exact shape — no markdown fences, no commentary:",
            '  {"original": "<the source text exactly as it appears, normalized>",',
            '   "translation": "<faithful translation into ' + target_name + '>"}',
        ]
        if ctx.source_lang:
            source_name = _LANG_NAMES.get(ctx.source_lang, ctx.source_lang)
            lines.append(f"- Source language hint: {source_name}.")
        if ctx.system_prompt.strip():
            lines.append(f"- Extra instructions: {ctx.system_prompt.strip()}")
        if ctx.glossary:
            entries = "; ".join(f"{src} → {tgt}" for src, tgt in ctx.glossary.items())
            lines.append(f"- Glossary (use when source matches): {entries}.")
        return "\n".join(lines)

    @staticmethod
    def _build_prompt(text: str, ctx: TranslationContext) -> str:
        target_name = _LANG_NAMES.get(ctx.target_lang, ctx.target_lang)
        parts: list[str] = [
            f"You are a professional translator. Translate the text below into {target_name}.",
            "Output ONLY the translation — no quotes, no markdown fences, no preface.",
            "Preserve formatting. Keep proper nouns and code identifiers in their original form.",
        ]
        if ctx.source_lang:
            source_name = _LANG_NAMES.get(ctx.source_lang, ctx.source_lang)
            parts.append(f"The source language is {source_name}.")
        if ctx.system_prompt.strip():
            parts.append(ctx.system_prompt.strip())
        if ctx.glossary:
            entries = "; ".join(f"{src} → {tgt}" for src, tgt in ctx.glossary.items())
            parts.append(f"Glossary: {entries}.")
        parts.append("")
        parts.append("Text to translate:")
        parts.append(text)
        return "\n".join(parts)
