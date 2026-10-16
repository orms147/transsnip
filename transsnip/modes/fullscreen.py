"""Full-screen translate helpers — the pure (Qt-free) half of the Alt+F flow.

Flow: hotkey → capture active monitor → OCR (multi-block) → batch all block
texts into one prompt with numeric prefixes [1], [2], ... → submit to the text
translator → parse output back per index → render InlineOverlay with one
opaque box per OCR bbox.

The text path is used even when the active provider supports vision: vision
providers return a single blob with no bbox info, so the overlay boxes
couldn't be positioned. Forcing text mode keeps the bbox→overlay coordinate
chain intact for every provider.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from transsnip.ocr.base import OCRBlock

_BATCH_MARKER = re.compile(r"\[(\d+)\]\s*", re.MULTILINE)


def build_numbered_batch(blocks: Sequence[OCRBlock]) -> str:
    """One `[N] text` line per block — a single API call for the whole screen."""
    return "\n".join(f"[{i + 1}] {b.text}" for i, b in enumerate(blocks))


def parse_numbered_batch(output: str, n: int) -> list[str]:
    """Split a `[1] ... [2] ... [3] ...` batch translation back into n strings.

    We feed the translator a single prompt with each OCR block prefixed by a
    `[N]` marker so we can keep N→1 (one API call, single context window) and
    still map results back to their bbox. The translator MOSTLY preserves the
    markers, but real providers misbehave in predictable ways:

    - Google Free occasionally re-wraps `[N]` as `( N )` or `「N」` — we won't
      match these and the affected block gets dropped from the overlay.
    - Some LLMs add commentary before the first marker (e.g. "Sure, here are
      the translations:") — anything before `[1]` is ignored.
    - Numbering can come back out of order; we map by the integer, not order.

    Output: list of length `n` where index `i` holds the translation of input
    block `i` (or empty string if the translator skipped that index).
    """
    matches = list(_BATCH_MARKER.finditer(output))
    result = [""] * n
    for i, m in enumerate(matches):
        idx = int(m.group(1)) - 1
        if not (0 <= idx < n):
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        result[idx] = output[start:end].strip()
    return result


def overlay_boxes(
    blocks: Sequence[OCRBlock], translations: Sequence[str], dpr: float
) -> list[tuple[tuple[int, int, int, int], str]]:
    """Pair each block's bbox with its translation, in LOGICAL monitor coords.

    OCR bboxes are in CAPTURED-image pixels (physical, already de-scaled for
    any OCR preprocessing). The overlay's geometry IS the monitor rect, so
    dividing by the device-pixel ratio gives overlay-local logical coords.
    Blocks whose translation came back empty are dropped.
    """
    boxes: list[tuple[tuple[int, int, int, int], str]] = []
    for block, text in zip(blocks, translations, strict=True):
        text = text.strip()
        if not text:
            continue
        x, y, w, h = block.bbox
        boxes.append(((int(x / dpr), int(y / dpr), int(w / dpr), int(h / dpr)), text))
    return boxes
