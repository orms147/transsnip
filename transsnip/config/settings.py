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


class Settings(BaseModel):
    """Top-level settings. New tabs (hotkeys, display, voice) become new sub-models here."""

    translate: TranslateSettings = Field(default_factory=TranslateSettings)
    schema_version: int = 1  # bump when migrating settings.json shape


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
