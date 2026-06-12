"""Translation history — a small, capped, JSON-backed log of recent results.

Lets the user re-open something they translated a minute ago without re-snipping
(and replay the TTS for English source). Deliberately tiny:
- Append-only with a cap (oldest entries fall off) so the file never balloons.
- Newest-first in memory for cheap "show recent N".
- Consecutive exact-duplicate translations are collapsed (re-translating the same
  popup text shouldn't spam the list).

Stored at %APPDATA%/transsnip/history.json — same dir as settings.json. It holds
translated text the user already saw on screen, nothing secret (API keys stay in
keyring), so plain JSON is fine.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_MAX_ENTRIES = 200


def _history_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.transsnip")
    path = Path(base) / "transsnip" / "history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class HistoryEntry(BaseModel):
    source_text: str
    translated_text: str
    source_lang: str = "auto"
    target_lang: str = "vi"
    provider: str = ""
    timestamp: str = ""  # ISO-8601; stamped by the caller (datetime.now().isoformat())


class HistoryStore:
    """In-memory list (newest first) mirrored to a JSON file."""

    def __init__(self, path: Path | None = None, *, max_entries: int = _MAX_ENTRIES) -> None:
        self._path = path or _history_path()
        self._max = max_entries
        self._entries: list[HistoryEntry] = self._load()

    def _load(self) -> list[HistoryEntry]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [HistoryEntry.model_validate(e) for e in data][: self._max]
        except Exception as exc:  # noqa: BLE001 — corrupt history must not crash app
            log.warning("Failed to load history (%s) — starting empty", exc)
            return []

    def add(self, entry: HistoryEntry) -> None:
        """Insert `entry` at the front, collapsing a consecutive duplicate."""
        if self._entries and (
            self._entries[0].source_text == entry.source_text
            and self._entries[0].translated_text == entry.translated_text
        ):
            return
        self._entries.insert(0, entry)
        del self._entries[self._max:]
        self._save()

    def recent(self, n: int | None = None) -> list[HistoryEntry]:
        return list(self._entries[:n]) if n else list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self._save()

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps([e.model_dump() for e in self._entries], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.error("Failed to write history %s: %s", self._path, exc)
