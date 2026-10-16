"""Private chrome widgets of the popup: drag bar, glyph, header, skeleton, error panel."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transsnip.ui import icons
from transsnip.ui.atoms import (
    IconButton,
    PillBadge,
    Spinner,
)
from transsnip.ui.theme import get_theme


# ── DragBar ────────────────────────────────────────────────────────────────
class _DragBar(QWidget):
    """The middle of the header — empty drag handle for moving the popup.

    Text body stays drag-free so selection works naturally; only this strip
    moves the window. Mirrors the design's `popup-drag` element.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMinimumHeight(28)
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


# ── AppGlyph (header brand mark) ──────────────────────────────────────────
class _AppGlyph(QWidget):
    """The small TransSnip glyph painted into the popup header.

    Two paths: outer crop brackets in accent, inner chevron in text_1.
    Paints with current theme palette colors via QPainter so theme switches
    recolor without re-importing assets.
    """

    def __init__(self, size: int = 14, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event: QPaintEvent) -> None:
        # Prefer the real app logo (assets/TransSnip.ico); fall back to the
        # procedural monogram if it's missing.
        from transsnip.ui.branding import app_pixmap
        pm = app_pixmap(self._size)
        if not pm.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(0, 0, self._size, self._size, pm)
            painter.end()
            return

        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Scale 16×16 design viewBox to the requested widget size.
        scale = self._size / 16
        painter.scale(scale, scale)

        # Outer crop brackets (accent).
        pen = QPen(QColor(p.accent), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for path_d in [
            ((2.5, 4.5), (2.5, 3), (3.2, 2.3), (4.5, 2.3)),  # top-left bracket
            ((11.5, 2.3), (13, 2.3), (13.7, 3), (13.7, 4.5)),
            ((13.7, 11.5), (13.7, 13), (13, 13.7), (11.5, 13.7)),
            ((4.5, 13.7), (3, 13.7), (2.3, 13), (2.3, 11.5)),
        ]:
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(*path_d[0])
            for pt in path_d[1:]:
                path.lineTo(*pt)
            painter.drawPath(path)

        # Inner chevron (text_1).
        pen2 = QPen(QColor(p.text_1), 1.6)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen2)
        from PySide6.QtGui import QPainterPath
        bar = QPainterPath()
        bar.moveTo(6, 8)
        bar.lineTo(10, 8)
        painter.drawPath(bar)
        chev = QPainterPath()
        chev.moveTo(8.5, 6.5)
        chev.lineTo(10, 8)
        chev.lineTo(8.5, 9.5)
        painter.drawPath(chev)
        painter.end()


# ── PopupHeader (one chrome strip for all states) ─────────────────────────
class _PopupHeader(QWidget):
    """Header bar: brand + drag + status + actions.

    `status` is a state string ("ocr", "translating", "done", "error") —
    the header swaps its center widget accordingly. Actions emit signals
    that the parent popup connects to its own slots.
    """

    speak_requested = Signal()
    copy_requested = Signal()
    pin_toggled = Signal(bool)
    settings_requested = Signal()
    close_requested = Signal()
    font_dec_requested = Signal()
    font_inc_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status: str = "ocr"
        self._show_voice = False
        self._pinned = False
        self._provider = ""
        self._cached = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 8, 10)
        layout.setSpacing(8)

        # Brand
        brand = QWidget()
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(6)
        self._glyph = _AppGlyph(14)
        brand_row.addWidget(self._glyph)
        self._brand_label = QLabel("TransSnip")
        brand_row.addWidget(self._brand_label)
        layout.addWidget(brand)

        # Drag (stretch)
        self._drag = _DragBar(self)
        layout.addWidget(self._drag, stretch=1)

        # Status area — replaced when status changes.
        self._status_wrap = QWidget()
        self._status_layout = QHBoxLayout(self._status_wrap)
        self._status_layout.setContentsMargins(0, 0, 0, 0)
        self._status_layout.setSpacing(6)
        layout.addWidget(self._status_wrap)

        # Actions
        actions = QWidget()
        actions_row = QHBoxLayout(actions)
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(2)

        # Font size − / + (user-controlled; dragging the popup wider reflows
        # text, it no longer zooms — see _apply_fonts / resizeEvent). Painted as
        # SVG icons (not Unicode text) so they render with consistent contrast
        # in both themes — see icons.py header note on why we avoid glyphs.
        self._font_dec_btn = IconButton("font-smaller", icon_size=15, tooltip="Cỡ chữ nhỏ hơn")
        self._font_dec_btn.clicked.connect(self.font_dec_requested.emit)
        actions_row.addWidget(self._font_dec_btn)
        self._font_inc_btn = IconButton("font-larger", icon_size=15, tooltip="Cỡ chữ lớn hơn")
        self._font_inc_btn.clicked.connect(self.font_inc_requested.emit)
        actions_row.addWidget(self._font_inc_btn)

        self._voice_btn = IconButton("volume", kind="accent", tooltip="Phát âm nguồn")
        self._voice_btn.clicked.connect(self.speak_requested.emit)
        self._voice_btn.hide()
        actions_row.addWidget(self._voice_btn)

        self._copy_btn = IconButton("copy", tooltip="Copy translation")
        self._copy_btn.clicked.connect(self.copy_requested.emit)
        actions_row.addWidget(self._copy_btn)

        self._pin_btn = IconButton("pin", tooltip="Pin (always on top)")
        self._pin_btn.clicked.connect(self._on_pin_clicked)
        actions_row.addWidget(self._pin_btn)

        self._settings_btn = IconButton("settings", tooltip="Settings")
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        actions_row.addWidget(self._settings_btn)

        # Subtle divider before close.
        self._divider = QFrame()
        self._divider.setFixedSize(1, 16)
        self._divider.setStyleSheet("background: rgba(255,255,255,0.10);")
        actions_row.addWidget(self._divider)

        self._close_btn = IconButton("close", kind="close", tooltip="Close (Esc)")
        self._close_btn.clicked.connect(self.close_requested.emit)
        actions_row.addWidget(self._close_btn)
        layout.addWidget(actions)

        self._apply_style()
        self.set_status("ocr")
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    # ── Public API ────────────────────────────────────────────────────────
    def set_status(self, status: str, *, provider: str = "", cached: bool = False) -> None:
        self._status = status
        self._provider = provider
        self._cached = cached
        self._rebuild_status()

    def set_voice_available(self, available: bool) -> None:
        self._show_voice = available
        self._voice_btn.setVisible(available)

    def is_pinned(self) -> bool:
        return self._pinned

    def reset_pin(self) -> None:
        """Unpin on a fresh translation cycle (called by the popup)."""
        if self._pinned:
            self._pinned = False
            self._refresh_pin_style()

    # ── Internals ─────────────────────────────────────────────────────────
    def _on_pin_clicked(self) -> None:
        self._pinned = not self._pinned
        self._refresh_pin_style()
        self.pin_toggled.emit(self._pinned)

    def _refresh_pin_style(self) -> None:
        # Tint the pin button accent while pinned so the state is visible.
        self._pin_btn.set_kind("accent" if self._pinned else "default")

    def _rebuild_status(self) -> None:
        # Clear existing widgets in status_layout.
        while self._status_layout.count():
            item = self._status_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        p = get_theme().palette
        if self._status in ("ocr", "translating"):
            spin = Spinner(11)
            spin.start()
            self._status_layout.addWidget(spin)
            label = QLabel("Đang OCR…" if self._status == "ocr" else "Đang dịch…")
            label.setStyleSheet(f"color: {p.text_2}; font-size: 11px;")
            self._status_layout.addWidget(label)
        elif self._status == "done":
            if self._provider:
                prov = QLabel(self._provider)
                prov.setStyleSheet(
                    f"color: {p.text_2}; font-family: {p.font_mono}; "
                    f"font-size: 10.5px; padding: 1px 6px; "
                    f"background: {p.bg_2}; border-radius: 4px;"
                )
                self._status_layout.addWidget(prov)
            if self._cached:
                badge = PillBadge("cached", icon_name="cached", tone="muted")
                self._status_layout.addWidget(badge)
        elif self._status == "error":
            badge = PillBadge("error", icon_name="alert", tone="warn")
            self._status_layout.addWidget(badge)

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._brand_label.setStyleSheet(
            f"color: {p.text_1}; font-size: 12px; font-weight: 600; "
            f"letter-spacing: {p.letter_tight};"
        )
        self._divider.setStyleSheet(f"background: {p.border_1};")
        self._rebuild_status()



