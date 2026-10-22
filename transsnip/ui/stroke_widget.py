"""Animated stroke-order view for one Chinese character.

Each stroke is revealed along its median: the filled stroke outline is clipped
by a fat round-capped polyline covering the first `t` of the median, which
looks like a brush tracing the stroke (same trick as Hanzi Writer).
"""
from __future__ import annotations

import itertools
import math
import re

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPaintEvent,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from transsnip.learning.zh.strokes import CharStrokes
from transsnip.ui.theme import get_theme
from transsnip.ui.tokens import qcolor

_BOX = 1024.0
_Y_FLIP = 900.0  # MMAH glyphs sit in a 1024 box with baseline offset; y' = 900 - y
_BRUSH = 128.0  # clip-pen width in data units — wide enough to cover any stroke
_FRAME_MS = 16
_PAUSE_MS = 150
_TOKEN_RE = re.compile(r"[MLQCZ]|-?\d+(?:\.\d+)?")
_ARITY = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}


def parse_svg_path(d: str) -> QPainterPath:
    """Parse MMAH's absolute M/L/Q/C/Z paths, flipping Y into screen space."""
    path = QPainterPath()
    tokens = _TOKEN_RE.findall(d)
    i, cmd = 0, ""
    while i < len(tokens):
        if tokens[i] in _ARITY:
            cmd = tokens[i]
            i += 1
            if cmd == "Z":
                path.closeSubpath()
                continue
        n = _ARITY.get(cmd, 0)
        if n == 0 or i + n > len(tokens):
            break  # stray number or truncated command — keep what parsed so far
        v = [float(x) for x in tokens[i:i + n]]
        i += n
        pts = [QPointF(v[k], _Y_FLIP - v[k + 1]) for k in range(0, n, 2)]
        if cmd == "M":
            path.moveTo(pts[0])
            cmd = "L"  # implicit repeats after M are line-tos (SVG rule)
        elif cmd == "L":
            path.lineTo(pts[0])
        elif cmd == "Q":
            path.quadTo(pts[0], pts[1])
        else:
            path.cubicTo(pts[0], pts[1], pts[2])
    return path




class StrokeOrderWidget(QWidget):
    """Square widget animating a character's strokes. Click to replay."""

    finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._char = ""
        self._paths: list[QPainterPath] = []
        self._medians: list[list[QPointF]] = []
        self._lengths: list[float] = []
        self._speed = 1.0
        self._index = 0  # stroke currently animating; == len → done
        self._elapsed = 0.0  # ms into current stroke (incl. trailing pause)
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    # ── Public API ─────────────────────────────────────────────────────────

    def set_char(self, char: str, data: CharStrokes | None) -> None:
        self._timer.stop()
        self._char = char
        self._paths = [parse_svg_path(s) for s in data.strokes] if data else []
        self._medians = (
            [[QPointF(x, _Y_FLIP - y) for x, y in m] for m in data.medians] if data else []
        )
        self._lengths = [_poly_len(m) for m in self._medians]
        self._index, self._elapsed = 0, 0.0
        self.update()

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        self._speed = max(0.1, float(value))

    def is_playing(self) -> bool:
        return self._timer.isActive()

    def play(self) -> None:
        if not self._paths:
            return
        if self._index >= len(self._paths):
            self._index, self._elapsed = 0, 0.0
        self._timer.start()

    def pause(self) -> None:
        self._timer.stop()

    def replay(self) -> None:
        self._index, self._elapsed = 0, 0.0
        self.update()
        self.play()

    def stroke_duration(self, i: int) -> float:
        """Draw time in ms: ~0.5 s for a dot, up to ~1 s for a long sweep."""
        return (500.0 + 500.0 * min(1.0, self._lengths[i] / 800.0)) / self._speed

    # ── Animation ──────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self.step(_FRAME_MS)

    def step(self, ms: float) -> None:
        """Advance the animation by `ms`; public so tests can drive it."""
        if self._index >= len(self._paths):
            self._timer.stop()
            return
        self._elapsed += ms
        while self._index < len(self._paths):
            total = self.stroke_duration(self._index) + _PAUSE_MS / self._speed
            if self._elapsed < total:
                break
            self._elapsed -= total
            self._index += 1
        if self._index >= len(self._paths):
            self._timer.stop()
            self.update()
            self.finished.emit()
            return
        self.update()

    def _progress(self) -> float:
        return min(1.0, self._elapsed / self.stroke_duration(self._index))

    # ── Qt overrides ───────────────────────────────────────────────────────

    def sizeHint(self) -> QSize:
        return QSize(160, 160)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return w

    def hideEvent(self, event) -> None:
        self._timer.stop()  # never tick for an invisible widget
        super().hideEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.replay()
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        margin = max(4.0, side * 0.04)
        box = QRectF(
            (self.width() - side) / 2 + margin, (self.height() - side) / 2 + margin,
            side - 2 * margin, side - 2 * margin,
        )
        painter.fillRect(box, qcolor(p.glass_1))
        self._paint_grid(painter, box, qcolor(p.border_2))

        if not self._paths:
            painter.setPen(qcolor(p.text_3))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             "Chưa có dữ liệu cách viết")
            return

        scale = box.width() / _BOX
        painter.setTransform(QTransform().translate(box.x(), box.y()).scale(scale, scale))
        painter.setPen(Qt.PenStyle.NoPen)
        faint = qcolor(p.text_3)
        faint.setAlpha(70)
        for path in self._paths:
            painter.fillPath(path, faint)
        solid = QBrush(qcolor(p.text_1))
        for path in self._paths[: self._index]:
            painter.fillPath(path, solid)
        if self._index < len(self._paths):
            i = self._index
            clip = _reveal_shape(self._medians[i], self._lengths[i] * self._progress())
            if not clip.isEmpty():
                painter.fillPath(self._paths[i].intersected(clip), qcolor(p.accent))

    @staticmethod
    def _paint_grid(painter: QPainter, box: QRectF, color: QColor) -> None:
        """米字格: border, centre cross and diagonals as dashed guides."""
        pen = QPen(color, 1)
        painter.setPen(pen)
        painter.drawRect(box)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        c = box.center()
        painter.drawLine(QPointF(box.left(), c.y()), QPointF(box.right(), c.y()))
        painter.drawLine(QPointF(c.x(), box.top()), QPointF(c.x(), box.bottom()))
        painter.drawLine(box.topLeft(), box.bottomRight())
        painter.drawLine(box.topRight(), box.bottomLeft())


def _poly_len(pts: list[QPointF]) -> float:
    return sum(math.dist((a.x(), a.y()), (b.x(), b.y())) for a, b in itertools.pairwise(pts))


def _reveal_shape(pts: list[QPointF], length: float) -> QPainterPath:
    """Fat round-capped polyline over the first `length` units of the median."""
    if not pts or length <= 0:
        return QPainterPath()
    line = QPainterPath(pts[0])
    left = length
    for a, b in itertools.pairwise(pts):
        seg = math.dist((a.x(), a.y()), (b.x(), b.y()))
        if seg >= left:
            f = left / seg if seg else 0.0
            line.lineTo(a + (b - a) * f)
            break
        line.lineTo(b)
        left -= seg
    if line.elementCount() == 1:
        line.lineTo(pts[0] + QPointF(0.01, 0))  # a lone moveTo strokes to nothing
    stroker = QPainterPathStroker()
    stroker.setWidth(_BRUSH)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(line)
