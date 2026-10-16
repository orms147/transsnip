"""Click-outside / focus-loss dismissal for the popup (mixin)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QScrollBar,
    QWidget,
)


class _OutsideDismissMixin:
    """App-wide event filter + focus-loss handling for FloatingPopup.

    Relies on the host widget's `_filter_installed`, `_click_outside_close`,
    `_pinned`, `_resize_edges` state and its `hide_popup()` / resize helpers.
    """

    def _install_event_filter(self) -> None:
        if self._filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._filter_installed = True

    def _remove_event_filter(self) -> None:
        if not self._filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._filter_installed = False

    def _is_self_or_descendant(self, watched) -> bool:
        w = watched if isinstance(watched, QWidget) else None
        while w is not None:
            if w is self:
                return True
            w = w.parentWidget()
        return False

    def eventFilter(self, watched, event):
        et = event.type()
        # Drag-resize in progress — handle every move/release app-wide (the
        # cursor may be over a child label, whose own handlers we bypass).
        if self._resize_edges:
            if et == QEvent.Type.MouseMove:
                self._update_resize(event.globalPosition().toPoint())
                return True
            if et == QEvent.Type.MouseButtonRelease:
                self._finish_resize()
                return True

        if not self.isVisible():
            return super().eventFilter(watched, event)
        inside = self._is_self_or_descendant(watched)
        # The vertical scrollbar sits ON the right resize edge. Without this,
        # hovering/clicking it showed the ↔ resize cursor and started a resize
        # instead of scrolling. When the pointer is over the scrollbar, suppress
        # edge-resize so it behaves like a normal scrollbar.
        over_scrollbar = isinstance(watched, QScrollBar)

        if et == QEvent.Type.MouseButtonPress:
            try:
                gp = event.globalPosition().toPoint()
            except AttributeError:
                return super().eventFilter(watched, event)
            if inside:
                # Near an edge → START resize even though a selectable label is
                # under the cursor; consume so it doesn't begin a text selection
                # instead of resizing.
                if event.button() == Qt.MouseButton.LeftButton and not over_scrollbar:
                    edges = self._edges_at(self.mapFromGlobal(gp))
                    if edges:
                        self._begin_resize(edges, gp)
                        return True
                return super().eventFilter(watched, event)
            if self._click_outside_close and not self._pinned \
                    and not self.geometry().contains(gp):
                self.hide_popup()
        elif et == QEvent.Type.MouseMove and inside:
            # Show the resize cursor ONLY on the popup's own outer edge. We set
            # it on `self` (children inherit it) and clear it back to the normal
            # arrow the moment the pointer leaves the edge band. The previous
            # code set the cursor on whatever child `watched` was and failed to
            # clear it when the pointer crossed to a sibling — children then
            # inherited a stuck ↔ cursor across the whole popup.
            try:
                gp = event.globalPosition().toPoint()
            except AttributeError:
                return super().eventFilter(watched, event)
            edges = 0 if over_scrollbar else self._edges_at(self.mapFromGlobal(gp))
            if edges:
                self.setCursor(self._cursor_for_edges(edges))
                self._edge_cursor_active = True
            elif self._edge_cursor_active:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self._edge_cursor_active = False
        return super().eventFilter(watched, event)

    def changeEvent(self, event) -> None:
        # Close on losing window focus (user clicked ANOTHER application/window).
        # The app-level eventFilter only sees clicks on our own widgets, so for
        # clicks on a foreign window this WindowDeactivate is what fires.
        if (
            event.type() == QEvent.Type.ActivationChange
            and self._click_outside_close
            and not self._pinned
            and self.isVisible()
            and not self.isActiveWindow()
            and self._resize_edges == 0
        ):
            # Defer so we don't hide mid-event (e.g. while focus is transferring
            # to our own settings window the user opened from the popup gear).
            QTimer.singleShot(0, self._close_if_truly_outside)
        super().changeEvent(event)

    def _close_if_truly_outside(self) -> None:
        # Re-check on the next tick: if focus went to one of our OWN windows
        # (settings/about/history) we keep the popup; only a foreign window or
        # the desktop should dismiss it.
        if not self._click_outside_close or self._pinned or not self.isVisible():
            return
        active = QApplication.activeWindow()
        if active is None or active is not self:
            self.hide_popup()
