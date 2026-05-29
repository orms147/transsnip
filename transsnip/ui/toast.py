"""ToastStack — slide-in notifications anchored to a screen corner.

Replaces `QSystemTrayIcon.showMessage` calls in AppController so we have
full control over styling and tone variants (success / info / warn). Each
toast auto-dismisses after a timeout with an animated progress bar; the
user can also click the × to dismiss early. Up to 3 toasts visible at a
time — older ones slide off the top when a fourth arrives.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from transsnip.ui import icons
from transsnip.ui.atoms import IconButton
from transsnip.ui.theme import get_theme

log = logging.getLogger(__name__)

_TOAST_WIDTH = 340
_TOAST_PADDING = 16
_DEFAULT_DURATION_MS = 4500
_MAX_TOASTS = 3


class _Toast(QWidget):
    """Single notification card. Self-dismissing after `duration_ms`."""

    dismissed = Signal(object)  # emits self

    def __init__(
        self,
        title: str,
        description: str = "",
        *,
        tone: str = "default",
        icon_name: str = "info",
        duration_ms: int = _DEFAULT_DURATION_MS,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._tone = tone
        self._duration_ms = duration_ms
        self._progress = 1.0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_TOAST_PADDING, 12, 8, 16)
        layout.setSpacing(12)

        # Icon column
        self._icon_widget = QLabel()
        self._icon_widget.setFixedSize(32, 32)
        self._icon_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_name = icon_name
        layout.addWidget(self._icon_widget, alignment=Qt.AlignmentFlag.AlignTop)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._title_label = QLabel(title)
        text_col.addWidget(self._title_label)
        if description:
            self._desc_label = QLabel(description)
            self._desc_label.setWordWrap(True)
            text_col.addWidget(self._desc_label)
        else:
            self._desc_label = None
        layout.addLayout(text_col, stretch=1)

        # Close button
        self._close_btn = IconButton("close", size=24, icon_size=10, tooltip="Dismiss")
        self._close_btn.clicked.connect(self._on_close)
        layout.addWidget(self._close_btn, alignment=Qt.AlignmentFlag.AlignTop)

        # Progress bar timer — ticks 20fps for smooth-ish drain.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._elapsed_ms = 0

        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def start(self) -> None:
        self.show()
        self._timer.start(50)

    def _tick(self) -> None:
        self._elapsed_ms += 50
        self._progress = max(0.0, 1.0 - self._elapsed_ms / self._duration_ms)
        self.update()
        if self._progress <= 0.0:
            self._on_close()

    def _on_close(self) -> None:
        self._timer.stop()
        self.dismissed.emit(self)
        self.deleteLater()

    def _apply_style(self) -> None:
        p = get_theme().palette
        if self._tone == "success":
            icon_color = p.success
        elif self._tone == "warn":
            icon_color = p.warning
        else:
            icon_color = p.text_2
        self._icon_widget.setPixmap(icons.get_pixmap(self._icon_name, color=icon_color, size=16))
        self._icon_widget.setStyleSheet(
            f"background: {p.bg_2}; border-radius: 8px;"
        )
        self._title_label.setStyleSheet(
            f"color: {p.text_1}; font-size: 12px; font-weight: 600;"
        )
        if self._desc_label:
            self._desc_label.setStyleSheet(
                f"color: {p.text_3}; font-size: 11px; line-height: 1.4;"
            )

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Card background
        rect_f = self.rect().adjusted(0, 0, -1, -4)  # leave room for progress bar
        painter.setBrush(QBrush(QColor(p.bg_1)))
        painter.setPen(QPen(QColor(p.border_2), 1))
        painter.drawRoundedRect(rect_f, 10, 10)

        # Progress bar at bottom — fills from full → empty as timer drains.
        bar_color = {
            "success": p.success,
            "warn": p.warning,
        }.get(self._tone, p.accent)
        bar_y = self.height() - 3
        bar_w = int((self.width() - 4) * self._progress)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bar_color))
        painter.drawRoundedRect(2, bar_y, bar_w, 2, 1, 1)


class ToastStack(QWidget):
    """Container anchored to a screen corner. Add toasts via `show_toast`."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # Block clicks from reaching widgets behind — toast actions, but the
        # background should be transparent to clicks elsewhere. Easiest: only
        # the toast widgets themselves receive input via their hit area.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._toasts: list[_Toast] = []

        self.resize(_TOAST_WIDTH, 100)

    def show_toast(
        self,
        title: str,
        description: str = "",
        *,
        tone: str = "default",
        icon_name: Optional[str] = None,
        duration_ms: int = _DEFAULT_DURATION_MS,
    ) -> None:
        """Push a new toast onto the stack, pruning the oldest if at cap."""
        if icon_name is None:
            icon_name = {"success": "check", "warn": "alert"}.get(tone, "info")
        if len(self._toasts) >= _MAX_TOASTS:
            oldest = self._toasts.pop(0)
            oldest._on_close()
        toast = _Toast(
            title,
            description,
            tone=tone,
            icon_name=icon_name,
            duration_ms=duration_ms,
            parent=self,
        )
        toast.dismissed.connect(self._on_dismissed)
        self._layout.addWidget(toast)
        toast.setFixedWidth(_TOAST_WIDTH)
        toast.adjustSize()
        toast.start()
        self._toasts.append(toast)
        self._reposition()

    def _on_dismissed(self, toast: _Toast) -> None:
        try:
            self._toasts.remove(toast)
        except ValueError:
            return
        self._reposition()

    def _reposition(self) -> None:
        # Anchor to bottom-right of the screen with the cursor (so toasts
        # appear where the user is).
        cursor_pos = QGuiApplication.primaryScreen().geometry()
        screen = QGuiApplication.screenAt(cursor_pos.center()) \
            or QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        self.adjustSize()
        x = avail.right() - self.width() - 20
        y = avail.bottom() - self.height() - 20
        self.move(x, y)
        if self._toasts and not self.isVisible():
            self.show()
        elif not self._toasts:
            self.hide()


# Singleton accessor so AppController gets the same stack every call.
_toast_stack: Optional[ToastStack] = None


def get_toast_stack() -> ToastStack:
    global _toast_stack
    if _toast_stack is None:
        _toast_stack = ToastStack()
    return _toast_stack
