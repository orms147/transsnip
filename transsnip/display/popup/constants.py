"""Shared sizing / font / language constants and small helpers for the popup."""
from __future__ import annotations

import re

# Default size from design (`POPUP_W = 460`). Height grows with content,
# clamped between _MIN_HEIGHT and the available screen height.
_DEFAULT_WIDTH = 460
_DEFAULT_HEIGHT = 360
_MIN_WIDTH = 320
_MIN_HEIGHT = 140
_MARGIN_FROM_EDGE = 16

# Languages offered in the popup's quick lang-picker menus (code order = menu
# order). The full ~100-language list stays in Settings; "Ngôn ngữ khác…" at
# the bottom of the menu routes there.
_COMMON_LANGS: list[str] = [
    "en", "vi", "ja", "ko", "zh-Hans", "zh-Hant",
    "fr", "de", "es", "ru", "th", "ar",
]
_GAP_FROM_REGION = 12
_RESIZE_MARGIN = 8

# Font scaling — base point sizes at _DEFAULT_WIDTH, multiplied by width/default
# (clamped) so a user dragging the popup wider gets larger reading text.
_FONT_SOURCE_PT = 11
_FONT_TRANSLATION_PT = 12
_FONT_IPA_PT = 9
_FONT_MIN_SCALE = 0.7   # allow shrinking text below default (A− button)
_FONT_MAX_SCALE = 2.4

_SPEAK_LINK_PREFIX = "speak:"
_IPA_TOKEN_RE = re.compile(r"\S+|\s+")

# IPA renders the primary-stress mark ˈ (U+02C8) as a raised tick BEFORE the
# stressed syllable — but only in a font with proper spacing-modifier metrics.
# The app's UI font (Inter) is web-only and usually not installed, so the
# fallback mispositioned the tick (it looked like it sat on top of the next
# letter). Pin the phonetic rows to fonts that render IPA correctly; Segoe UI
# ships with Windows and has the right metrics, the SIL fonts are the ideal if
# present. Kept as a CSS stack (HTML) + family list (QFont metrics) in sync.
_IPA_FONT_FAMILIES = ["Segoe UI", "Charis SIL", "Doulos SIL", "Arial"]
_IPA_FONT_CSS = "'Segoe UI', 'Charis SIL', 'Doulos SIL', Arial, sans-serif"

# A default Edge-TTS voice per target language, used to read the TRANSLATION
# aloud (Standard/Learning mode). The Settings → Voice `voice` is for the SOURCE
# (English pronunciation); reading a Vietnamese translation with an English
# voice sounds wrong, so we pick a matching voice by target language here.
_TARGET_VOICE: dict[str, str] = {
    "vi": "vi-VN-HoaiMyNeural",
    "en": "en-US-AriaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "zh-Hans": "zh-CN-XiaoxiaoNeural",
    "zh-Hant": "zh-TW-HsiaoChenNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "es": "es-ES-ElviraNeural",
    "th": "th-TH-PremwadeeNeural",
    "ru": "ru-RU-SvetlanaNeural",
}


def _voice_for_lang(lang: str) -> str:
    """Edge voice for a target language; falls back to Vietnamese."""
    primary = (lang or "vi").split("-")[0]
    return _TARGET_VOICE.get(lang) or _TARGET_VOICE.get(primary, "vi-VN-HoaiMyNeural")

# ── Helpers ───────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int = 800) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _lang_display_name(code: str | None) -> str:
    """Map a BCP-47 primary subtag to a human-readable label.

    Tiny table — covers the languages TransSnip actually shows headers for.
    Anything not listed falls back to the uppercase code.
    """
    if not code:
        return ""
    mapping = {
        "en": "English",
        "ja": "日本語",
        "ko": "한국어",
        "zh": "中文",
        "zh-Hans": "中文 简体",
        "zh-Hant": "中文 繁體",
        "vi": "Tiếng Việt",
        "fr": "Français",
        "de": "Deutsch",
        "es": "Español",
        "ru": "Русский",
        "ar": "العربية",
        "th": "ภาษาไทย",
    }
    return mapping.get(code, code.upper())
