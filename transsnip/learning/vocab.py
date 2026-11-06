"""Vocabulary notebook ("Sổ từ") with spaced-repetition review.

Words saved from the word card keep the sentence they were snipped from —
seeing a word again in its original context is what makes it stick. Review
uses a trimmed SM-2 (the algorithm behind Anki's defaults): each answer
(again / hard / good / easy) updates an ease factor and the next interval.

Stored in `%APPDATA%\\transsnip\\vocab.sqlite3`; `export_anki_tsv()` writes a
tab-separated file Anki imports directly (File → Import).
"""
from __future__ import annotations

import csv
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from transsnip.utils.paths import app_data_dir

_DAY = 86_400
# SM-2 knobs (Anki defaults): new cards start at ease 2.5, never below 1.3.
_START_EASE = 2.5
_MIN_EASE = 1.3
GRADES = ("again", "hard", "good", "easy")


@dataclass(frozen=True)
class VocabEntry:
    word: str
    pinyin: str = ""
    hanviet: str = ""
    meaning: str = ""
    example: str = ""          # the sentence it was snipped from
    example_vi: str = ""       # its translation
    lang: str = "zh"
    added_at: int = 0
    due_at: int = 0
    interval_days: float = 0.0
    ease: float = _START_EASE
    reps: int = 0
    lapses: int = 0


def schedule(entry: VocabEntry, grade: str, now: int | None = None) -> VocabEntry:
    """Next state after answering `grade` (SM-2, simplified like Anki)."""
    now = int(now if now is not None else time.time())
    ease, interval, reps, lapses = entry.ease, entry.interval_days, entry.reps, entry.lapses
    if grade == "again":
        lapses += 1
        reps = 0
        ease = max(_MIN_EASE, ease - 0.2)
        interval = 0.0          # see it again in this session (10 min)
        due = now + 600
    else:
        reps += 1
        if reps == 1:
            interval = 1.0 if grade != "easy" else 4.0
        elif reps == 2:
            interval = 3.0 if grade != "easy" else 6.0
        else:
            factor = {"hard": 1.2, "good": ease, "easy": ease * 1.3}[grade]
            interval = max(interval + 1, interval * factor)
        ease = max(_MIN_EASE, ease + {"hard": -0.15, "good": 0.0, "easy": 0.15}[grade])
        due = now + int(interval * _DAY)
    return VocabEntry(**{**entry.__dict__, "ease": ease, "interval_days": interval,
                         "reps": reps, "lapses": lapses, "due_at": due})


class VocabStore:
    """Thread-safe SQLite notebook. One row per (lang, word)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or app_data_dir() / "vocab.sqlite3"
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self._path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS vocab (
                lang TEXT NOT NULL, word TEXT NOT NULL, pinyin TEXT, hanviet TEXT,
                meaning TEXT, example TEXT, example_vi TEXT, added_at INTEGER,
                due_at INTEGER, interval_days REAL, ease REAL, reps INTEGER,
                lapses INTEGER, PRIMARY KEY (lang, word))"""
        )
        self._db.commit()

    _COLS = ("word", "pinyin", "hanviet", "meaning", "example", "example_vi", "lang",
             "added_at", "due_at", "interval_days", "ease", "reps", "lapses")

    def _row(self, r: tuple) -> VocabEntry:
        return VocabEntry(**dict(zip(self._COLS, r, strict=True)))

    def add(self, entry: VocabEntry) -> bool:
        """Save a word (due now). Returns False if it was already saved —
        an existing entry keeps its review history; only empty fields fill in."""
        now = int(time.time())
        with self._lock:
            cur = self._db.execute("SELECT 1 FROM vocab WHERE lang=? AND word=?",
                                   (entry.lang, entry.word))
            if cur.fetchone():
                self._db.execute(
                    """UPDATE vocab SET
                         pinyin=COALESCE(NULLIF(pinyin,''),?),
                         hanviet=COALESCE(NULLIF(hanviet,''),?),
                         meaning=COALESCE(NULLIF(meaning,''),?),
                         example=COALESCE(NULLIF(example,''),?),
                         example_vi=COALESCE(NULLIF(example_vi,''),?)
                       WHERE lang=? AND word=?""",
                    (entry.pinyin, entry.hanviet, entry.meaning, entry.example,
                     entry.example_vi, entry.lang, entry.word))
                self._db.commit()
                return False
            e = VocabEntry(**{**entry.__dict__, "added_at": now, "due_at": now})
            cols, marks = ",".join(self._COLS), ",".join("?" * len(self._COLS))
            self._db.execute(f"INSERT INTO vocab ({cols}) VALUES ({marks})",
                             tuple(getattr(e, c) for c in self._COLS))
            self._db.commit()
            return True

    def contains(self, word: str, lang: str = "zh") -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM vocab WHERE lang=? AND word=?",
                                    (lang, word)).fetchone() is not None

    def remove(self, word: str, lang: str = "zh") -> None:
        with self._lock:
            self._db.execute("DELETE FROM vocab WHERE lang=? AND word=?", (lang, word))
            self._db.commit()

    def all(self, lang: str = "zh") -> list[VocabEntry]:
        with self._lock:
            rows = self._db.execute(
                f"SELECT {','.join(self._COLS)} FROM vocab WHERE lang=? ORDER BY added_at DESC",
                (lang,)).fetchall()
        return [self._row(r) for r in rows]

    def due(self, lang: str = "zh", now: int | None = None, limit: int = 50) -> list[VocabEntry]:
        now = int(now if now is not None else time.time())
        with self._lock:
            rows = self._db.execute(
                f"SELECT {','.join(self._COLS)} FROM vocab WHERE lang=? AND due_at<=? "
                "ORDER BY due_at LIMIT ?", (lang, now, limit)).fetchall()
        return [self._row(r) for r in rows]

    def answer(self, entry: VocabEntry, grade: str, now: int | None = None) -> VocabEntry:
        nxt = schedule(entry, grade, now)
        with self._lock:
            self._db.execute(
                "UPDATE vocab SET due_at=?, interval_days=?, ease=?, reps=?, lapses=? "
                "WHERE lang=? AND word=?",
                (nxt.due_at, nxt.interval_days, nxt.ease, nxt.reps, nxt.lapses,
                 nxt.lang, nxt.word))
            self._db.commit()
        return nxt

    def export_anki_tsv(self, dest: Path, lang: str = "zh") -> int:
        """Front: word · Back: pinyin, Hán-Việt, meaning, example (+translation).
        Returns the number of cards written."""
        entries = self.all(lang)
        with dest.open("w", encoding="utf-8", newline="") as f:
            f.write("#separator:tab\n#html:true\n")
            w = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            for e in entries:
                back = "<br>".join(p for p in (
                    e.pinyin, e.hanviet and f"Hán-Việt: {e.hanviet}", e.meaning,
                    e.example and f"<i>{e.example}</i>", e.example_vi) if p)
                w.writerow([e.word, back])
        return len(entries)
