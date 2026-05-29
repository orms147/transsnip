"""InlineOverlay — fullscreen translate (Google-Lens style).

Reverted to the original simple opaque-box layout: full-screen dim,
one rounded opaque rectangle per OCR block with the Vietnamese translation
inside (white text, auto-fitted), click/Esc to dismiss. No toolbar, no
accent border, no numbered badges — the user found the Cobalt redesign
too busy for this view and asked to keep the original UI for fullscreen
mode.

The contract from `AppController` is unchanged: call
`show_for_monitor(monitor_rect, blocks)` with blocks already converted to
overlay-local logical coords. Extra keyword args (src_lang, tgt_lang,
provider) are accepted-and-ignored so existing callers don't need to
change shape.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

# Visual constants (kept inline — the overlay is the only consumer).
_DIM_ALPHA = 90              # full-screen dim under the boxes
_BLOCK_BG = QColor(0, 0, 0, 235)
_BLOCK_FG = QColor(245, 245, 250, 255)
_BLOCK_PAD_X = 6
_BLOCK_PAD_Y = 3
_BLOCK_RADIUS = 4
_MIN_FONT_PT = 8
_MAX_FONT_PT = 24


class InlineOverlay(QWidget):
    """Full-screen translucent overlay painting opaque boxes over OCR blocks.

    Lifecycle:
      1. Caller computes per-block translations + each block's bbox in
         monitor-local logical coordinates.
      2. `show_for_monitor(monitor_rect, blocks)` resizes the overlay to
         cover the monitor and repaints.
      3. Any mouse press or Esc dismisses the overlay and emits `closed`.
    """

    closed = Signal()
    # Kept for compatibility with AppController wiring. The simplified UI
    # has no Refresh button, so this signal will never fire — but the
    # connection in AppController is harmless.
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._blocks: list[tuple[QRect, str]] = []

    # ── Public API ─────────────────────────────────────────────────────────

    def show_for_monitor(
        self,
        monitor_rect: QRect,
        blocks: list[tuple[QRect, str]],
        **_unused,
    ) -> None:
        """Show the overlay covering `monitor_rect` (logical screen coords).

        `blocks` carries `(bbox, translated_text)` pairs in monitor-local
        coordinates. Extra keyword args (src_lang / tgt_lang / provider)
        are silently accepted for forward-compat with the toolbar-era
        signature but ignored by this simpler renderer.
        """
        self._blocks = blocks
        log.debug(
            "InlineOverlay.show_for_monitor: monitor=%s blocks=%d",
            monitor_rect, len(blocks),
        )
        self.setGeometry(monitor_rect)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def close_overlay(self) -> None:
        self.hide()
        self._blocks = []
        self.closed.emit()

    # ── Paint ──────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 1. Faint global dim so the boxes pop without hiding context entirely.
        painter.fillRect(self.rect(), QColor(0, 0, 0, _DIM_ALPHA))

        # 2. Opaque rounded box at each bbox with the translated text.
        painter.setPen(_BLOCK_FG)
        for bbox, text in self._blocks:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_BLOCK_BG)
            painter.drawRoundedRect(bbox, _BLOCK_RADIUS, _BLOCK_RADIUS)

            inner = bbox.adjusted(_BLOCK_PAD_X, _BLOCK_PAD_Y, -_BLOCK_PAD_X, -_BLOCK_PAD_Y)
            if inner.width() <= 0 or inner.height() <= 0:
                continue

            font = _fit_font(text, inner)
            painter.setFont(font)
            painter.setPen(_BLOCK_FG)
            painter.drawText(
                inner,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap,
                text,
            )

    # ── Dismiss handlers ───────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Single-click anywhere closes — keeps the model identical to the
        # original implementation.
        self.close_overlay()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
            return
        super().keyPressEvent(event)


def _fit_font(text: str, rect: QRect) -> QFont:
    """Pick the largest point size in [_MIN_FONT_PT, _MAX_FONT_PT] that
    word-wraps `text` inside `rect`.

    Translated text typically expands ~30-50% vs the original (especially
    CJK→Vi), so the block's OCR bbox is usually too small for the source's
    font size. Auto-fitting prevents clipping at the cost of a few
    QFontMetrics measurements per block (cheap — overlay is short-lived).
    """
    for pt in range(_MAX_FONT_PT, _MIN_FONT_PT - 1, -1):
        font = QFont()
        font.setPointSize(pt)
        font.setBold(True)
        metrics = QFontMetrics(font)
        bound = metrics.boundingRect(
            rect,
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        if bound.width() <= rect.width() and bound.height() <= rect.height():
            return font
    font = QFont()
    font.setPointSize(_MIN_FONT_PT)
    font.setBold(True)
    return font
