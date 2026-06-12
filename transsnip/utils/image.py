"""Cheap frame-diff + fuzzy text helpers for the video subtitle loop.

The subtitle loop captures the same small region ~4×/second. Re-running OCR +
translation on every frame would hammer the CPU and the translation API even
when nothing changed (a paused video, a held subtitle line). These two helpers
are the gates that keep the loop cheap:

- `frame_difference()` — "did the pixels change at all?" Skips OCR on identical
  frames. A downscaled grayscale mean-abs-diff, NOT full SSIM: SSIM needs
  scikit-image (heavy) and we only need a coarse "changed / not changed" signal.
- `text_similarity()` — "is this the same line we already translated?" Skips the
  translation call when OCR returns a near-identical string (anti-aliasing makes
  the same subtitle OCR to slightly different text frame-to-frame).
"""
from __future__ import annotations

from difflib import SequenceMatcher

import numpy as np
from PIL import Image

# Both frames are downscaled to this square before comparing. Small enough that
# the diff costs microseconds; large enough to notice a subtitle line changing.
_DIFF_SIZE = 48


def frame_difference(a: Image.Image, b: Image.Image) -> float:
    """Return a 0.0–1.0 difference score between two frames (0 = identical).

    Both images are converted to grayscale and squashed to `_DIFF_SIZE`², so
    the score is resolution-independent and robust to a 1-px capture jitter.
    Caller compares against a threshold (e.g. skip OCR if score < 0.02).
    """
    ga = np.asarray(a.convert("L").resize((_DIFF_SIZE, _DIFF_SIZE)), dtype=np.float32)
    gb = np.asarray(b.convert("L").resize((_DIFF_SIZE, _DIFF_SIZE)), dtype=np.float32)
    return float(np.abs(ga - gb).mean() / 255.0)


def text_similarity(a: str, b: str) -> float:
    """Return a 0.0–1.0 similarity ratio between two strings (1 = identical).

    Plain `difflib` ratio — good enough to catch "same subtitle, OCR jittered a
    couple characters". Caller treats e.g. ≥0.92 as "same line, don't re-translate".
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
