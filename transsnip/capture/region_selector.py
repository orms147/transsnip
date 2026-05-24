from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

_TINT_ALPHA = 110
_BORDER_COLOR = QColor(255, 200, 0)
_BORDER_WIDTH = 2
_MIN_SELECTION = 5  # pixels — drag smaller than this counts as a click → cancel


class RegionSelector(QWidget):
    """Full-screen translucent overlay for snipping-tool style rectangle selection.

    Emits `selected(QRect)` (screen / global coordinates) when the user finishes a drag,
    or `cancelled()` on Esc / right-click / sub-minimum drag.
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
        self._origin: QPoint | None = None
        self._end: QPoint | None = None

    def start(self) -> None:
        """Show the overlay covering the primary screen.

        Multi-monitor coverage will be added in a later milestone (see plan, Phase 3).
        """
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
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _current_rect(self) -> QRect | None:
        if self._origin is None or self._end is None:
            return None
        return QRect(self._origin, self._end).normalized()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002
        painter = QPainter(self)
        try:
            tint = QColor(0, 0, 0, _TINT_ALPHA)
            full = self.rect()
            sel = self._current_rect()
            if sel is None:
                painter.fillRect(full, tint)
                return
            # Paint tint on the 4 strips outside the selection so the selection
            # itself is a "hole" — user sees source content clearly.
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
            pen = QPen(_BORDER_COLOR, _BORDER_WIDTH)
            painter.setPen(pen)
            painter.drawRect(sel)
        finally:
            painter.end()

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
        if self._origin is None:
            return
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
        # Translate local widget coordinates to global screen coordinates so the
        # capture layer can hand the rect straight to mss without further offset math.
        global_top_left = self.mapToGlobal(local.topLeft())
        global_rect = QRect(global_top_left, local.size())
        self._finish(cancelled=False, result=global_rect)

    def _finish(self, *, cancelled: bool, result: QRect | None = None) -> None:
        self.hide()
        self._origin = None
        self._end = None
        if cancelled or result is None:
            log.info("Region selection cancelled")
            self.cancelled.emit()
        else:
            log.info("Region selected: %s", result)
            self.selected.emit(result)
