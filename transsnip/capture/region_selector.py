"""RegionSelector — Cobalt redesign.

Snipping-tool style overlay with the design's polish:
- 4 corner brackets (instead of full rect border) — less busy
- Crosshair guides from the active cursor position
- Size readout `480 × 78 · 1.5×` follows the bottom-right of the selection
- Top-center hint "Kéo để chọn vùng cần dịch · Esc huỷ · Enter xác nhận"

Emits the same `selected(QRect)` / `cancelled()` signals as before so
`AppController` doesn't need to change. Coordinates are global Qt logical
pixels (via `mapToGlobal`) — DPI conversion lives in `capture/screen.py`.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from transsnip.ui.theme import get_theme

log = logging.getLogger(__name__)

_TINT_ALPHA = 110           # 4 outer strips outside the selection
_MIN_SELECTION = 5          # drag smaller than this counts as a cancel-click
_CORNER_LEN = 14            # length of each corner bracket arm (px)
_CORNER_WIDTH = 2
_GUIDE_DASH = (4, 4)
_GUIDE_WIDTH = 1
_READOUT_OFFSET = 10        # gap between selection corner and readout pill
_HINT_TOP_INSET = 24


class RegionSelector(QWidget):
    """Full-screen translucent overlay for snipping-tool style selection.

    UX flow (Cobalt design):
      1. `start()` shows the overlay over the primary screen with a top-center
         hint and crosshair guides following the cursor.
      2. While dragging, the selection becomes a "hole" in the dim tint with
         accent corner brackets + a size readout pill near the bottom-right
         corner of the selection.
      3. Release emits `selected(global_rect)`; Esc / right-click / sub-min
         drag emits `cancelled()`.
    """

    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setMouseTracking(True)  # crosshair guides need hover position
        self._origin: QPoint | None = None
        self._end: QPoint | None = None
        self._hover: QPoint | None = None
        self._dpr_label: str = ""

    def start(self) -> None:
        if self.isVisible():
            log.debug("Region selector already visible — ignoring re-trigger")
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            log.error("No primary screen available")
            self.cancelled.emit()
            return
        self._origin = None
        self._end = None
        self._hover = None
        self._dpr_label = f"{screen.devicePixelRatio():.1f}×"
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _current_rect(self) -> QRect | None:
        if self._origin is None or self._end is None:
            return None
        return QRect(self._origin, self._end).normalized()

    # ── Paint ──────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            tint = QColor(0, 0, 0, _TINT_ALPHA)
            full = self.rect()
            sel = self._current_rect()

            # Crosshair guides — only when hovering (before drag starts).
            if sel is None:
                painter.fillRect(full, tint)
                if self._hover is not None:
                    self._draw_guides(painter, self._hover, p)
                self._draw_hint(painter, p)
                return

            # 4 strips outside the selection — selection is a "hole".
            painter.fillRect(QRect(0, 0, full.width(), sel.top()), tint)
            painter.fillRect(
                QRect(0, sel.bottom() + 1, full.width(), full.height() - sel.bottom() - 1),
                tint,
            )
            painter.fillRect(QRect(0, sel.top(), sel.left(), sel.height()), tint)
            painter.fillRect(
                QRect(sel.right() + 1, sel.top(), full.width() - sel.right() - 1, sel.height()),
                tint,
            )

            # Crosshair guides from the active corner during drag.
            if self._end is not None:
                self._draw_guides(painter, self._end, p)

            # 4 corner brackets (accent) — replaces the old full-border rect.
            self._draw_corners(painter, sel, p)

            # Size readout pill near bottom-right corner of selection.
            self._draw_readout(painter, sel, p)
        finally:
            painter.end()

    def _draw_corners(self, painter: QPainter, sel: QRect, p) -> None:
        pen = QPen(QColor(p.accent), _CORNER_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        x1, y1, x2, y2 = sel.left(), sel.top(), sel.right(), sel.bottom()
        L = _CORNER_LEN
        # TL
        painter.drawLine(x1, y1, x1 + L, y1)
        painter.drawLine(x1, y1, x1, y1 + L)
        # TR
        painter.drawLine(x2 - L, y1, x2, y1)
        painter.drawLine(x2, y1, x2, y1 + L)
        # BL
        painter.drawLine(x1, y2 - L, x1, y2)
        painter.drawLine(x1, y2, x1 + L, y2)
        # BR
        painter.drawLine(x2 - L, y2, x2, y2)
        painter.drawLine(x2, y2 - L, x2, y2)

    def _draw_guides(self, painter: QPainter, point: QPoint, p) -> None:
        pen = QPen(QColor(p.accent), _GUIDE_WIDTH)
        pen.setDashPattern([float(_GUIDE_DASH[0]), float(_GUIDE_DASH[1])])
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        full = self.rect()
        painter.drawLine(0, point.y(), full.width(), point.y())
        painter.drawLine(point.x(), 0, point.x(), full.height())

    def _draw_readout(self, painter: QPainter, sel: QRect, p) -> None:
        text = f"{sel.width()} × {sel.height()}  ·  {self._dpr_label}"
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(text)
        text_h = metrics.height()
        pad_x = 10
        pad_y = 5
        pill_w = text_w + 2 * pad_x
        pill_h = text_h + 2 * pad_y

        # Position: bottom-right of the selection, with offset; flip to inside
        # the selection or above if it would land off-screen.
        full = self.rect()
        x = sel.right() + _READOUT_OFFSET
        y = sel.bottom() + _READOUT_OFFSET
        if x + pill_w > full.width():
            x = sel.right() - pill_w  # tuck inside
        if y + pill_h > full.height():
            y = sel.top() - pill_h - _READOUT_OFFSET

        pill = QRectF(x, y, pill_w, pill_h)
        painter.setBrush(QColor(p.bg_1))
        painter.setPen(QPen(QColor(p.border_2), 1))
        painter.drawRoundedRect(pill, p.r_pill, p.r_pill)

        painter.setPen(QColor(p.text_1))
        painter.setFont(font)
        painter.drawText(
            pill,
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    def _draw_hint(self, painter: QPainter, p) -> None:
        """Top-center hint shown only while the user is hovering pre-drag.

        Keeps the screen from feeling empty / unclear before the first click.
        """
        text_main = "Kéo để chọn vùng cần dịch"
        text_kbd = "Esc huỷ  ·  Enter xác nhận"
        font_main = QFont()
        font_main.setPointSize(11)
        font_main.setBold(True)
        font_kbd = QFont()
        font_kbd.setPointSize(10)
        m_main = QFontMetrics(font_main)
        m_kbd = QFontMetrics(font_kbd)
        text_w = max(m_main.horizontalAdvance(text_main), m_kbd.horizontalAdvance(text_kbd))
        pad_x, pad_y, spacing = 20, 10, 4
        pill_w = text_w + 2 * pad_x
        pill_h = m_main.height() + m_kbd.height() + 2 * pad_y + spacing
        full = self.rect()
        x = (full.width() - pill_w) // 2
        y = _HINT_TOP_INSET
        pill = QRectF(x, y, pill_w, pill_h)

        painter.setBrush(QColor(p.bg_1))
        painter.setPen(QPen(QColor(p.border_2), 1))
        painter.drawRoundedRect(pill, 8, 8)

        painter.setPen(QColor(p.text_1))
        painter.setFont(font_main)
        painter.drawText(
            QRectF(x, y + pad_y, pill_w, m_main.height()),
            Qt.AlignmentFlag.AlignCenter,
            text_main,
        )
        painter.setPen(QColor(p.text_3))
        painter.setFont(font_kbd)
        painter.drawText(
            QRectF(x, y + pad_y + m_main.height() + spacing, pill_w, m_kbd.height()),
            Qt.AlignmentFlag.AlignCenter,
            text_kbd,
        )

    # ── Input handlers ─────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._finish(cancelled=True)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._end = self._origin
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._finish(cancelled=True)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # Always track hover for crosshair guides; drag-end updates only when
        # the LMB has been pressed and origin is set.
        self._hover = event.position().toPoint()
        if self._origin is not None:
            self._end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._end = event.position().toPoint()
        local = self._current_rect()
        if local is None or local.width() < _MIN_SELECTION or local.height() < _MIN_SELECTION:
            self._finish(cancelled=True)
            return
        global_top_left = self.mapToGlobal(local.topLeft())
        global_rect = QRect(global_top_left, local.size())
        self._finish(cancelled=False, result=global_rect)

    def _finish(self, *, cancelled: bool, result: QRect | None = None) -> None:
        self.hide()
        self._origin = None
        self._end = None
        self._hover = None
        if cancelled or result is None:
            log.info("Region selection cancelled")
            self.cancelled.emit()
        else:
            log.info("Region selected: %s", result)
            self.selected.emit(result)
