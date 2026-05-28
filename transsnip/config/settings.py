from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


def _settings_path() -> Path:
    """%APPDATA%\\transsnip\\settings.json on Windows, ~/.transsnip/settings.json elsewhere."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.transsnip")
    path = Path(base) / "transsnip" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class HotkeySettings(BaseModel):
    """Global hotkey bindings.

    Format follows the `keyboard` Python library: lowercase, `+`-separated,
    modifiers first (e.g. `ctrl+shift+t`, `alt+f`). The Settings UI uses
    `QKeySequenceEdit` for input and normalizes its output to this format.
    Empty string disables the binding for that action.
    """

    region_translate: str = "alt+t"
    fullscreen_translate: str = "alt+f"
    video_subtitle_translate: str = "alt+v"


class TranslateSettings(BaseModel):
    """User choices for the translation layer.

    API keys are NOT stored here — they live in keyring (see `keyring_store.py`).
    This file is plaintext JSON checked into nothing sensitive.
    """

    provider: str = "google_free"  # default: works without an API key
    target_lang: str = "vi"
    source_lang: str | None = None  # None → provider auto-detects
    preset_name: str = "default"
    openrouter_model: str = "google/gemini-2.0-flash-001"


class PresetSettings(BaseModel):
    """A named translation context — system prompt + glossary applied on top of
    whichever provider is active.

    Why a separate object instead of inline strings on `TranslateSettings`:
    - User wants to switch quickly between "Gaming", "Programming", "News"
      tones without rewriting the prompt every time.
    - LLM providers (Claude/OpenRouter/Gemini) consume `ctx.system_prompt` +
      `ctx.glossary` already (see `_build_system_prompt` in each); the preset
      just feeds those fields.
    - Non-LLM providers (Google Free) apply the glossary as a post-process
      replace and ignore the system prompt — also handled in `google_free.py`.

    `description` is shown in the picker so the user can remember what each
    preset is for; it doesn't reach the provider.
    """

    name: str = "default"
    description: str = ""
    system_prompt: str = ""
    glossary: dict[str, str] = Field(default_factory=dict)


def _default_presets() -> list[PresetSettings]:
    """Ship 3 starter presets so a fresh install has something useful to try.

    Users can edit / delete these in Settings → Context. Built-ins aren't
    pinned — once edited they become "user" presets and persist as-is.
    """
    return [
        PresetSettings(
            name="default",
            description="Bản dịch thông thường, không có instruction đặc biệt.",
        ),
        PresetSettings(
            name="programming",
            description="Tài liệu kỹ thuật, code, API docs — giữ thuật ngữ Anh.",
            system_prompt=(
                "You are translating technical documentation or source code "
                "context. Keep code identifiers, library names, framework names, "
                "and standard programming terms (function, class, variable, API, "
                "endpoint, etc.) in English. Use natural Vietnamese for the prose."
            ),
            glossary={"function": "hàm", "library": "thư viện", "class": "lớp"},
        ),
        PresetSettings(
            name="gaming",
            description="Hội thoại / UI game — giữ tên skill, item, nhân vật.",
            system_prompt=(
                "You are translating in-game dialogue or UI. Keep proper nouns, "
                "character names, skill names, item names, and game-specific "
                "stats (HP, MP, DPS, etc.) in their original form. Use casual, "
                "natural Vietnamese tone."
            ),
            glossary={"HP": "máu", "MP": "mana", "DPS": "sát thương/giây"},
        ),
    ]


class Settings(BaseModel):
    """Top-level settings. New tabs (display, voice) become new sub-models here."""

    translate: TranslateSettings = Field(default_factory=TranslateSettings)
    hotkeys: HotkeySettings = Field(default_factory=HotkeySettings)
    presets: list[PresetSettings] = Field(default_factory=_default_presets)
    schema_version: int = 3  # bump when migrating settings.json shape


def get_preset(settings: Settings, name: str) -> PresetSettings:
    """Return the preset with `name`, or a blank fallback if missing.

    Returning a fallback (instead of raising) means a stale `preset_name` in
    settings.json — pointing at a preset the user deleted — degrades to plain
    translation instead of crashing the popup.
    """
    for preset in settings.presets:
        if preset.name == name:
            return preset
    log.warning("Preset %r not found, falling back to empty context", name)
    return PresetSettings(name=name)


def load_settings() -> Settings:
    path = _settings_path()
    if not path.exists():
        log.info("No settings file at %s — using defaults", path)
        return Settings()
    try:
        raw = path.read_text(encoding="utf-8")
        return Settings.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to parse %s: %s — falling back to defaults", path, exc)
        return Settings()


def save_settings(settings: Settings) -> None:
    path = _settings_path()
    try:
        path.write_text(
            json.dumps(settings.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Saved settings to %s", path)
    except OSError as exc:
        log.error("Failed to write %s: %s", path, exc)
