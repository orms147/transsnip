from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from transsnip.translate.llm import REQUEST_TIMEOUT_S, VISION_TIMEOUT_S, LLMTranslator

if TYPE_CHECKING:
    from PIL import Image

log = logging.getLogger(__name__)


# Flash is the cheap + fast tier, has a generous free quota (1500 req/day at the
# time of writing). User upgrades to `gemini-2.5-pro` via settings if they want.
_DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiTranslator(LLMTranslator):
    """Google Gemini provider via the `google-generativeai` SDK.

    Why this is the default-recommended LLM provider for TransSnip users:
    - Free tier (1500 req/day on Flash) without a credit card
    - API key signup needs only a Google account, works from Vietnam without VPN
    - Translation quality close to Claude Haiku for the languages we care about
    - Pricing after free is ~11x cheaper than Claude Haiku per million tokens

    Also the one vision-capable provider: `translate_image` does OCR + translate
    in a single call, which beats our OCR pipeline on diacritics and wrapped
    sentences.
    """

    name = "gemini"
    default_model = _DEFAULT_MODEL
    env_var = "GOOGLE_API_KEY"
    sdk_module = "google.generativeai"
    sdk_package = "google-generativeai"
    missing_key_message = (
        "Gemini API key chưa set. Lấy key miễn phí tại aistudio.google.com → "
        "mở Settings trong tray và paste vào, hoặc set env GOOGLE_API_KEY."
    )

    def _ensure_client(self) -> Any:
        if self._client is None:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(self._model)
        return self._client

    def _complete(self, system: str, user: str) -> str:
        # The legacy SDK's GenerativeModel is built once per model, so the
        # (per-request) system prompt travels in the same turn as the text.
        prompt = f"{system}\n\nText to translate:\n{user}"
        response = self._ensure_client().generate_content(
            prompt, request_options={"timeout": REQUEST_TIMEOUT_S}
        )
        return response.text or ""

    def supports_vision(self) -> bool:
        return self.is_available()

    def _complete_image(self, prompt: str, image: Image.Image) -> str:
        # `generate_content` accepts a mixed list of text + PIL.Image — the SDK
        # encodes the image as inline base64 automatically.
        response = self._ensure_client().generate_content(
            [prompt, image], request_options={"timeout": VISION_TIMEOUT_S}
        )
        return response.text or ""
