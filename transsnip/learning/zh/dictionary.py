"""Offline lookups over resources/zh/zh.sqlite (built by scripts/fetch_zh_data.py).

- Word meanings (Vietnamese, CVDICT) by simplified or traditional form.
- Hán-Việt per character, chosen by the reading IN CONTEXT: 长 in 董事长
  (zhǎng) is "trưởng", in 长城 (cháng) "trường"; 行 háng → "hàng", xíng →
  "hành". Fallbacks: the character's common reading, then Thiều Chửu's first.
- Character anatomy (radical, components, etymology hint) and HSK 3.0 level.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from transsnip.learning.zh.text import Syllable, Token, is_han


def data_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else Path(__file__).resolve().parents[3]
    return base / "resources" / "zh" / "zh.sqlite"


def available() -> bool:
    return data_path().exists()


@dataclass(frozen=True)
class DictEntry:
    simp: str
    trad: str
    pinyin: str                 # CEDICT numbered, e.g. "shi2 xi2"
    meanings: tuple[str, ...]


@dataclass(frozen=True)
class CharInfo:
    char: str
    hanviet: str                # reading used in this context (or primary)
    hanviet_all: str            # every known reading, comma-separated
    radical: str = ""
    decomposition: str = ""     # IDS, e.g. "⿰女子"
    etym_type: str = ""         # pictographic / ideographic / pictophonetic
    etym_hint: str = ""
    meanings: tuple[str, ...] = ()


class ZhDict:
    """Thread-safe, read-only. Open lazily; every query is a few µs-ms."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or data_path()
        self._db: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _q(self, sql: str, args: tuple) -> list[tuple]:
        with self._lock:
            if self._db is None:
                uri = f"file:{self._path.as_posix()}?mode=ro"
                self._db = sqlite3.connect(uri, uri=True, check_same_thread=False)
            return self._db.execute(sql, args).fetchall()

    # ── words ────────────────────────────────────────────────────────────
    def lookup(self, word: str) -> list[DictEntry]:
        rows = self._q("SELECT simp, trad, pinyin, vi FROM words WHERE simp=? OR trad=?",
                       (word, word))
        return [DictEntry(s, t, p, tuple(m for m in v.split("/") if m)) for s, t, p, v in rows]

    def hsk_level(self, word: str) -> int | None:
        rows = self._q("SELECT level FROM hsk WHERE word=?", (word,))
        return rows[0][0] if rows else None

    # ── Hán-Việt ─────────────────────────────────────────────────────────
    def hanviet_for(self, char: str, numbered_pinyin: str = "") -> str:
        """Reading for `char` as pronounced `numbered_pinyin` ("zhang3")."""
        if numbered_pinyin:
            best = self._q("SELECT reading FROM hv_best WHERE char=? AND pinyin=?",
                           (char, numbered_pinyin.lower()))
            if best and best[0][0]:
                return best[0][0]
        # Pronunciation unknown to the table (e.g. 一 after tone sandhi "yi2"):
        # fall back to the character's common reading.
        rows = self._q("SELECT primary_reading, all_readings FROM hvchar WHERE char=?", (char,))
        if not rows:
            return ""
        primary, every = rows[0]
        return (primary or every.split(",")[0]).strip()

    def hanviet_all(self, char: str) -> str:
        rows = self._q("SELECT all_readings, primary_reading FROM hvchar WHERE char=?", (char,))
        return (rows[0][0] or rows[0][1]) if rows else ""

    def token_hanviet(self, token: Token) -> str:
        """"董事长" (dǒng shì zhǎng) → "đổng sự trưởng"; non-Han chars pass through."""
        return " ".join(self._syllable_hv(s) for s in token.syllables if s.tone)

    def _syllable_hv(self, s: Syllable) -> str:
        return self.hanviet_for(s.char, s.numbered) or s.char

    # ── characters ───────────────────────────────────────────────────────
    def char_info(self, s: Syllable) -> CharInfo:
        rows = self._q("SELECT radical, decomposition, etym_type, etym_hint FROM chars "
                       "WHERE char=?", (s.char,))
        radical, decomp, etype, hint = rows[0] if rows else ("", "", "", "")
        meanings: tuple[str, ...] = ()
        # Exact-case pinyin first: "dong3" (common word) before "Dong3" (surname).
        entries = sorted(self.lookup(s.char), key=lambda e: e.pinyin != s.numbered)
        for e in entries:
            if not s.numbered or e.pinyin.lower() == s.numbered:
                meanings = e.meanings
                break
        return CharInfo(
            char=s.char, hanviet=self._syllable_hv(s), hanviet_all=self.hanviet_all(s.char),
            radical=radical, decomposition=decomp if decomp != "？" else "",
            etym_type=etype, etym_hint=hint, meanings=meanings,
        )


@lru_cache(maxsize=1)
def shared() -> ZhDict:
    return ZhDict()


def sentence_hanviet(tokens: list[Token], zd: ZhDict | None = None) -> str:
    """Whole-sentence Hán-Việt reading, words separated by spaces and
    punctuation kept: "实习不久，老董事长" → "thực tập bất cửu, lão đổng sự trưởng"."""
    zd = zd or shared()
    parts: list[str] = []
    for t in tokens:
        if t.is_word:
            parts.append(zd.token_hanviet(t))
        elif t.text.strip():
            mapped = t.text.translate(_PUNCT)
            if parts and mapped and not any(is_han(c) for c in mapped):
                parts[-1] += mapped if mapped in _ATTACH else f" {mapped}"
            else:
                parts.append(mapped)
    return " ".join(p for p in parts if p).replace("  ", " ")


# Full-width CJK punctuation → Latin, so the reading looks like Vietnamese text.
_PUNCT = str.maketrans({"，": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";",
                        "、": ",", "（": "(", "）": ")", "“": "\"", "”": "\""})
_ATTACH = {",", ".", "!", "?", ":", ";", ")"}
