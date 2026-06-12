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
_BLOCK_PAD_X = 8
_BLOCK_PAD_Y = 5
_BLOCK_RADIUS = 4
_MIN_FONT_PT = 11            # readable floor — below this we grow the box instead
_MAX_FONT_PT = 22
_MIN_BOX_W = 160             # don't let a box get narrower than this
_MAX_BOX_W_FRAC = 0.6        # cap box width at this fraction of the monitor width


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

        # 2. Opaque rounded box at each bbox with the translated text. The box
        #    GROWS to fit the translation (rather than shrinking the text to an
        #    unreadable size and clipping it inside the small source bbox).
        for bbox, text in self._blocks:
            box, font = _layout_block(text, bbox, self.width(), self.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_BLOCK_BG)
            painter.drawRoundedRect(box, _BLOCK_RADIUS, _BLOCK_RADIUS)

            inner = box.adjusted(_BLOCK_PAD_X, _BLOCK_PAD_Y, -_BLOCK_PAD_X, -_BLOCK_PAD_Y)
            if inner.width() <= 0 or inner.height() <= 0:
                continue
            painter.setFont(font)
            painter.setPen(_BLOCK_FG)
            painter.drawText(
                inner,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                    | Qt.TextFlag.TextWordWrap),
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


def _layout_block(text: str, bbox: QRect, ov_w: int, ov_h: int) -> tuple[QRect, QFont]:
    """Return (box, font) for one translated block — the box GROWS to fit text.

    Why grow instead of shrink-to-fit: a Vietnamese translation is often 30-50%
    longer than the CJK/EN source, so the source's small OCR bbox can't hold it
    even at a tiny font — the old shrink-then-clip approach left text cut off and
    unreadable. Instead we pick a readable font sized to the source line, then
    size the box to whatever the wrapped text needs (capped at 60% monitor width),
    and nudge it back on-screen if it would spill off the edge.
    """
    font = QFont()
    font.setBold(True)
    pt = max(_MIN_FONT_PT, min(_MAX_FONT_PT, round(bbox.height() * 0.5) or _MIN_FONT_PT))
    font.setPointSize(pt)
    metrics = QFontMetrics(font)

    max_w = int(min(ov_w * _MAX_BOX_W_FRAC, max(bbox.width(), _MIN_BOX_W)))
    inner_w = max(40, max_w - 2 * _BLOCK_PAD_X)
    bound = metrics.boundingRect(
        QRect(0, 0, inner_w, 100_000),
        int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft),
        text,
    )
    box_w = max(bbox.width(), min(max_w, bound.width() + 2 * _BLOCK_PAD_X))
    box_h = max(bbox.height(), bound.height() + 2 * _BLOCK_PAD_Y)

    x, y = bbox.x(), bbox.y()
    if x + box_w > ov_w:
        x = max(0, ov_w - box_w)
    if y + box_h > ov_h:
        y = max(0, ov_h - box_h)
    return QRect(x, y, box_w, box_h), font
