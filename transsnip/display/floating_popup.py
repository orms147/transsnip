from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transsnip.translate.base import TranslationResult

log = logging.getLogger(__name__)

_DEFAULT_WIDTH = 500
_DEFAULT_HEIGHT = 460
_MIN_WIDTH = 280
_MIN_HEIGHT = 120
_MARGIN_FROM_EDGE = 16
_GAP_FROM_REGION = 12
_RESIZE_MARGIN = 6  # px from the edge that counts as a resize handle

_BG_COLOR = QColor(22, 22, 26, 245)
_BORDER_COLOR = QColor(70, 70, 75, 220)
_BORDER_RADIUS = 10

_STYLESHEET = """
QLabel#source {
    color: rgba(190, 190, 200, 230);
    font-size: 13px;
    line-height: 1.55;
    padding: 0;
}
QFrame#separator {
    background-color: rgba(80, 80, 90, 160);
    margin: 2px 0;
}
QLabel#translation {
    color: rgba(245, 245, 250, 255);
    font-size: 14px;
    font-weight: 600;
    line-height: 1.6;
    padding: 0;
}
QLabel#status {
    color: rgba(140, 140, 150, 200);
    font-size: 10px;
    letter-spacing: 0.3px;
}
QLabel#appTitle {
    color: rgba(220, 220, 230, 230);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.4px;
}
QPushButton#iconBtn {
    background-color: transparent;
    color: rgba(200, 200, 210, 220);
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 13px;
    min-width: 24px;
}
QPushButton#iconBtn:hover {
    background-color: rgba(255, 255, 255, 30);
    color: white;
}
QPushButton#iconBtn:pressed {
    background-color: rgba(255, 255, 255, 50);
}
QPushButton#closeBtn {
    background-color: transparent;
    color: rgba(180, 180, 190, 200);
    border: none;
    border-radius: 6px;
    padding: 2px 6px;
    font-size: 16px;
    font-weight: 500;
    min-width: 22px;
}
QPushButton#closeBtn:hover {
    background-color: rgba(232, 80, 80, 200);
    color: white;
}
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 4px 2px 4px 0;
}
QScrollBar::handle:vertical {
    background: rgba(130, 130, 140, 140);
    border-radius: 3px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(180, 180, 190, 220);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0;
}
"""


