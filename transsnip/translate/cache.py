"""Translation cache: in-memory LRU in front of a single bounded SQLite file.

Why SQLite instead of one JSON file per key: video-subtitle mode translates every new
subtitle line, so the old layout grew to thousands of tiny files that were never
evicted and made NTFS + antivirus scanning slow. One DB file with a row cap keeps
disk usage bounded and lookups O(log n).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import shutil
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, replace
from pathlib import Path

from transsnip.translate.base import TranslationContext, TranslationResult, WordInfo
from transsnip.utils.paths import app_data_dir

log = logging.getLogger(__name__)

_DB_NAME = "translate-cache.sqlite3"
_LEGACY_DIR_NAME = "translate-cache"
# Prune only every N puts: a COUNT + DELETE per put would dominate subtitle-mode writes.
_PRUNE_EVERY = 200


def _db_path() -> Path:
    """On Windows: `%APPDATA%\\transsnip\\translate-cache.sqlite3`."""
    return app_data_dir() / _DB_NAME


def _remove_legacy_dir() -> None:
    """Drop the old one-JSON-per-key directory. Not imported: entries are cheap to
    regenerate and importing thousands of files at startup would cost more than it saves.
    Best-effort — a locked file just leaves the leftovers for the next launch.
    """
    legacy = app_data_dir() / _LEGACY_DIR_NAME
    if legacy.is_dir():
        shutil.rmtree(legacy, ignore_errors=True)
        log.info("Removed legacy translation cache dir %s", legacy)


def _make_key(text: str, ctx: TranslationContext, provider: str) -> str:
    """Hash the full request shape so two translations only collide when they would
    produce identical output (same text, same target lang, same context, same provider).
    """
    payload = {
        # bump if cache schema changes — or to drop bad entries: v2 discards
        # pre-2026-10 LLM results that echoed the source language untranslated.
        "v": 2,
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
    """Two-tier cache: in-memory LRU on the hot path, SQLite for cross-restart persistence.

    Disk layer is one table `(key PK, payload JSON, last_used)`, capped at `max_rows`
    (oldest `last_used` pruned). Threading: get/put run on QThreadPool workers and the
    subtitle QThreads concurrently, so one connection (`check_same_thread=False`) is
    shared behind a single lock — writes are tiny, contention is negligible, and it
    avoids per-thread connections fighting over the WAL. Any sqlite error disables the
    disk layer (memory-only) rather than surfacing to callers: a cache must never break
    translation.
    """

    def __init__(self, *, mem_size: int = 256, max_rows: int = 20_000) -> None:
        self._mem: OrderedDict[str, TranslationResult] = OrderedDict()
        self._mem_size = mem_size
        self._max_rows = max_rows
        self._lock = threading.Lock()
        self._puts_since_prune = 0
        try:
            _remove_legacy_dir()
        except OSError as exc:
            log.warning("Could not remove legacy cache dir: %s", exc)
        self._conn: sqlite3.Connection | None = self._open_db()

    # ---- disk layer -------------------------------------------------------

    def _open_db(self) -> sqlite3.Connection | None:
        try:
            path = _db_path()
        except OSError as exc:
            log.warning("Translation cache dir unavailable (%s) — memory-only", exc)
            return None
        try:
            return self._connect(path)
        except sqlite3.DatabaseError as exc:
            # Corrupt/non-DB file: move aside so the user's data isn't silently destroyed
            # and start fresh.
            log.warning("Translation cache DB unusable (%s) — moving aside", exc)
            try:
                path.replace(path.with_name(path.name + ".corrupt"))
                for suffix in ("-wal", "-shm"):
                    path.with_name(path.name + suffix).unlink(missing_ok=True)
                return self._connect(path)
            except (OSError, sqlite3.Error) as exc2:
                log.warning("Translation cache disabled — memory-only: %s", exc2)
                return None

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        try:
            # quick_check forces a real page read, so a garbage file fails here, not later.
            conn.execute("PRAGMA quick_check").fetchone()
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS translations ("
                " key TEXT PRIMARY KEY,"
                " payload TEXT NOT NULL,"
                " last_used INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_translations_last_used"
                " ON translations(last_used)"
            )
            conn.commit()
        except sqlite3.Error:
            conn.close()
            raise
        return conn

    def _disable_disk(self, exc: Exception) -> None:
        """Caller holds the lock."""
        log.warning("Translation cache DB error (%s) — falling back to memory-only", exc)
        if self._conn is not None:
            with contextlib.suppress(sqlite3.Error):
                self._conn.close()
        self._conn = None

    def _prune(self) -> None:
        """Caller holds the lock. Keep only the newest `max_rows` by last_used."""
        assert self._conn is not None
        (count,) = self._conn.execute("SELECT COUNT(*) FROM translations").fetchone()
        excess = count - self._max_rows
        if excess > 0:
            self._conn.execute(
                "DELETE FROM translations WHERE key IN ("
                " SELECT key FROM translations ORDER BY last_used ASC, rowid ASC LIMIT ?)",
                (excess,),
            )
            log.debug("Pruned %d cache rows", excess)

    # ---- public API -------------------------------------------------------

    def get(
        self, text: str, ctx: TranslationContext, provider: str
    ) -> TranslationResult | None:
        key = _make_key(text, ctx, provider)
        with self._lock:
            if key in self._mem:
                # No last_used touch here: a mem hit implies a recent put/disk-hit already
                # stamped the row, and a write per hot-path hit would be wasteful.
                self._mem.move_to_end(key)
                log.debug("Cache HIT (mem) %s", key[:12])
                return replace(self._mem[key], cached=True)

            if self._conn is None:
                return None
            try:
                row = self._conn.execute(
                    "SELECT payload FROM translations WHERE key = ?", (key,)
                ).fetchone()
                if row is None:
                    log.debug("Cache MISS %s", key[:12])
                    return None
                try:
                    result = _result_from_dict(json.loads(row[0]))
                except (KeyError, TypeError, ValueError) as exc:
                    log.warning("Corrupt cache row %s: %s — deleting", key[:12], exc)
                    self._conn.execute("DELETE FROM translations WHERE key = ?", (key,))
                    self._conn.commit()
                    return None
                self._conn.execute(
                    "UPDATE translations SET last_used = ? WHERE key = ?",
                    (int(time.time()), key),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                self._disable_disk(exc)
                return None
            self._store_mem(key, result)
            log.debug("Cache HIT (disk) %s", key[:12])
            return replace(result, cached=True)

    def put(
        self,
        text: str,
        ctx: TranslationContext,
        provider: str,
        result: TranslationResult,
    ) -> None:
        key = _make_key(text, ctx, provider)
        data = asdict(result)
        data.pop("cached", None)  # caller-side flag, not part of the persisted payload
        payload = json.dumps(data, ensure_ascii=False)
        with self._lock:
            self._store_mem(key, result)
            if self._conn is None:
                return
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO translations (key, payload, last_used)"
                    " VALUES (?, ?, ?)",
                    (key, payload, int(time.time())),
                )
                self._puts_since_prune += 1
                if self._puts_since_prune >= _PRUNE_EVERY:
                    self._puts_since_prune = 0
                    self._prune()
                self._conn.commit()
            except sqlite3.Error as exc:
                self._disable_disk(exc)

    def _store_mem(self, key: str, result: TranslationResult) -> None:
        """Caller holds the lock."""
        if key in self._mem:
            self._mem.move_to_end(key)
            self._mem[key] = result
            return
        self._mem[key] = result
        if len(self._mem) > self._mem_size:
            self._mem.popitem(last=False)
