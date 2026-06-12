"""SubtitleBar — a floating translated-subtitle strip for video subtitle mode.

Positioned just BELOW the user's chosen subtitle region by default (never on
top of it: the loop re-captures that region every frame, so an overlay covering
it would feed its own translated pixels back into the OCR — the self-capture
trap from the popup-overlay postmortem, mentor doc 90).

The bar is:
- centered text (easier to read),
- draggable (user can park it anywhere — once moved, it stays put and only
  resizes to fit new text),
- adjustable background opacity (Settings → Display) so the video stays visible.

It never steals focus (WA_ShowWithoutActivating) so it doesn't interrupt
playback; stopping is via the controller (toggle Alt+V).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QWidget

_FG = QColor(245, 246, 248, 255)
_STATUS_FG = QColor(129, 140, 248, 255)  # cobalt accent
_PAD_X = 16
_PAD_Y = 11
_RADIUS = 10
_GAP = 8           # px between the source region and the bar
_MIN_W = 280
_FONT_PT = 15
_STATUS_PT = 10


class SubtitleBar(QWidget):
    """Always-on-top, draggable strip showing the live translated subtitle."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._region = QRect()
        self._text = ""
        self._status = "Đang nghe phụ đề…"   # shown until the first translation lands
        self._bg_alpha = 235                  # 0-255; set via set_bg_opacity()
        self._font_pt = _FONT_PT              # set via set_font_pt()
        self._user_moved = False              # once dragged, stop auto-anchoring
        self._drag_offset: QPoint | None = None

    # ── Public API ───────────────────────────────────────────────────────────

    def start_for_region(self, region: QRect) -> None:
        """Anchor the bar below `region` (logical coords) and show the waiting state."""
        self._region = region
        self._text = ""
        self._status = "Đang nghe phụ đề…"
        self._user_moved = False
        self._relayout()
        self.show()
        self.raise_()

    def set_bg_opacity(self, opacity: float) -> None:
        """Background opacity, 0.0 (transparent) .. 1.0 (solid)."""
        self._bg_alpha = max(0, min(255, int(opacity * 255)))
        self.update()

    def set_font_pt(self, pt: int) -> None:
        """Subtitle text size in points (Settings → Display)."""
        self._font_pt = max(8, min(48, int(pt)))
        self._relayout()
        self.update()

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def set_text(self, text: str) -> None:
        """Show a freshly translated line (clears the status indicator)."""
        self._text = text.strip()
        self._status = ""
        self._relayout()
        self.update()

    def stop(self) -> None:
        self.hide()
        self._text = ""

    # ── Drag-to-move ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self._user_moved = True
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _relayout(self) -> None:
        """Size to the text. Anchor below the region unless the user moved it."""
        region = self._region
        width = max(region.width(), _MIN_W)
        inner_w = width - 2 * _PAD_X

        body = self._text or self._status
        metrics = QFontMetrics(self._font())
        bound = metrics.boundingRect(
            QRect(0, 0, inner_w, 10_000),
            int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter),
            body or " ",
        )
        height = bound.height() + 2 * _PAD_Y

        if self._user_moved:
            # Keep where the user parked it; only resize (anchor top-left).
            self.resize(width, height)
            return

        x = region.x()
        y = region.y() + region.height() + _GAP
        # If the bar would fall off the bottom of the screen, flip it above.
        screen = QGuiApplication.screenAt(region.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.geometry()
            if y + height > geo.bottom():
                y = region.y() - _GAP - height
            x = max(geo.left(), min(x, geo.right() - width))
        self.setGeometry(x, y, width, height)

    def _font(self) -> QFont:
        f = QFont()
        f.setPointSize(self._font_pt)
        f.setWeight(QFont.Weight.Medium)
        return f

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 13, 16, self._bg_alpha))
        painter.drawRoundedRect(self.rect(), _RADIUS, _RADIUS)

        inner = self.rect().adjusted(_PAD_X, _PAD_Y, -_PAD_X, -_PAD_Y)
        if self._text:
            painter.setFont(self._font())
            painter.setPen(_FG)
            painter.drawText(
                inner,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                    | Qt.TextFlag.TextWordWrap),
                self._text,
            )
        else:
            f = QFont()
            f.setPointSize(_STATUS_PT)
            painter.setFont(f)
            painter.setPen(_STATUS_FG)
            painter.drawText(
                inner,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                self._status or "…",
            )