class _DragBar(QWidget):
    """Empty bar widget that moves its top-level window when dragged.

    Using a dedicated drag widget (rather than catching presses on the whole
    popup) keeps the text body click-through for selection — only the top
    strip starts a window move, matching the Trancy-style toolbar pattern.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMinimumHeight(20)
        self._press_global: QPoint | None = None
        self._press_frame_topleft: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_frame_topleft = self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._press_global is not None
            and self._press_frame_topleft is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.globalPosition().toPoint() - self._press_global
            self.window().move(self._press_frame_topleft + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_global = None
        self._press_frame_topleft = None
        super().mouseReleaseEvent(event)


class FloatingPopup(QWidget):
    """Popup hiện cạnh vùng đã chọn, cập nhật theo từng giai đoạn của pipeline."""

    closed = Signal()
    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("FloatingPopupRoot")
        # WA_TranslucentBackground: without this, resizing a frameless window with
        # an rgba (alpha < 255) background leaves "ghost" pixels from the previous
        # frame because the OS never clears the area between paints. With it, Qt
        # composites each frame fresh so the QSS-painted rounded box redraws cleanly.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(_STYLESHEET)
        self.setMouseTracking(True)
        self._build_ui()
        self._filter_installed = False
        self._last_region: QRect | None = None
        self._last_translation = ""
        # Resize state
        self._resize_edges: int = 0  # bitmask: 1=left 2=right 4=top 8=bottom
        self._resize_start_geom: QRect | None = None
        self._resize_start_global: QPoint | None = None

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 14, 12)
        root.setSpacing(8)

        # Toolbar: app title on the left, a drag handle filling the middle
        # (cursor turns into a move handle there), action buttons on the right.
        # The body below stays drag-free so text selection feels natural.
        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        top_row.setContentsMargins(0, 0, 0, 0)

        self._app_title = QLabel("TransSnip")
        self._app_title.setObjectName("appTitle")
        self._app_title.setCursor(Qt.CursorShape.ArrowCursor)
        top_row.addWidget(self._app_title)

        self._drag_bar = _DragBar(self)
        top_row.addWidget(self._drag_bar, stretch=1)

        self._status_label = QLabel()
        self._status_label.setObjectName("status")
        self._status_label.setCursor(Qt.CursorShape.ArrowCursor)
        top_row.addWidget(self._status_label)

        self._settings_button = QPushButton("⚙")
        self._settings_button.setObjectName("iconBtn")
        self._settings_button.setToolTip("Open settings")
        self._settings_button.clicked.connect(self.settings_requested.emit)
        self._settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        top_row.addWidget(self._settings_button)

        self._copy_button = QPushButton("⧉")
        self._copy_button.setObjectName("iconBtn")
        self._copy_button.setToolTip("Copy translation")
        self._copy_button.clicked.connect(self._on_copy)
        self._copy_button.hide()
        self._copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        top_row.addWidget(self._copy_button)

        self._close_button = QPushButton("×")
        self._close_button.setObjectName("closeBtn")
        self._close_button.setToolTip("Close (Esc)")
        self._close_button.setFixedWidth(28)
        self._close_button.clicked.connect(self.hide_popup)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        top_row.addWidget(self._close_button)

        root.addLayout(top_row)

        # Source + separator + translation live inside a scroll area so long
        # translations remain readable without forcing the popup taller than
        # the screen. Wheel-scroll on the labels passes through to this area.
        self._scroll = QScrollArea()
        self._scroll.setObjectName("scrollArea")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Transparent background so the popup's painted background shows through.
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")

        scroll_content = QWidget()
        scroll_content.setObjectName("scrollContent")
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(2, 4, 6, 4)
        content_layout.setSpacing(10)

        self._source_label = QLabel()
        self._source_label.setObjectName("source")
        self._source_label.setWordWrap(True)
        self._source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._source_label.setCursor(Qt.CursorShape.ArrowCursor)
        self._source_label.hide()
        content_layout.addWidget(self._source_label)

        self._separator = QFrame()
        self._separator.setObjectName("separator")
        self._separator.setFrameShape(QFrame.Shape.HLine)
        self._separator.setFixedHeight(1)
        self._separator.hide()
        content_layout.addWidget(self._separator)

        self._translation_label = QLabel()
        self._translation_label.setObjectName("translation")
        self._translation_label.setWordWrap(True)
        self._translation_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._translation_label.setCursor(Qt.CursorShape.ArrowCursor)
        content_layout.addWidget(self._translation_label)
        content_layout.addStretch(1)

        self._scroll.setWidget(scroll_content)
        root.addWidget(self._scroll, stretch=1)

        self.setMinimumSize(_MIN_WIDTH, _MIN_HEIGHT)
        # No fixed max — clamped at runtime against available screen geometry.

    # ── Public state API ────────────────────────────────────────────────────

    def show_for_region(self, region: QRect) -> None:
        self._source_label.hide()
        self._separator.hide()
        self._translation_label.setText("…")
        self._translation_label.setTextFormat(Qt.TextFormat.PlainText)
        self._copy_button.hide()
        self._status_label.setText("Đang xử lý ảnh…")
        self._last_translation = ""
        self._last_region = region

        self._position_near(region)

        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self._install_event_filter()

    def update_status(self, status: str) -> None:
        self._status_label.setText(status)

    def update_source(self, source_text: str) -> None:
        self._source_label.setText(_truncate(source_text))
        self._source_label.show()
        self._separator.show()
        self._translation_label.setText("…")
        self._status_label.setText("Đang dịch…")

    def update_translation(self, result: TranslationResult) -> None:
        if result.source_text:
            self._source_label.setText(_truncate(result.source_text))
            self._source_label.show()
            self._separator.show()
        else:
            self._source_label.hide()
            self._separator.hide()

        self._translation_label.setText(result.translated_text)
        self._translation_label.setTextFormat(Qt.TextFormat.PlainText)
        self._last_translation = result.translated_text
        cache_tag = " · cached" if result.cached else ""
        self._status_label.setText(f"[{result.provider}{cache_tag}]")
        self._copy_button.show()

    def show_error(self, message: str) -> None:
        self._source_label.hide()
        self._separator.hide()
        self._translation_label.setTextFormat(Qt.TextFormat.RichText)
        self._translation_label.setText(
            f"<span style='color: #ff7676;'>Lỗi: {message}</span>"
        )
        self._status_label.setText("")
        self._copy_button.hide()

    def hide_popup(self) -> None:
        self._remove_event_filter()
        self.hide()
        self.closed.emit()

    # ── Internals ───────────────────────────────────────────────────────────

    def _on_copy(self) -> None:
        if not self._last_translation:
            return
        QGuiApplication.clipboard().setText(self._last_translation)
        self._status_label.setText("Đã copy ✓")

    def _position_near(self, region: QRect) -> None:
        # `region` is already in Qt logical coords — RegionSelector builds it via
        # mapToGlobal() (see capture/region_selector.py), and screen.availableGeometry()
        # is also logical. Do NOT divide by devicePixelRatio here: a previous
        # version did and the popup ended up overlaying the captured area on
        # 1.5x DPI displays, leaking popup pixels (e.g. "Đang nhận diện…" status
        # text) into the OCR input.
        screen = QGuiApplication.screenAt(region.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        # Keep user's size if they resized the popup; otherwise open at the defaults.
        cur_w = self.width()
        cur_h = self.height()
        w = cur_w if cur_w >= _MIN_WIDTH else _DEFAULT_WIDTH
        h = cur_h if cur_h >= _MIN_HEIGHT else _DEFAULT_HEIGHT
        w = min(w, available.width() - 2 * _MARGIN_FROM_EDGE)
        h = min(h, available.height() - 2 * _MARGIN_FROM_EDGE)

        log.debug("_position_near: region=%s available=%s popup=%dx%d", region, available, w, h)

        x = region.left()
        y = region.bottom() + _GAP_FROM_REGION

        if y + h > available.bottom() - _MARGIN_FROM_EDGE:
            flipped_y = region.top() - h - _GAP_FROM_REGION
            if flipped_y >= available.top() + _MARGIN_FROM_EDGE:
                y = flipped_y
            else:
                y = max(available.top() + _MARGIN_FROM_EDGE,
                        available.bottom() - h - _MARGIN_FROM_EDGE)

        if x + w > available.right() - _MARGIN_FROM_EDGE:
            x = available.right() - w - _MARGIN_FROM_EDGE
        if x < available.left() + _MARGIN_FROM_EDGE:
            x = available.left() + _MARGIN_FROM_EDGE

        self.setGeometry(x, y, w, h)

    def _install_event_filter(self) -> None:
        if self._filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._filter_installed = True

    def _remove_event_filter(self) -> None:
        if not self._filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._filter_installed = False

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            # Skip presses dispatched to the popup itself or any of its children.
            # Walking the widget tree is more reliable than comparing the global
            # mouse position against `self.geometry()` — coordinate comparisons
            # can disagree during resize/move because the widget's screen rect
            # updates asynchronously from the event being dispatched, leading to
            # false "outside" detections that auto-close the popup.
            w = watched if isinstance(watched, QWidget) else None
            while w is not None:
                if w is self:
                    return super().eventFilter(watched, event)
                w = w.parentWidget()
            try:
                global_pos = event.globalPosition().toPoint()
            except AttributeError:
                return super().eventFilter(watched, event)
            if not self.geometry().contains(global_pos):
                self.hide_popup()
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the rounded translucent background + border manually.

        Required because `WA_TranslucentBackground` disables Qt's default
        QSS background painting on top-level widgets — without this, the
        popup would be fully see-through.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Inset by half a pixel so the 1px border doesn't get clipped.
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QBrush(_BG_COLOR))
        painter.setPen(QPen(_BORDER_COLOR, 1))
        painter.drawRoundedRect(rect, _BORDER_RADIUS, _BORDER_RADIUS)

    def _edges_at(self, pos: QPoint) -> int:
        """Return resize bitmask for a position in widget-local coords."""
        m = _RESIZE_MARGIN
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        edges = 0
        if x <= m:
            edges |= 1  # left
        elif x >= w - m:
            edges |= 2  # right
        if y <= m:
            edges |= 4  # top
        elif y >= h - m:
            edges |= 8  # bottom
        return edges

    @staticmethod
    def _cursor_for_edges(edges: int) -> Qt.CursorShape:
        if edges in (1 | 4, 2 | 8):  # left+top or right+bottom
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (2 | 4, 1 | 8):  # right+top or left+bottom
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (1 | 2):
            return Qt.CursorShape.SizeHorCursor
        if edges & (4 | 8):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.SizeAllCursor

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Only the popup border starts a resize. Dragging the window is the
        # _DragBar's job (top toolbar) so clicks on the body never accidentally
        # move the popup.
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self._resize_edges = edges
                self._resize_start_geom = self.geometry()
                self._resize_start_global = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # Resize in progress.
        if self._resize_edges and self._resize_start_geom and self._resize_start_global:
            delta = event.globalPosition().toPoint() - self._resize_start_global
            g = QRect(self._resize_start_geom)
            min_w, min_h = _MIN_WIDTH, _MIN_HEIGHT
            # Clamp the popup against the screen it sits on so it can't grow off-screen.
            screen = QGuiApplication.screenAt(self.frameGeometry().center()) \
                or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None

            if self._resize_edges & 1:  # left
                new_left = g.left() + delta.x()
                if g.right() - new_left + 1 < min_w:
                    new_left = g.right() - min_w + 1
                if avail and new_left < avail.left():
                    new_left = avail.left()
                g.setLeft(new_left)
            if self._resize_edges & 2:  # right
                new_right = g.right() + delta.x()
                if new_right - g.left() + 1 < min_w:
                    new_right = g.left() + min_w - 1
                if avail and new_right > avail.right():
                    new_right = avail.right()
                g.setRight(new_right)
            if self._resize_edges & 4:  # top
                new_top = g.top() + delta.y()
                if g.bottom() - new_top + 1 < min_h:
                    new_top = g.bottom() - min_h + 1
                if avail and new_top < avail.top():
                    new_top = avail.top()
                g.setTop(new_top)
            if self._resize_edges & 8:  # bottom
                new_bottom = g.bottom() + delta.y()
                if new_bottom - g.top() + 1 < min_h:
                    new_bottom = g.top() + min_h - 1
                if avail and new_bottom > avail.bottom():
                    new_bottom = avail.bottom()
                g.setBottom(new_bottom)
            self.setGeometry(g)
            # Force a full repaint — translucent frameless windows occasionally
            # keep stale pixels from the previous frame during fast resizes.
            self.repaint()
            super().mouseMoveEvent(event)
            return

        # Hover — switch cursor to a resize handle when near an edge, otherwise
        # restore the default arrow (no more "move from anywhere" cursor).
        edges = self._edges_at(event.position().toPoint())
        if edges:
            self.setCursor(self._cursor_for_edges(edges))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._resize_edges = 0
        self._resize_start_geom = None
        self._resize_start_global = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_popup()
            return
        super().keyPressEvent(event)


def _truncate(text: str, limit: int = 800) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
