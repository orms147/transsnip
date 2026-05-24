from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from PIL import Image


class OCRError(Exception):
    """Raised when no OCR engine can produce a result."""


# Sentence-terminating punctuation, both fullwidth (CJK) and ASCII. When an OCR
# line ends with one of these, Stage 2 treats the next line as a new paragraph
# even if the vertical gap is small — typical of Discord/Slack/IM messages where
# each sentence ends with 。 (or .) and sits on its own visual line. Without this
# check, all sentences inside a single chat block merge into one wall of text.
_SENTENCE_TERMINATORS: tuple[str, ...] = (
    "。", "．", "！", "？",  # fullwidth CJK
    ".", "!", "?",            # ASCII
)


def _is_cjk(ch: str) -> bool:
    """True for Han/Hiragana/Katakana/Hangul/CJK-punct/fullwidth code points.

    Used by the per-line joiner: two adjacent CJK code points should not get
    a space between them (Japanese/Chinese have no word separators), while
    a Latin↔CJK boundary still needs one for readability.
    """
    if not ch:
        return False
    code = ord(ch)
    return (
        0x3000 <= code <= 0x303F     # CJK symbols & punctuation
        or 0x3040 <= code <= 0x309F  # Hiragana
        or 0x30A0 <= code <= 0x30FF  # Katakana
        or 0x4E00 <= code <= 0x9FFF  # CJK unified ideographs
        or 0xFF00 <= code <= 0xFFEF  # Halfwidth / fullwidth forms
        or 0xAC00 <= code <= 0xD7AF  # Hangul syllables
    )


def _join_blocks_smart(texts: list[str]) -> str:
    """Concatenate block texts, omitting the separator between CJK↔CJK pairs.

    Windows OCR (and most engines) emit one block per character for CJK
    scripts. Joining everything with " " yields "受 講 の み" — every
    character becomes its own "word", which destroys translation quality
    downstream. This joiner detects the script of the boundary characters
    and inserts a space only where one belongs.
    """
    parts: list[str] = []
    for i, cur in enumerate(texts):
        if not cur:
            continue
        if not parts:
            parts.append(cur)
            continue
        prev = parts[-1]
        if prev and _is_cjk(prev[-1]) and _is_cjk(cur[0]):
            parts.append(cur)
        else:
            parts.append(" ")
            parts.append(cur)
    return "".join(parts)


@dataclass(frozen=True)
class OCRBlock:
    """A recognized chunk of text with its bounding rectangle (image pixels)."""

    text: str
    bbox: tuple[int, int, int, int]  # x, y, w, h relative to the input image
    confidence: float | None = None


@dataclass(frozen=True)
class OCRResult:
    engine: str
    blocks: list[OCRBlock] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Reassemble blocks into reading-order text.

        Two stages:

        1. **Group blocks into horizontal lines** by y-coordinate proximity. Within
           a line, sort left-to-right and join with single spaces. This fixes the
           "one-word-per-line" bug where OCR engines emit word-level blocks.

        2. **Merge consecutive lines into paragraphs** when the vertical gap is
           small (< 80% of average line height). This handles the case where a
           single sentence wraps across multiple visual lines (e.g. YouTube card
           titles) — without this, translation providers see two disconnected
           fragments and lose context. Large gaps still produce a real paragraph
           break (`\\n`) so genuinely separate text blocks stay separate.
        """
        if not self.blocks:
            return ""

        sorted_blocks = sorted(self.blocks, key=lambda b: (b.bbox[1], b.bbox[0]))

        # Stage 1 — group into lines.
        lines: list[list[OCRBlock]] = []
        for block in sorted_blocks:
            _x, y_top, _w, height = block.bbox
            y_center = y_top + height / 2
            tolerance = max(height * 0.6, 6)

            attached = False
            for line in lines:
                line_top = min(b.bbox[1] for b in line)
                line_bot = max(b.bbox[1] + b.bbox[3] for b in line)
                line_center = (line_top + line_bot) / 2
                if abs(y_center - line_center) <= tolerance:
                    line.append(block)
                    attached = True
                    break
            if not attached:
                lines.append([block])

        # Materialize per-line metadata: (y_top, y_bot, avg_height, text).
        per_line: list[tuple[int, int, float, str]] = []
        for line in lines:
            line.sort(key=lambda b: b.bbox[0])
            y_top = min(b.bbox[1] for b in line)
            y_bot = max(b.bbox[1] + b.bbox[3] for b in line)
            avg_h = sum(b.bbox[3] for b in line) / len(line)
            text = _join_blocks_smart([b.text for b in line]).strip()
            if text:
                per_line.append((y_top, y_bot, avg_h, text))

        if not per_line:
            return ""

        per_line.sort(key=lambda t: t[0])

        # Stage 2 — merge wrapped lines into paragraphs.
        #
        # The visual-gap rule alone (`gap < avg_h * 0.8`) over-merges: Discord
        # chat lines that each end with `。` sit at ~0.4-0.5 avg_h apart, so
        # every sentence in a message would collapse into one paragraph. Layer
        # a sentence-terminator check on top: if the previous line clearly
        # ended a sentence, the next line starts a new paragraph regardless
        # of how close it sits visually. Lines that don't end with a
        # terminator are still merged (this handles a long single sentence
        # that wraps across visual lines — we don't want a phantom `\n` in
        # the middle of it before sending to the translator).
        paragraphs: list[str] = [per_line[0][3]]
        for i in range(1, len(per_line)):
            _, prev_bot, prev_h, _ = per_line[i - 1]
            cur_top, _, cur_h, cur_text = per_line[i]
            gap = cur_top - prev_bot
            avg_h = (prev_h + cur_h) / 2
            prev_ends_sentence = paragraphs[-1].rstrip().endswith(_SENTENCE_TERMINATORS)
            if gap < avg_h * 0.8 and not prev_ends_sentence:
                # Reuse the smart joiner so CJK lines merge without a phantom
                # space appearing mid-sentence at the wrap point.
                paragraphs[-1] = _join_blocks_smart([paragraphs[-1], cur_text])
            else:
                paragraphs.append(cur_text)

        return "\n".join(paragraphs)


class OCREngine(ABC):
    """Common interface for every OCR backend.

    Implementations must be thread-safe for `recognize()` — they are invoked from
    a worker thread (see `transsnip/ocr/worker.py`).
    """

    name: str = "unknown"

    @abstractmethod
    def recognize(self, image: Image.Image, lang: str | None = None) -> OCRResult:
        """Return text blocks recognized in `image`.

        Raises `OCRError` if the engine fails. An empty result list is NOT an error
        — it means the engine ran successfully but found nothing.
        """

    @abstractmethod
    def supported_languages(self) -> set[str]:
        """BCP-47 language tags this engine can recognize on the current host."""

    def is_available(self) -> bool:
        """Whether the engine can run right now (DLLs present, models loaded, ...)."""
        return True
