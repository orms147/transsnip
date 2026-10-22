"""Segment Chinese text into words and annotate each with pinyin + tones.

jieba segments ("实习不久" → 实习 / 不久) and pypinyin reads each WORD, not
each character, so polyphones resolve from context (董事长 zhǎng, 银行 háng,
长城 cháng) and 一/不 tone sandhi applies (一定 yí dìng). Both are MIT,
fully offline; jieba's dictionary takes ~0.6 s to load, hence the lazy init.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_init_lock = threading.Lock()
_ready = False


def is_han(ch: str) -> bool:
    return bool(_HAN_RE.fullmatch(ch))


@dataclass(frozen=True)
class Syllable:
    char: str
    pinyin: str          # with tone mark, e.g. "zhǎng"; "" for non-Han chars
    tone: int            # 1-4, 5 = neutral, 0 = not a Han character
    numbered: str = ""   # "zhang3" — dictionary key form (CEDICT style, ü → v)


@dataclass(frozen=True)
class Token:
    text: str
    syllables: tuple[Syllable, ...] = field(default=())

    @property
    def is_word(self) -> bool:
        """Contains Chinese characters (clickable / looked up)."""
        return any(s.tone for s in self.syllables)

    @property
    def pinyin(self) -> str:
        return " ".join(s.pinyin for s in self.syllables if s.pinyin)


def _ensure_ready() -> None:
    global _ready
    if _ready:
        return
    with _init_lock:
        if _ready:
            return
        import jieba
        jieba.setLogLevel(logging.WARNING)
        jieba.initialize()   # loads the ~5 MB dictionary once
        _ready = True


def warm_up() -> None:
    """Load jieba's dictionary now (call off the GUI thread)."""
    _ensure_ready()


def _syllables(word: str) -> tuple[Syllable, ...]:
    from pypinyin import Style, pinyin

    marks = pinyin(word, style=Style.TONE, errors=lambda s: [[c] for c in s],
                   neutral_tone_with_five=False)
    nums = pinyin(word, style=Style.TONE3, errors=lambda s: [[c] for c in s],
                  neutral_tone_with_five=True)
    out: list[Syllable] = []
    chars = list(word)
    # pypinyin returns one item per Han char and passes other runs through;
    # walk chars and consume readings only for Han characters.
    readings = [(m[0], n[0]) for m, n in zip(marks, nums, strict=True)]
    ri = 0
    for ch in chars:
        if is_han(ch) and ri < len(readings):
            mark, num = readings[ri]
            ri += 1
            tone = int(num[-1]) if num and num[-1].isdigit() else 5
            numbered = num if num and num[-1].isdigit() else f"{num}5"
            out.append(Syllable(ch, mark, tone, numbered.replace("ü", "v")))
        else:
            if ri < len(readings) and readings[ri][0] == ch:
                ri += 1
            out.append(Syllable(ch, "", 0))
    return tuple(out)


def tokenize(text: str) -> list[Token]:
    """Words with per-character pinyin. Non-Chinese runs come back as tokens
    with tone-0 syllables so the caller can render the line verbatim."""
    _ensure_ready()
    import jieba

    return [Token(w, _syllables(w)) for w in jieba.lcut(text) if w]


# Pleco-style tone colours (1 red, 2 green/orange, 3 blue, 4 purple, neutral grey)
# tuned to stay readable on both the dark and light popup themes.
TONE_COLORS: dict[int, str] = {
    1: "#e5484d",   # flat
    2: "#30a46c",   # rising
    3: "#3e8ef7",   # dipping
    4: "#a855f7",   # falling
    5: "#8b8d98",   # neutral
}


_SENTENCE_END = re.compile(r"[。！？!?；;\n]")


def sentence_at(text: str, start: int, end: int) -> str:
    """The sentence of `text` that contains text[start:end] (its punctuation
    included). A word card needs the word's own sentence, not a whole
    paragraph snipped from an article."""
    left = max((m.end() for m in _SENTENCE_END.finditer(text, 0, start)), default=0)
    m = _SENTENCE_END.search(text, end)
    right = m.end() if m else len(text)
    return text[left:right].strip()
