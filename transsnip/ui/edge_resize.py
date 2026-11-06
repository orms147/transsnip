"""Drag-to-resize from the border of a frameless window.

Hovering within a few px of the edge shows the resize cursor; pressing there
hands the drag to the OS (QWindow.startSystemResize) — smooth, snaps like a
native window, and honours the window's minimumSize.

Usage — one line in the window's __init__:

    self._edge_resize = EdgeResize(self)

Mouse events are watched at the QWindow level (via an app-wide filter, only
while the window is visible): Qt delivers every hover move to the QWindow,
but to a child widget only if that widget tracks the mouse.
"""
from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtWidgets import QApplication, QScrollBar, QWidget

_MARGIN = 6

_LEFT, _RIGHT, _TOP, _BOTTOM = (Qt.Edge.LeftEdge, Qt.Edge.RightEdge,
                                Qt.Edge.TopEdge, Qt.Edge.BottomEdge)


def edges_at(pos: QPoint, width: int, height: int, margin: int = _MARGIN) -> Qt.Edge:
    edges = Qt.Edge(0)
    if pos.x() <= margin:
        edges |= _LEFT
    elif pos.x() >= width - margin:
        edges |= _RIGHT
    if pos.y() <= margin:
        edges |= _TOP
    elif pos.y() >= height - margin:
        edges |= _BOTTOM
    return edges


def cursor_for(edges: Qt.Edge) -> Qt.CursorShape:
    if edges in (_LEFT | _TOP, _RIGHT | _BOTTOM):
        return Qt.CursorShape.SizeFDiagCursor
    if edges in (_RIGHT | _TOP, _LEFT | _BOTTOM):
        return Qt.CursorShape.SizeBDiagCursor
    if edges & (_LEFT | _RIGHT):
        return Qt.CursorShape.SizeHorCursor
    return Qt.CursorShape.SizeVerCursor


class EdgeResize(QObject):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._win = window
        self._cursor_set = False
        window.installEventFilter(self)

    def _edges(self, pos: QPoint) -> Qt.Edge:
        edges = edges_at(pos, self._win.width(), self._win.height())
        # The vertical scrollbar hugs the right edge: there it scrolls, not resizes.
        if edges & _RIGHT and isinstance(self._win.childAt(pos), QScrollBar):
            edges &= ~_RIGHT
        return edges

    def _clear_cursor(self) -> None:
        if self._cursor_set:
            self._win.unsetCursor()
            self._cursor_set = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        et = event.type()
        if watched is self._win:
            app = QApplication.instance()
            if et == QEvent.Type.Show and app is not None:
                app.installEventFilter(self)
            elif et == QEvent.Type.Hide and app is not None:
                app.removeEventFilter(self)
                self._clear_cursor()
            return False
        if not shiboken6.isValid(self._win):     # window deleted while shown
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            return False
        if self._win.isMaximized() or watched is not self._win.windowHandle():
            return False
        if et == QEvent.Type.Leave:
            self._clear_cursor()
        elif et == QEvent.Type.MouseMove and event.buttons() == Qt.MouseButton.NoButton:
            edges = self._edges(event.position().toPoint())
            if edges:
                self._win.setCursor(cursor_for(edges))
                self._cursor_set = True
            else:
                self._clear_cursor()
        elif et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges(event.position().toPoint())
            if edges and self._win.windowHandle().startSystemResize(edges):
                return True
        return False
