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

import time

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
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
_BOTTOM_MARGIN = 80  # px above the monitor bottom for the audio-anchored bar

# Readability pacing: a freshly shown line stays on screen for at least the time
# it takes to read it (chars ÷ reading speed), so back-to-back translations don't
# flash past unread. Lines that arrive during that window are coalesced (only the
# newest is kept) and shown once the current one has had its dwell.
_READING_CPS = 15      # characters/second a viewer reads comfortably (Vietnamese)
_MIN_DWELL_MS = 1200   # even a 2-word line lingers this long
_MAX_DWELL_MS = 7000   # never hold longer than this (else subtitles desync badly)


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
        self._anchor_monitor: QRect | None = None  # set by start_anchored (audio mode)
        self._text = ""
        self._status = "Đang nghe phụ đề…"   # shown until the first translation lands
        self._bg_alpha = 235                  # 0-255; set via set_bg_opacity()
        self._font_pt = _FONT_PT              # set via set_font_pt()
        self._user_moved = False              # once dragged, stop auto-anchoring
        self._drag_offset: QPoint | None = None
        # Readability pacing (see set_text / _display).
        self._shown_at = 0.0                  # time.monotonic() of the current line
        self._shown_dwell_ms = 0              # min ms the current line must stay
        self._pending: str | None = None      # latest line waiting for the dwell
        self._dwell_timer = QTimer(self)
        self._dwell_timer.setSingleShot(True)
        self._dwell_timer.timeout.connect(self._show_pending)

    # ── Public API ───────────────────────────────────────────────────────────

    def start_for_region(self, region: QRect) -> None:
        """Anchor the bar below `region` (logical coords) and show the waiting state."""
        self._region = region
        self._anchor_monitor = None
        self._text = ""
        self._status = "Đang nghe phụ đề…"
        self._user_moved = False
        self._reset_pacing()
        self._relayout()
        self.show()
        self.raise_()

    def start_anchored(self, monitor_rect: QRect) -> None:
        """Audio mode: no source region — anchor near the BOTTOM of `monitor_rect`.

        `_region` is left null so the self-capture nudge (`_nudge_out_of_region`,
        which guards the OCR video mode) becomes a no-op here.
        """
        self._region = QRect()
        self._anchor_monitor = monitor_rect
        self._text = ""
        self._status = "Đang nghe âm thanh…"
        self._user_moved = False
        self._reset_pacing()
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
        """Queue a freshly translated line, respecting the current line's dwell.

        If the line on screen has been visible long enough to read, show the new
        one immediately. Otherwise hold it (coalescing to the newest) until the
        current line has had its minimum on-screen time — so dense, back-to-back
        translations don't flash past before the viewer can read them.
        """
        text = text.strip()
        if not text:
            return
        elapsed_ms = (time.monotonic() - self._shown_at) * 1000.0
        if self._status or elapsed_ms >= self._shown_dwell_ms:
            self._dwell_timer.stop()
            self._pending = None
            self._display(text)
        else:
            self._pending = text   # newest wins; shown when the dwell expires
            self._dwell_timer.start(int(max(0.0, self._shown_dwell_ms - elapsed_ms)))

    def _show_pending(self) -> None:
        if self._pending is not None:
            text, self._pending = self._pending, None
            self._display(text)

    def _display(self, text: str) -> None:
        self._text = text
        self._status = ""
        self._shown_at = time.monotonic()
        self._shown_dwell_ms = int(
            max(_MIN_DWELL_MS, min(_MAX_DWELL_MS, len(text) * 1000.0 / _READING_CPS))
        )
        self._relayout()
        self.update()

    def _reset_pacing(self) -> None:
        self._dwell_timer.stop()
        self._pending = None
        self._shown_at = 0.0
        self._shown_dwell_ms = 0

    def stop(self) -> None:
        self.hide()
        self._text = ""
        self._reset_pacing()

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
        # Snap out of the capture region if the user dropped the bar over it —
        # otherwise the next OCR poll would read the bar's own translated text
        # back in as "source" (the self-capture trap).
        self._nudge_out_of_region()
        event.accept()

    def _nudge_out_of_region(self) -> None:
        """If the bar overlaps the subtitle region, push it just below (or above
        if no room below) so screen captures of the region never include it."""
        if self._region.isNull():
            return
        rect = self.frameGeometry()
        if not rect.intersects(self._region):
            return
        screen = QGuiApplication.screenAt(self._region.center()) or QGuiApplication.primaryScreen()
        geo = screen.geometry() if screen is not None else rect
        below_y = self._region.bottom() + _GAP
        if below_y + rect.height() <= geo.bottom():
            self.move(rect.x(), below_y)
        else:
            self.move(rect.x(), self._region.top() - _GAP - rect.height())

    # ── Layout ───────────────────────────────────────────────────────────────

    def _relayout(self) -> None:
        """Size to the text. Anchor below the region unless the user moved it."""
        # Audio mode: no source region → anchor near the bottom-center of the monitor.
        if self._anchor_monitor is not None and self._region.isNull():
            mon = self._anchor_monitor
            width = max(_MIN_W, int(mon.width() * 0.6))
            inner_w = width - 2 * _PAD_X
            body = self._text or self._status
            bound = QFontMetrics(self._font()).boundingRect(
                QRect(0, 0, inner_w, 10_000),
                int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter),
                body or " ",
            )
            height = bound.height() + 2 * _PAD_Y
            if self._user_moved:
                self.resize(width, height)
                return
            x = mon.x() + (mon.width() - width) // 2
            y = mon.bottom() - height - _BOTTOM_MARGIN
            self.setGeometry(x, y, width, height)
            return

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
            # Keep where the user parked it; only resize (anchor top-left)…
            self.resize(width, height)
            # …but if the resize now makes it overlap the region, push it out
            # (a taller translation could grow back into the source area).
            self._nudge_out_of_region()
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
