from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


class TranslationError(Exception):
    """Raised when a provider can't produce a translation (network fail, auth, ...)."""


@dataclass(frozen=True)
class WordInfo:
    """Per-word linguistic info, populated only when Learning mode is active."""

    token: str
    ipa: str | None = None
    meaning: str | None = None
    pos: str | None = None  # part of speech: noun / verb / adj / ...


@dataclass(frozen=True)
class TranslationContext:
    """Knobs that influence how text gets translated.

    Caller fills this from current settings + active context preset. The same text
    with a different context (different preset, different glossary, want_word_breakdown
    flag) is a different cache key — the cache layer hashes the whole context, not
    just the text.
    """

    target_lang: str = "vi"  # BCP-47 tag
    source_lang: str | None = None  # None → provider auto-detects
    preset_name: str = "default"
    system_prompt: str = ""  # extra LLM instructions, e.g. domain / tone
    glossary: dict[str, str] = field(default_factory=dict)
    want_word_breakdown: bool = False  # Learning mode (Phase 2)


@dataclass(frozen=True)
class TranslationResult:
    source_text: str
    translated_text: str
    source_lang: str  # what the provider thinks the source was (or echo of ctx.source_lang)
    target_lang: str
    provider: str
    cached: bool = False
    words: list[WordInfo] | None = None  # only present when want_word_breakdown=True


class Translator(ABC):
    """Common interface for every translation backend.

    Implementations must be thread-safe for `translate()` / `translate_image()` —
    they're called from worker threads (see `worker.py`).

    Vision support is opt-in. Providers that override `supports_vision` to True
    must also override `translate_image` to do the actual image → translation.
    The default `translate_image` raises NotImplementedError so callers know to
    fall back to the OCR-then-translate path.
    """

    name: str = "unknown"

    @abstractmethod
    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        """Return a translation result, or raise `TranslationError` to signal failure."""

    def is_available(self) -> bool:
        """Whether the provider can run right now (SDK present, key configured, ...)."""
        return True

    def supports_vision(self) -> bool:
        """True if `translate_image` is implemented. Override in vision-capable providers."""
        return False

    def translate_image(self, image: "Image.Image", ctx: TranslationContext) -> TranslationResult:
        """Single-pass OCR + translate. Skips the OCR layer entirely.

        Vision-capable providers (Gemini Flash, Claude, GPT-4V) override this to
        send the image directly. The default raises so the AppController knows to
        route via the OCR pipeline instead.
        """
        raise NotImplementedError(f"{self.name} doesn't support vision input")
