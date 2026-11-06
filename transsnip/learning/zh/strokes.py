"""Chinese stroke-order data (Make Me a Hanzi) — on-demand download + SQLite lookup.

The raw graphics.txt is ~30 MB of JSON lines; we fetch it once, verify a pinned
sha256 (the URL is pinned to a commit, so the hash never drifts), and index it
into SQLite so a lookup costs one primary-key read instead of a 30 MB scan.
No Qt here: the download runs on a worker thread and tests stay headless.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from transsnip.utils.paths import app_data_dir

GRAPHICS_URL = (
    "https://raw.githubusercontent.com/skishore/makemeahanzi/"
    "bddc96d41bef78427ed0e034e9f7e31d71fd1b92/graphics.txt"
)
GRAPHICS_SHA256 = "a28c478b5178e98f67f510b2d52fde08a69dc664654ef43498253b9b764d46ee"
ATTRIBUTION = (
    "Dữ liệu cách viết: Make Me a Hanzi (github.com/skishore/makemeahanzi), "
    "Arphic Public License."
)
DB_NAME = "zh-strokes.sqlite3"
_CHUNK = 1 << 16


class StrokeDataError(RuntimeError):
    """Download/verification failure — message is user-facing (Vietnamese)."""


@dataclass(frozen=True)
class CharStrokes:
    strokes: list[str]  # SVG path strings, 1024 box, Y up
    medians: list[list[tuple[int, int]]]


def db_path() -> Path:
    return app_data_dir() / DB_NAME


class StrokeStore:
    """Read-only, thread-safe lookup over the indexed stroke DB."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path or db_path()

    def available(self) -> bool:
        return self.path.is_file()

    def get(self, char: str) -> CharStrokes | None:
        if not char or not self.available():
            return None
        with self._lock:
            try:
                if self._conn is None:
                    uri = self.path.resolve().as_uri() + "?mode=ro"
                    self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
                row = self._conn.execute(
                    "SELECT data FROM strokes WHERE char = ?", (char[0],)
                ).fetchone()
            except sqlite3.Error:
                self._close_locked()
                return None
        if row is None:
            return None
        obj = json.loads(row[0])
        return CharStrokes(
            strokes=list(obj["strokes"]),
            medians=[[(int(p[0]), int(p[1])) for p in m] for m in obj["medians"]],
        )

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def remove(self) -> None:
        """Delete the DB (Settings → "Xoá dữ liệu cách viết")."""
        self.close()
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def download(
    progress: Callable[[int, int], None] | None = None,
    *,
    url: str = GRAPHICS_URL,
    sha256: str = GRAPHICS_SHA256,
    dest: Path | None = None,
) -> None:
    """Fetch, verify and index graphics.txt. Blocking — call off the GUI thread.

    `progress(done_bytes, total_bytes)`; total is 0 when the server omits it.
    """
    dest = dest or db_path()
    tmp = dest.with_name(dest.name + ".download")
    part = dest.with_name(dest.name + ".part")
    try:
        _fetch(url, tmp, sha256, progress)
        _build_db(tmp, part)
        os.replace(part, dest)
    finally:
        for p in (tmp, part):
            with contextlib.suppress(OSError):
                p.unlink()


def remove(dest: Path | None = None) -> None:
    with contextlib.suppress(FileNotFoundError):
        (dest or db_path()).unlink()


def _fetch(
    url: str, out: Path, sha256: str, progress: Callable[[int, int], None] | None
) -> None:
    h = hashlib.sha256()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TransSnip"})
        with urllib.request.urlopen(req, timeout=30) as resp, out.open("wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(_CHUNK):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as e:  # URLError, timeouts and disk errors all derive from OSError
        raise StrokeDataError(f"Không tải được dữ liệu cách viết: {e}") from e
    if h.hexdigest() != sha256.lower():
        raise StrokeDataError("Dữ liệu cách viết tải về bị lỗi (sai mã kiểm tra sha256).")


def _build_db(src: Path, part: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        part.unlink()
    conn = sqlite3.connect(part)
    try:
        conn.execute("CREATE TABLE strokes(char TEXT PRIMARY KEY, data TEXT)")
        with src.open(encoding="utf-8") as f:
            conn.executemany(
                "INSERT OR REPLACE INTO strokes VALUES (?, ?)", _rows(f)
            )
        conn.commit()
    finally:
        conn.close()


def _rows(lines):
    for line in lines:
        try:
            obj = json.loads(line)
            ch, strokes, medians = obj["character"], obj["strokes"], obj["medians"]
        except (ValueError, KeyError, TypeError):
            continue  # one malformed line shouldn't sink the whole dataset
        if ch and strokes and len(strokes) == len(medians):
            data = json.dumps({"strokes": strokes, "medians": medians}, ensure_ascii=False)
            yield ch, data