# ── Skeleton placeholder (loading state) ──────────────────────────────────
class _Skeleton(QWidget):
    """Animated horizontal bars for loading state.

    Matches design `.popup-skeleton-line` (4 lines, 2 default + 2 accent).
    Uses paintEvent with a shimmer effect — repaints every 50ms while visible.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 18, 8, 18)
        layout.setSpacing(10)
        # Width ratios from the design: 85% / 60% / 75% / 50%.
        self._bars = [
            (0.85, False),
            (0.60, False),
            (0.75, True),
            (0.50, True),
        ]
        for _w, _a in self._bars:
            placeholder = QFrame()
            placeholder.setFixedHeight(12)
            layout.addWidget(placeholder)
        self._frames = [layout.itemAt(i).widget() for i in range(layout.count())]
        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def _apply_style(self) -> None:
        p = get_theme().palette
        for frame, (width_ratio, is_accent) in zip(self._frames, self._bars, strict=True):
            color = p.accent_soft if is_accent else p.bg_2
            frame.setStyleSheet(
                f"background: {color}; border-radius: 6px;"
            )
            frame.setMaximumWidth(int(440 * width_ratio))


# ── ErrorPanel (error state body) ─────────────────────────────────────────
class _ErrorPanel(QWidget):
    """Inline error display: alert icon + title + msg + action buttons.

    `retry_requested` / `switch_provider_requested` fire when the user
    clicks the corresponding ghost button; popup wires them up.
    """

    retry_requested = Signal()
    switch_provider_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Icon column
        self._icon = QLabel()
        self._icon.setFixedSize(36, 36)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignTop)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        self._title = QLabel("Không thể dịch")
        self._msg = QLabel()
        self._msg.setWordWrap(True)
        text_col.addWidget(self._title)
        text_col.addWidget(self._msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._switch_btn = QPushButton("Đổi provider")
        self._switch_btn.setProperty("soft", True)
        self._switch_btn.clicked.connect(self.switch_provider_requested.emit)
        self._retry_btn = QPushButton("Thử lại")
        self._retry_btn.setProperty("soft", True)
        self._retry_btn.clicked.connect(self.retry_requested.emit)
        btn_row.addWidget(self._switch_btn)
        btn_row.addWidget(self._retry_btn)
        btn_row.addStretch(1)
        text_col.addLayout(btn_row)
        layout.addLayout(text_col, stretch=1)

        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def set_error(self, message: str) -> None:
        self._msg.setText(message)

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._icon.setPixmap(icons.get_pixmap("alert", color=p.danger, size=22))
        self._icon.setStyleSheet(
            f"background: {p.accent_soft}; border-radius: 18px;"
        )
        self._title.setStyleSheet(
            f"color: {p.text_1}; font-size: 13px; font-weight: 600;"
        )
        self._msg.setStyleSheet(
            f"color: {p.text_2}; font-size: 12px; line-height: 1.5;"
        )
