"""Build the bundled Chinese-study database: resources/zh/zh.sqlite (+ NOTICE.md).

    python scripts/fetch_zh_data.py

Downloads pinned (commit-SHA) source files, verifies SHA-256, and distils
them into one compact SQLite file the app reads offline:

    words(simp, trad, pinyin, vi)        CVDICT — Chinese→Vietnamese, CC BY-SA 4.0
    hv(char, pinyin, readings)           Hán-Việt per pinyin reading (行 háng→hàng,
                                         xíng→hành) — reading column of the
                                         HanViet/zhongwen data (no definitions)
    hvchar(char, primary, all_readings)  phiên âm list (one common reading) +
                                         Thiều Chửu (1942) reading lists
    hv_best(char, pinyin, reading)       the reading to SHOW for that pronunciation
                                         (rules + HV_OVERRIDES, see choose_reading)
    chars(char, radical, decomposition,  Make Me a Hanzi dictionary.txt, LGPL-3.0+
          etym_type, etym_hint)
    hsk(word, level)                     HSK 3.0 (levels 1-6, 7 = band 7-9), MIT

Stroke-order data (Make Me a Hanzi graphics.txt, ~30 MB) is NOT bundled — the
app downloads it on demand when "Cách viết" is enabled (learning/zh/strokes.py).
Run on the build machine before `pyinstaller`; the file is gitignored.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "build" / "zh-src"
OUT_DIR = ROOT / "resources" / "zh"

_GH = "https://raw.githubusercontent.com"
SOURCES: dict[str, tuple[str, str]] = {
    "cvdict": (f"{_GH}/phucbm/xue-hanzi/c1e7610546454e32db2b3332435902bf78181152"
               "/src/data/CVDICT.u8",
               "4dde4b204193efa9c192d7f7daeab1bb579c8ccd7c41ed90d1b6caee22ba0948"),
    "zhongwen": (f"{_GH}/alienngator/zhongwen/1f3dcde08f2bba0adb18d401c82d2377a874a776"
                 "/data/cedict_augmented.u8",
                 "bb97446c0e0c01cef32a96643d03a43fc38fbd81f0aa660e5266ab4b6128ed05"),
    "thieuchuu": (f"{_GH}/ryanphung/chinese-hanviet-cognates/"
                  "5f79922e2223105547e9ad7d2819949dd508407b/inputs/thieuchuu.txt",
                  "8174f19291dad6706b7ab324b21b53e36b8c40108cc32a6e8724dcc24ca7f5cf"),
    "phienam": (f"{_GH}/ryanphung/chinese-hanviet-cognates/"
                "5f79922e2223105547e9ad7d2819949dd508407b/inputs/phienam.txt",
                "4935f951a9968e22a4d9161015698cf3db2e03bb8ac8eaae6e5237cdbf8879c5"),
    "mmah_dict": (f"{_GH}/skishore/makemeahanzi/bddc96d41bef78427ed0e034e9f7e31d71fd1b92"
                  "/dictionary.txt",
                  "744bb05d5b0742e9ee35c37791f94d56a173349b3367569e7ca11e510364d203"),
    "hsk": (f"{_GH}/drkameleon/complete-hsk-vocabulary/"
            "7ac65bf1a6387d35f1ade478906172a19311c7f9/complete.min.json",
            "52d8e64ba65a6db4a38ea34302c6de5df53cdb5145254b25edcbf93b80676434"),
}

# (char, numbered pinyin) → modern standard Hán-Việt, for common characters
# whose source readings are archaic (Thiều Chửu 1942: 實 thật, 本 bổn, 退 thối),
# belong to another character merged in simplification (价 giới, 办 bạn,
# 示 kì, 找 hoa, 杂 tập), or where the first-listed of several is the rarer
# one (采 thải, 占 chiêm, 率 luật). Curated by reviewing every ambiguous
# choice among the 1000 most frequent characters. Both character forms.
HV_OVERRIDES: dict[tuple[str, str], str] = {
    **{(c, "shi2"): "thực" for c in "实實"},
    **{(c, "dang1"): "đương" for c in "当當"},
    ("分", "fen4"): "phận",
    **{(c, "zhong4"): "chủng" for c in "种種"},
    ("相", "xiang4"): "tướng",
    ("教", "jiao1"): "giáo",
    ("任", "ren4"): "nhiệm",
    ("期", "qi1"): "kì",
    **{(c, "hua4"): "hoa" for c in "华華"},
    **{(c, "xian4"): "huyện" for c in "县縣"},
    ("什", "shen2"): "thập",
    **{(c, "dan1"): "đơn" for c in "单單"},
    **{(c, "jia4"): "giá" for c in "价價"},
    **{(c, "ban4"): "biện" for c in "办辦"},
    ("示", "shi4"): "thị",
    ("率", "lv4"): "suất",
    ("般", "ban1"): "ban",
    **{(c, "zhan4"): "chiếm" for c in "占佔"},
    **{(c, "cai3"): "thái" for c in "采採彩"},
    **{(c, "cai4"): "thái" for c in "采採"},
    **{(c, "dou3"): "đẩu" for c in "斗"},
    ("找", "zhao3"): "trảo",
    **{(c, "qian2"): "tiền" for c in "钱錢"},
    **{(c, "jin4"): "tận" for c in "尽盡"},
    ("拿", "na2"): "nã",
    **{(c, "xian3"): "tiển" for c in "鲜鮮"},
    **{(c, "ye2"): "gia" for c in "爷爺"},
    **{(c, "za2"): "tạp" for c in "杂雜"},
    ("探", "tan4"): "thám",
    ("退", "tui4"): "thoái",
    ("否", "pi3"): "bĩ",
    **{(c, "kuo4"): "khuếch" for c in "扩擴"},
    ("本", "ben3"): "bản",
    **{(c, "xie2"): "hiệp" for c in "叶"},
}

NOTICE = """# Chinese study data — sources & licences

