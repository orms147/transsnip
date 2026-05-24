from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import OrderedDict
from dataclasses import asdict, replace
from pathlib import Path

from transsnip.translate.base import TranslationContext, TranslationResult, WordInfo

log = logging.getLogger(__name__)


def _cache_dir() -> Path:
    """Per-user cache root. On Windows: `%APPDATA%\\transsnip\\translate-cache\\`."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.transsnip")
    path = Path(base) / "transsnip" / "translate-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _make_key(text: str, ctx: TranslationContext, provider: str) -> str:
    """Hash the full request shape so two translations only collide when they would
    produce identical output (same text, same target lang, same context, same provider).
    """
    payload = {
        "v": 1,  # bump if cache schema changes
        "text": text,
        "source_lang": ctx.source_lang,
        "target_lang": ctx.target_lang,
        "preset": ctx.preset_name,
        "system_prompt": ctx.system_prompt,
        "glossary": sorted(ctx.glossary.items()),
        "want_word_breakdown": ctx.want_word_breakdown,
        "provider": provider,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _result_from_dict(data: dict) -> TranslationResult:
    raw_words = data.get("words")
    words = (
        [WordInfo(**w) for w in raw_words]
        if isinstance(raw_words, list)
        else None
    )
    return TranslationResult(
        source_text=data["source_text"],
        translated_text=data["translated_text"],
        source_lang=data["source_lang"],
        target_lang=data["target_lang"],
        provider=data["provider"],
        cached=False,  # `cached=True` is applied by `.get()` on retrieval
        words=words,
    )


class TranslationCache:
    """Two-tier cache: in-memory LRU on the hot path, disk JSON for cross-restart persistence.

    Memory layer is a bounded `OrderedDict`; disk layer is one file per cache key under
    `%APPDATA%/transsnip/translate-cache/`. Both layers store the same shape — disk is
    just the cold path.
    """

    def __init__(self, *, mem_size: int = 256) -> None:
        self._mem: OrderedDict[str, TranslationResult] = OrderedDict()
        self._mem_size = mem_size
        self._dir = _cache_dir()

    def get(
        self, text: str, ctx: TranslationContext, provider: str
    ) -> TranslationResult | None:
        key = _make_key(text, ctx, provider)
        if key in self._mem:
            self._mem.move_to_end(key)
            log.debug("Cache HIT (mem) %s", key[:12])
            return replace(self._mem[key], cached=True)

        path = self._dir / f"{key}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result = _result_from_dict(data)
            except (OSError, KeyError, ValueError) as exc:
                log.warning("Corrupt cache %s: %s — deleting", key[:12], exc)
                path.unlink(missing_ok=True)
                return None
            self._store_mem(key, result)
            log.debug("Cache HIT (disk) %s", key[:12])
            return replace(result, cached=True)

        log.debug("Cache MISS %s", key[:12])
        return None

    def put(
        self,
        text: str,
        ctx: TranslationContext,
        provider: str,
        result: TranslationResult,
    ) -> None:
        key = _make_key(text, ctx, provider)
        self._store_mem(key, result)
        path = self._dir / f"{key}.json"
        try:
            data = asdict(result)
            data.pop("cached", None)  # caller-side flag, not part of the persisted payload
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("Failed to persist cache %s: %s", key[:12], exc)

    def _store_mem(self, key: str, result: TranslationResult) -> None:
        if key in self._mem:
            self._mem.move_to_end(key)
            return
        self._mem[key] = result
        if len(self._mem) > self._mem_size:
            self._mem.popitem(last=False)
