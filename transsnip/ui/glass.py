""""Liquid glass" windows: live backdrop blur + a painted glass slab.

Qt can't blur what's BEHIND a window — only the compositor can. We ask DWM
for an acrylic blur via SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLIC-
BLURBEHIND): unlike Windows 11's official DWMWA_SYSTEMBACKDROP_TYPE acrylic
(measured: a near-opaque grey slab in dark mode), it takes our own tint and
lets the colours of the video/page underneath glow through, iOS-style. It
works from Windows 10 1803 up.

On top of the blur we paint a translucent tint, a soft top-left sheen and a
bright rim (the glass edge). Without blur (glass off, old Windows, non-Win)
the same painter fills opaquely so text stays readable.

Usage — one line in a frameless, WA_TranslucentBackground window:

    self._glass = Glass(self)

Child containers must not paint opaque backgrounds (use the `glass_*`
palette tokens for cards/controls inside).
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QScrollArea, QWidget

from transsnip.ui.theme import get_theme
from transsnip.ui.tokens import DARK

log = logging.getLogger(__name__)

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2
_WCA_ACCENT_POLICY = 19
_ACCENT_DISABLED = 0
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_ACCENT_FLAG_GRADIENT = 2

# Tint of the slab (also handed to DWM as the acrylic colour), keyed by dark.
# Alphas tuned on screenshots over a bright, busy background: lower = more
# "liquid", but text must stay readable over white video frames too.
_TINT = {True: QColor("#14161c"), False: QColor("#f7f8fb")}
_TINT_ALPHA = {True: 95, False: 45}
_ACRYLIC_ALPHA = {True: 0x40, False: 0x30}


class _AccentPolicy(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _WcaData(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


def set_backdrop(widget: QWidget, *, dark: bool, on: bool) -> bool:
    """Turn the acrylic blur behind `widget`'s native window on/off.

    Needs a native window (call from a Show event or later). Returns True if
    the blur is active, False when off or unsupported — callers paint opaque.
    """
    if sys.platform != "win32" or sys.getwindowsversion().build < 17134:
        return False
    try:
        hwnd = wintypes.HWND(int(widget.winId()))
        dwm = ctypes.windll.dwmapi
        for attr, value in ((_DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark)),
                            (_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        tint = _TINT[dark]
        abgr = ((_ACRYLIC_ALPHA[dark] << 24) | (tint.blue() << 16)
                | (tint.green() << 8) | tint.red())
        policy = _AccentPolicy(_ACCENT_ENABLE_ACRYLICBLURBEHIND if on else _ACCENT_DISABLED,
                               _ACCENT_FLAG_GRADIENT, abgr, 0)
        data = _WcaData(_WCA_ACCENT_POLICY,
                        ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p),
                        ctypes.sizeof(policy))
        ok = bool(ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))
        return ok and on
    except (AttributeError, OSError) as exc:
        log.debug("backdrop unavailable: %s", exc)
        return False


def paint_glass(painter: QPainter, rect: QRectF, radius: float, *, dark: bool,
                blurred: bool) -> None:
    """Glass slab: tint + top-left sheen + bright rim. `blurred` = backdrop
    active (translucent tint lets it show); otherwise an opaque fill."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    base = QColor(_TINT[dark])
    base.setAlpha(_TINT_ALPHA[dark] if blurred else 255)
    painter.fillPath(path, base)

    # Sheen: light falling from the top-left, fading out by mid-height.
    sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left() + rect.width() * 0.35,
                                                   rect.top() + rect.height() * 0.6))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 30 if dark else 70))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(path, QBrush(sheen))

    # Rim: brighter along the top edge, dimmer mid-way — reads as a thick
    # glass edge catching light.
    rim = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    rim.setColorAt(0.0, QColor(255, 255, 255, 70 if dark else 230))
    rim.setColorAt(0.5, QColor(255, 255, 255, 18 if dark else 120))
    rim.setColorAt(1.0, QColor(255, 255, 255, 40 if dark else 170))
    painter.setBrush(QBrush())
    if dark:
        painter.setPen(QPen(QBrush(rim), 1.2))
        painter.drawPath(path)
        return
    # Light: a white rim alone vanishes over a white page — add a faint dark
    # outline and draw the bright rim just inside it.
    painter.setPen(QPen(QColor(15, 23, 42, 40), 1.0))
    painter.drawPath(path)
    inner = QPainterPath()
    inner.addRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
    painter.setPen(QPen(QBrush(rim), 1.2))
    painter.drawPath(inner)


class Glass(QObject):
    """Turns a frameless, WA_TranslucentBackground top-level into glass.

    Paints the slab under the window's children (via an event filter, so the
    host needs no paintEvent of its own), (re)applies the blur each time the
    native window is shown, and follows the theme's dark/light + glass on/off.
    """

    def __init__(self, window: QWidget, radius: float | None = None) -> None:
        super().__init__(window)
        self._win = window
        self._radius = radius
        self._blurred = False
        window.installEventFilter(self)
        get_theme().mode_changed.connect(lambda _p: self._refresh())

    @property
    def blurred(self) -> bool:
        return self._blurred

    @staticmethod
    def _dark() -> bool:
        return get_theme().palette is DARK

    def _refresh(self) -> None:
        if self._win.isVisible():
            self._apply()
            self._win.update()

    def _apply(self) -> None:
        self._blurred = set_backdrop(self._win, dark=self._dark(), on=get_theme().glass)

    def _clear_scroll_fills(self) -> None:
        # QScrollArea.setWidget() turns autoFillBackground ON for the content
        # widget, which then paints the opaque palette Window colour over the
        # glass. Content is (re)built lazily, so re-check on every show.
        for area in self._win.findChildren(QScrollArea):
            area.viewport().setAutoFillBackground(False)
            if area.widget() is not None:
                area.widget().setAutoFillBackground(False)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._win:
            if event.type() == QEvent.Type.Show:
                self._clear_scroll_fills()
                self._apply()
            elif event.type() == QEvent.Type.Paint:
                radius = get_theme().palette.r_popup if self._radius is None else self._radius
                painter = QPainter(self._win)
                paint_glass(painter, QRectF(self._win.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                            radius, dark=self._dark(), blurred=self._blurred)
                painter.end()
        return False
