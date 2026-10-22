from __future__ import annotations

import logging

from PIL import Image

from transsnip.ocr.base import OCREngine, OCRError, OCRResult
from transsnip.ocr.rapid_ocr import RapidOCREngine
from transsnip.ocr.windows_ocr import WindowsOCR

log = logging.getLogger(__name__)


def _lang_matches(requested: str, available: set[str]) -> bool:
    """BCP-47 primary-subtag match.

    Returns True if `requested` matches any tag in `available` either exactly
    (case-insensitive) or by primary subtag. e.g. requested="en" matches
    available={"en-US"}, requested="zh-Hans" matches available={"zh-CN"}
    only by primary subtag "zh".

    Why this matters: Windows OCR reports installed packs in their full
    regional form ("en-US", "ja-JP", "vi-VN"). The Settings combo stores
    primary subtags ("en", "ja", "vi"). Without this normalisation the
    pipeline filters Windows OCR out as if it didn't speak the language
    the user picked.
    """
    requested_lc = requested.lower()
    requested_primary = requested_lc.split("-")[0]
    for tag in available:
        tag_lc = tag.lower()
        if tag_lc == requested_lc:
            return True
        if tag_lc.split("-")[0] == requested_primary:
            return True
    return False


class OCRPipeline:
    """Tries OCR engines in priority order, falling back if one is unavailable or fails.

    "Fails" includes raising OCRError or returning an empty result — both signal that
    we should try the next engine. Only the first engine to produce non-empty text wins.
    """

    def __init__(self, engines: list[OCREngine]) -> None:
        if not engines:
            raise ValueError("OCRPipeline needs at least one engine")
        self._engines = engines

    def engines(self) -> list[OCREngine]:
        return list(self._engines)

    def _serves(self, engine: OCREngine, lang: str | None) -> bool:
        if not engine.is_available():
            return False
        if not lang:
            return True
        supported = engine.supported_languages()
        # Match BCP-47 by PRIMARY SUBTAG so "en" picks up an "en-US" OCR pack
        # (and vice-versa). Without this, Windows OCR — which reports installed
        # packs as "en-US" / "ja-JP" / "vi-VN" — gets filtered out the moment
        # the user picks "en" in Settings, even though it handles it fine.
        return not supported or _lang_matches(lang, supported)

    def warm_up(self, lang: str | None = None) -> None:
        """Warm the engine that will serve `lang` first. Best-effort; blocking —
        call it off the GUI thread."""
        for engine in self._engines:
            if self._serves(engine, lang):
                try:
                    engine.warm_up(lang)
                except Exception as exc:  # noqa: BLE001 — warm-up must never surface
                    log.debug("OCR warm-up of %s failed: %s", engine.name, exc)
                return

    def recognize(self, image: Image.Image, lang: str | None = None) -> OCRResult:
        last_err: Exception | None = None
        attempted: list[str] = []
        for engine in self._engines:
            if not self._serves(engine, lang):
                log.debug("Skip engine %s for lang %r (unavailable/unsupported)", engine.name, lang)
                continue
            attempted.append(engine.name)
            try:
                result = engine.recognize(image, lang)
            except OCRError as exc:
                log.warning("Engine %s raised: %s", engine.name, exc)
                last_err = exc
                continue
            if result.text.strip():
                log.info("OCR success via %s (%d blocks)", engine.name, len(result.blocks))
                return result
            log.debug("Engine %s returned empty — trying next", engine.name)
        if last_err is None:
            # Every engine ran fine and simply saw no text — not a failure of
            # ours, so the popup says so plainly instead of dumping internals.
            raise OCRError(NO_TEXT_FOUND)
        raise OCRError(
            f"No engine produced text. Tried: {attempted}. Last error: {last_err}"
        )


NO_TEXT_FOUND = "no text found in the selected region"

PRIMARY_ENGINES = ("rapid", "windows")


def default_pipeline(primary: str = "rapid") -> OCRPipeline:
    """Build the standard pipeline for TransSnip.

    Default order: RapidOCR (bundled PP-OCRv6) first, Windows OCR as fallback.
    Measured with scripts/ocr_bench.py on zh/en/ja captures:
    - RapidOCR: ~0% CER on nearly every case — subtitles of every style, game
      UI, dark mode, Traditional Chinese, CJK+Latin mixes — at 20-110 ms per
      region. One multilingual model, so "auto" source language costs nothing
      extra and reads Chinese correctly.
    - Windows OCR: 3-5x faster on clean UI text, but 90%+ CER on yellow /
      shadow-only subtitles, ~17% on game UI, and in auto mode its Japanese pack
      "wins" Chinese captures with garbage (17-56% CER). Garbage is non-empty,
      so the pipeline never fell through to RapidOCR while Windows went first.
    Windows still serves anything RapidOCR can't (missing models, languages it
    lacks). `primary="windows"` restores the old speed-first order.

    Each engine is tried in order; the first one to return non-empty text wins.
    """
    engines: list[OCREngine] = [RapidOCREngine(), WindowsOCR()]
    if primary == "windows":
        engines.reverse()
    return OCRPipeline(engines)
