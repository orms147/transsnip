"""Build the Android app's Chinese dictionary (android/app/src/main/assets/zh.sqlite).

Starts from the desktop database (resources/zh/zh.sqlite, built by
fetch_zh_data.py) and adds what the desktop gets from jieba + pypinyin at
runtime, precomputed here so the phone needs no Python:

  word_py(word, pinyin)  — context-aware numbered pinyin for every dictionary
                           word, with 一/不 tone sandhi ("董事长" → "dong3 shi4
                           zhang3", "一定" → "yi2 ding4"). The phone segments
                           text by dictionary matching and reads each word here.
  char_py(char, pinyin)  — the most common reading of every single character,
                           for characters that end up outside any word.

The unused `hv` table is dropped (hv_best covers it) and the file vacuumed.

    python scripts/build_android_zh.py
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

from pypinyin import Style, lazy_pinyin

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "resources" / "zh" / "zh.sqlite"
DST = ROOT / "android" / "app" / "src" / "main" / "assets" / "zh.sqlite"
NOTICE_SRC = ROOT / "resources" / "zh" / "NOTICE.md"


def is_han(c: str) -> bool:
    return "㐀" <= c <= "鿿" or "豈" <= c <= "﫿"


def numbered(word: str) -> str:
    """pypinyin TONE3 with neutral tone 5 and ü → v (the hv_best key form)."""
    readings = lazy_pinyin(word, style=Style.TONE3, neutral_tone_with_five=True,
                           tone_sandhi=True, errors=lambda s: ["?"] * len(s))
    return " ".join(r.replace("ü", "v") for r in readings)


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC} — run scripts/fetch_zh_data.py first", file=sys.stderr)
        return 1
    DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC, DST)
    db = sqlite3.connect(DST)
    words = {w for (s, t) in db.execute("SELECT simp, trad FROM words") for w in (s, t)
             if w and all(is_han(c) for c in w)}
    chars = {c for w in words for c in w}
    chars |= {c for (c,) in db.execute("SELECT char FROM hvchar") if is_han(c)}

    db.execute("DROP TABLE IF EXISTS hv")
    db.execute("CREATE TABLE word_py (word TEXT PRIMARY KEY, pinyin TEXT)")
    db.execute("CREATE TABLE char_py (char TEXT PRIMARY KEY, pinyin TEXT)")
    db.executemany("INSERT INTO word_py VALUES (?, ?)",
                   ((w, numbered(w)) for w in sorted(words) if len(w) > 1))
    db.executemany("INSERT INTO char_py VALUES (?, ?)", ((c, numbered(c)) for c in sorted(chars)))
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('schema', '1')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    shutil.copyfile(NOTICE_SRC, DST.parent / "NOTICE.md")
    print(f"{DST}: {len(words)} words, {len(chars)} chars, "
          f"{DST.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
