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


_DIM_OVERLAY = QColor(0, 0, 0, 90)        # full-monitor dim under the boxes
_BLOCK_BG = QColor(0, 0, 0, 235)          # per-block opaque background
_BLOCK_FG = QColor(245, 245, 250, 255)    # translated text color
_BLOCK_PAD_X = 6
_BLOCK_PAD_Y = 3
_MIN_FONT_PT = 8
_MAX_FONT_PT = 24


class InlineOverlay(QWidget):
    """Full-screen translucent overlay that paints Vietnamese translations on
    top of the original OCR'd text blocks (Google-Lens style).

    Lifecycle:
      1. Caller computes per-block translations + their bbox in screen-local
         coordinates (i.e. relative to the monitor's top-left).
      2. `show_for_monitor(monitor_rect, blocks)` positions the overlay over
         that monitor and triggers a repaint.
      3. Any mouse press or Esc dismisses the overlay and emits `closed`.

    The overlay is intentionally "modal-ish": it accepts mouse events so the
    user can dismiss it with a single click anywhere. We don't pass clicks
    through to the underlying app — UX trade-off the user picked.
    """

    closed = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        # Translucent so the per-block boxes blend into whatever's beneath.
        # paintEvent draws everything manually (QSS background-color is unreliable
        # on top-level translucent widgets — same gotcha as FloatingPopup).
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._blocks: list[tuple[QRect, str]] = []

    def show_for_monitor(
        self,
        monitor_rect: QRect,
        blocks: list[tuple[QRect, str]],
    ) -> None:
        """Show the overlay covering `monitor_rect` (logical screen coords).

        `blocks` carries `(bbox, translated_text)` pairs. Each `bbox` is in
        coordinates relative to the monitor's top-left — caller has already
        adjusted for monitor origin so paintEvent can draw directly without
        more math.
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

        # 1. Faint dim of the whole monitor so original text reads as "muted".
        painter.fillRect(self.rect(), _DIM_OVERLAY)

        # 2. Opaque block at each bbox with the translated text inside.
        painter.setPen(_BLOCK_FG)
        for bbox, text in self._blocks:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_BLOCK_BG)
            painter.drawRoundedRect(bbox, 4, 4)

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
        # Any click anywhere dismisses the overlay — single-action close.
        self.close_overlay()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
            return
        super().keyPressEvent(event)


def _fit_font(text: str, rect: QRect) -> QFont:
    """Pick the largest point size in [_MIN_FONT_PT, _MAX_FONT_PT] that fits
    `text` (word-wrapped) inside `rect`.

    Translated text typically expands ~30-50% vs the original (especially CJK→Vi),
    so the block bbox from OCR is usually too small for the same font size. Auto-
    fitting prevents clipping at the cost of a few QFontMetrics measurements per
    block (cheap — overlay is short-lived).
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
    # Floor: even at _MIN_FONT_PT the text doesn't fit — let Qt clip it,
    # better than rendering nothing.
    font = QFont()
    font.setPointSize(_MIN_FONT_PT)
    font.setBold(True)
    return font
