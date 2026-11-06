"""Edge-drag resize for the frameless popup (mixin)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QGuiApplication,
    QMouseEvent,
)

from transsnip.display.popup.constants import (
    _MIN_HEIGHT,
    _MIN_WIDTH,
    _RESIZE_MARGIN,
)


class _EdgeResizeMixin:
    """Drag-from-edge resizing. Host owns `_resize_*` / `_user_resized` state."""

    def _edges_at(self, pos: QPoint) -> int:
        m = _RESIZE_MARGIN
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        edges = 0
        if x <= m:
            edges |= 1
        elif x >= w - m:
            edges |= 2
        if y <= m:
            edges |= 4
        elif y >= h - m:
            edges |= 8
        return edges

    @staticmethod
    def _cursor_for_edges(edges: int) -> Qt.CursorShape:
        if edges in (1 | 4, 2 | 8):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (2 | 4, 1 | 8):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (1 | 2):
            return Qt.CursorShape.SizeHorCursor
        if edges & (4 | 8):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _begin_resize(self, edges: int, global_pt: QPoint) -> None:
        self._resize_edges = edges
        self._resize_start_geom = self.geometry()
        self._resize_start_global = global_pt

    def _update_resize(self, global_pt: QPoint) -> None:
        if not (self._resize_edges and self._resize_start_geom and self._resize_start_global):
            return
        delta = global_pt - self._resize_start_global
        g = QRect(self._resize_start_geom)
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) \
            or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None

        if self._resize_edges & 1:
            new_left = g.left() + delta.x()
            if g.right() - new_left + 1 < _MIN_WIDTH:
                new_left = g.right() - _MIN_WIDTH + 1
            if avail and new_left < avail.left():
                new_left = avail.left()
            g.setLeft(new_left)
        if self._resize_edges & 2:
            new_right = g.right() + delta.x()
            if new_right - g.left() + 1 < _MIN_WIDTH:
                new_right = g.left() + _MIN_WIDTH - 1
            if avail and new_right > avail.right():
                new_right = avail.right()
            g.setRight(new_right)
        if self._resize_edges & 4:
            new_top = g.top() + delta.y()
            if g.bottom() - new_top + 1 < _MIN_HEIGHT:
                new_top = g.bottom() - _MIN_HEIGHT + 1
            if avail and new_top < avail.top():
                new_top = avail.top()
            g.setTop(new_top)
        if self._resize_edges & 8:
            new_bottom = g.bottom() + delta.y()
            if new_bottom - g.top() + 1 < _MIN_HEIGHT:
                new_bottom = g.top() + _MIN_HEIGHT - 1
            if avail and new_bottom > avail.bottom():
                new_bottom = avail.bottom()
            g.setBottom(new_bottom)
        self.setGeometry(g)
        self.repaint()

    def _finish_resize(self) -> None:
        if self._resize_start_geom is not None:
            self._user_resized = True
        self._resize_edges = 0
        self._resize_start_geom = None
        self._resize_start_global = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self._begin_resize(edges, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._resize_edges:
            self._update_resize(event.globalPosition().toPoint())
            return
        edges = self._edges_at(event.position().toPoint())
        if edges:
            self.setCursor(self._cursor_for_edges(edges))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._finish_resize()
        super().mouseReleaseEvent(event)