The code of TransSnip is MIT. The DATA in `zh.sqlite` (and the stroke data the
app downloads on demand) keeps its original licence:

- **CVDICT** (Chinese→Vietnamese dictionary) © Phong Phan, CC BY-SA 4.0 —
  derived from CC-CEDICT (© MDBG, CC BY-SA 4.0; CEDICT © 1997-98 Paul Denisowski).
  The `words` table is an adapted subset and is distributed under CC BY-SA 4.0.
- **Hán-Việt readings**: readings only (no definitions) from *Hán Việt tự điển*,
  Thiều Chửu (1942), via the HanViet extension data (github.com/alienngator/zhongwen)
  and github.com/ryanphung/chinese-hanviet-cognates (incl. a community phiên âm list).
- **Make Me a Hanzi** (github.com/skishore/makemeahanzi): `dictionary.txt`
  (radicals, decompositions, etymology hints) LGPL-3.0-or-later; stroke graphics
  (downloaded on demand) derived from Arphic PL KaitiM GB / UKai, Arphic Public License.
- **HSK 3.0 vocabulary**: complete-hsk-vocabulary © Yanis Zafirópulos, MIT.
"""


def fetch(name: str) -> Path:
    url, sha = SOURCES[name]
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / Path(url).name
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha:
        return dest
    print(f"  fetch {name} …", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    got = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if got != sha:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"sha256 mismatch for {name}: {got}")
    tmp.replace(dest)
    return dest


_CEDICT = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")


def _norm_py(py: str) -> str:
    """CEDICT pinyin ("Zhang3", "u:", "lu:4") → lowercase numbered ("zhang3", "lv4")."""
    return py.strip().lower().replace("u:", "v")


def choose_reading(candidates: list[str], primary: str, freq: dict[str, int]) -> str:
    """Pick the reading to display among those listed for one pronunciation.

    - the character's common (phiên âm) reading wins when it's a candidate;
    - a lone candidate that is near-absent from Vietnamese text (≤10 hits)
      yields to a common reading ≥10x more frequent (暗 àn: "yểm" vs "ám");
    - otherwise keep dictionary order. Raw frequency alone was tried and
      rejected: native words collide (的 "đích" lost to "để", 么 "ma" to "yêu").
    """
    if not candidates:
        return primary
    if primary in candidates:
        return primary
    if (len(candidates) == 1 and primary and freq.get(candidates[0], 0) <= 10
            and freq.get(primary, 0) >= 10 * max(1, freq.get(candidates[0], 0))):
        return primary
    return candidates[0]


def build() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "zh.sqlite"
    tmp = out.with_suffix(".sqlite.part")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
        CREATE TABLE words (simp TEXT, trad TEXT, pinyin TEXT, vi TEXT);
        CREATE TABLE hv (char TEXT, pinyin TEXT, readings TEXT, PRIMARY KEY (char, pinyin));
        CREATE TABLE hvchar (char TEXT PRIMARY KEY, primary_reading TEXT, all_readings TEXT);
        CREATE TABLE hv_best (char TEXT, pinyin TEXT, reading TEXT, PRIMARY KEY (char, pinyin));
        CREATE TABLE chars (char TEXT PRIMARY KEY, radical TEXT, decomposition TEXT,
                            etym_type TEXT, etym_hint TEXT);
        CREATE TABLE hsk (word TEXT PRIMARY KEY, level INTEGER);
    """)

    # CVDICT → words
    n = 0
    for line in fetch("cvdict").read_text(encoding="utf-8").splitlines():
        m = _CEDICT.match(line)
        if not m or line.startswith("#"):
            continue
        trad, simp, py, defs = m.groups()
        db.execute("INSERT INTO words VALUES (?,?,?,?)", (simp, trad, py, defs))
        n += 1
    print(f"  words: {n}")

    # zhongwen reading column → hv (single characters only, keyed by both forms)
    trad_of: dict[str, str] = {}
    n = 0
    for line in fetch("zhongwen").read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        m = _CEDICT.match(parts[0]) if parts else None
        if not m or len(parts) < 2 or not parts[1].strip():
            continue
        trad, simp, py, _ = m.groups()
        if len(trad) != 1 or len(simp) != 1 or " " in py:
            continue
        readings = parts[1].strip()
        trad_of.setdefault(simp, trad)
        for ch in {trad, simp}:
            db.execute("INSERT OR IGNORE INTO hv VALUES (?,?,?)", (ch, _norm_py(py), readings))
            n += 1
    print(f"  hv (char, pinyin) readings: {n}")

    # phiên âm (primary) + Thiều Chửu (all readings) → hvchar
    primary: dict[str, str] = {}
    for line in fetch("phienam").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            ch, r = line.split("=", 1)
            if len(ch) == 1 and r.strip():
                primary[ch] = r.strip()
    allr: dict[str, str] = {}
    for line in fetch("thieuchuu").read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^(.)=([^\[\\]+)", line)
        if m:
            allr[m.group(1)] = m.group(2).strip().rstrip(",")
    # Simplified forms inherit their traditional character's readings.
    for simp, trad in trad_of.items():
        if simp != trad:
            primary.setdefault(simp, primary.get(trad, ""))
            allr.setdefault(simp, allr.get(trad, ""))
    for ch in set(primary) | set(allr):
        p, a = primary.get(ch, ""), allr.get(ch, "")
        if p or a:
            db.execute("INSERT INTO hvchar VALUES (?,?,?)", (ch, p or a.split(",")[0].strip(), a))
    print(f"  hvchar: {len(set(primary) | set(allr))}")

    # hv_best: one display reading per (char, pinyin). Corpus counts come from
    # the Vietnamese glosses just loaded — Hán-Việt syllables are dense there.
    freq: dict[str, int] = {}
    for (vi,) in db.execute("SELECT vi FROM words"):
        for w in re.findall(r"[^\W\d_]+", vi.lower()):
            freq[w] = freq.get(w, 0) + 1
    rows = db.execute("SELECT char, pinyin, readings FROM hv").fetchall()
    for ch, py, readings in rows:
        best = HV_OVERRIDES.get((ch, py)) or choose_reading(
            [r.strip() for r in readings.split(",") if r.strip()],
            primary.get(ch, ""), freq)
        db.execute("INSERT OR REPLACE INTO hv_best VALUES (?,?,?)", (ch, py, best))
    for (ch, py), r in HV_OVERRIDES.items():   # overrides for pinyin the source lacks
        db.execute("INSERT OR REPLACE INTO hv_best VALUES (?,?,?)", (ch, py, r))
    print(f"  hv_best: {len(rows)} (+{len(HV_OVERRIDES)} curated)")

    # Make Me a Hanzi dictionary → chars
    n = 0
    for line in fetch("mmah_dict").read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        et = d.get("etymology") or {}
        hint = et.get("hint") or ""
        if et.get("type") == "pictophonetic":
            hint = f"thanh phù {et.get('phonetic', '')} · nghĩa phù {et.get('semantic', '')}" + (
                f" — {hint}" if hint else "")
        db.execute("INSERT OR IGNORE INTO chars VALUES (?,?,?,?,?)",
                   (d["character"], d.get("radical", ""), d.get("decomposition", ""),
                    et.get("type", ""), hint))
        n += 1
    print(f"  chars: {n}")

    # HSK 3.0 → hsk (lowest new-syllabus level "nX"; 7 = band 7-9)
    n = 0
    for item in json.loads(fetch("hsk").read_text(encoding="utf-8")):
        levels = [int(x[1:]) for x in item.get("l", []) if x.startswith("n") and x[1:].isdigit()]
        if levels:
            db.execute("INSERT OR REPLACE INTO hsk VALUES (?,?)", (item["s"], min(levels)))
            n += 1
    print(f"  hsk: {n}")

    db.executescript("""
        CREATE INDEX words_simp ON words(simp);
        CREATE INDEX words_trad ON words(trad);
    """)
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(out)
    (OUT_DIR / "NOTICE.md").write_text(NOTICE, encoding="utf-8")
    print(f"Done: {out} ({out.stat().st_size // 1024} KB)")
    return out


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
