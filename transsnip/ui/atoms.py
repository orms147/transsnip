"""Reusable atom widgets — match the Cobalt design's React components.

Each widget here is the Qt twin of a `surface-*.jsx` component:
    LangChip     ↔ <LangChip code name>
    Toggle       ↔ <Toggle on>
    KbdSeq       ↔ <KbdSeq keys=[...]>
    PillBadge    ↔ <span className="popup-cache"> etc.
    SectionHead  ↔ <div className="settings-section-head">
    IconButton   ↔ <button className="popup-iconbtn">

They consume `theme.get_theme().palette` and re-render when
`mode_changed` fires. Building these once means surface modules
(`floating_popup`, `settings_window`) stay focused on layout — no
duplicate "draw a 4px-radius chip" code in every file.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from transsnip.ui import icons
from transsnip.ui.theme import get_theme


# ── IconButton ────────────────────────────────────────────────────────────
class IconButton(QPushButton):
    """Square icon-only button used everywhere (popup toolbar, settings titlebar,
    tray menu rows).

    Three variants via `kind`:
      "default" — text_2 → text_1 on hover, transparent bg with subtle hover tint
      "accent"  — accent color always (matches `popup-iconbtn--accent` in JSX)
      "close"   — danger red hover background (matches `--close`)
    """

    def __init__(
        self,
        icon_name: str,
        *,
        kind: str = "default",
        size: int = 28,
        icon_size: int = 14,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._kind = kind
        self._icon_size = icon_size
        self.setFixedSize(QSize(size, size))
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.setFlat(True)
        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def set_kind(self, kind: str) -> None:
        """Switch variant ('default'/'accent'/'close') and restyle — used to
        reflect toggle state (e.g. the pin button turns accent while pinned)."""
        if kind != self._kind:
            self._kind = kind
            self._apply_style()

    def _apply_style(self) -> None:
        p = get_theme().palette
        if self._kind == "accent":
            color = p.accent
        else:
            color = p.text_2
        self.setIcon(icons.get_icon(self._icon_name, color=color, size=self._icon_size))

        if self._kind == "close":
            hover_bg = p.danger
            hover_color = p.accent_on
        elif self._kind == "accent":
            hover_bg = p.accent_soft
            hover_color = p.accent_hover
        else:
            hover_bg = p.bg_3
            hover_color = p.text_1

        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
        """)
        # Hover-state icon swap is handled via enterEvent/leaveEvent below —
        # QSS can't recolor an SVG-baked QIcon on its own.
        self._hover_color = hover_color
        self._idle_color = color

    def enterEvent(self, event) -> None:
        self.setIcon(icons.get_icon(self._icon_name, color=self._hover_color, size=self._icon_size))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setIcon(icons.get_icon(self._icon_name, color=self._idle_color, size=self._icon_size))
        super().leaveEvent(event)


# ── LangChip ──────────────────────────────────────────────────────────────
class LangChip(QWidget):
    """`EN · English` style chip with mono code + UI-font name.

    Replaces the JSX `<div className="lang-chip">`. Used in popup section
    headers (above each source/translation block) and in the overlay toolbar.
    """

    def __init__(
        self,
        code: str,
        name: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._code = code
        self._name = name
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        self._code_label = QLabel(code)
        self._code_label.setProperty("mono", True)
        self._layout.addWidget(self._code_label)

        self._name_label: Optional[QLabel] = None
        if name:
            self._name_label = QLabel(name)
            self._layout.addWidget(self._name_label)

        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def set_lang(self, code: str, name: Optional[str] = None) -> None:
        """Update the chip's code/name in place — used when popup source
        language changes mid-session (vision provider returns a different
        source). Avoids reparenting QWidget which fights with parent layouts.

        Lazily creates the name label on first non-empty name so chips that
        started "code-only" can grow a name later without being rebuilt.
        """
        self._code = code
        self._code_label.setText(code)
        if name:
            if self._name_label is None:
                self._name_label = QLabel(name)
                self._layout.addWidget(self._name_label)
                self._apply_style()
            else:
                self._name_label.setText(name)
                self._name_label.show()
        elif self._name_label is not None:
            self._name_label.hide()
        self._name = name

    def _apply_style(self) -> None:
        p = get_theme().palette
        # Outer pill background + chip styling. The two inner labels get
        # their own color rules so the mono code (text_2) and the name
        # (text_1) read at different weights even in a single chip.
        self.setStyleSheet(f"""
            LangChip {{
                background: {p.bg_2};
                border: 1px solid {p.border_1};
                border-radius: {p.r_pill}px;
                padding: 0;
            }}
        """)
        self._code_label.setStyleSheet(
            f"color: {p.text_2}; font-family: {p.font_mono}; "
            f"font-size: 10px; font-weight: 600; letter-spacing: {p.letter_caps}; "
            f"padding: 2px 4px 2px 8px;"
        )
        if self._name_label:
            self._name_label.setStyleSheet(
                f"color: {p.text_1}; font-size: 11px; font-weight: 500; "
                f"padding: 2px 8px 2px 0;"
            )


# ── Toggle (custom switch) ────────────────────────────────────────────────
class Toggle(QWidget):
    """Slide-style on/off switch. Qt's QCheckBox is square + boring;
    the design wants a pill track with a sliding knob.

    Emits `toggled(bool)` when state changes; reads `isChecked()` / sets
    `setChecked(...)` for API symmetry with QCheckBox so settings code
    can swap between them.
    """

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(36, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        if value == self._checked:
            return
        self._checked = value
        self.update()
        self.toggled.emit(value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Track — accent when on, border_2 box when off.
        track_color = QColor(p.accent if self._checked else p.bg_3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(0, 2, 36, 16, 8, 8)

        # Knob — slides between left (off) and right (on) edges.
        knob_color = QColor(p.accent_on if self._checked else p.text_2)
        painter.setBrush(knob_color)
        x = 19 if self._checked else 3
        painter.drawEllipse(x, 4, 12, 12)
        painter.end()


class ToggleRow(QWidget):
    """`toggle-row` from the design — title (+ optional desc) on the left,
    Toggle widget on the right. Used heavily in Settings.
    """

    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        description: str = "",
        *,
        checked: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("font-size: 12.5px; font-weight: 500;")
        text_col.addWidget(self._title_label)
        self._desc_label: Optional[QLabel] = None
        if description:
            self._desc_label = QLabel(description)
            self._desc_label.setWordWrap(True)
            self._desc_label.setProperty("hint", True)
            text_col.addWidget(self._desc_label)
        layout.addLayout(text_col, stretch=1)

        self._toggle = Toggle(checked)
        self._toggle.toggled.connect(self.toggled.emit)
        layout.addWidget(self._toggle, alignment=Qt.AlignmentFlag.AlignTop)

        get_theme().mode_changed.connect(lambda _p: self._apply_style())
        self._apply_style()

    def isChecked(self) -> bool:
        return self._toggle.isChecked()

    def setChecked(self, value: bool) -> None:
        self._toggle.setChecked(value)

    def _apply_style(self) -> None:
        p = get_theme().palette
        # Skip local `color:` so theme switches recolor via the global
        # `QLabel { color: text_1 }` cascade — local color refused to
        # re-apply on unpolish/polish for the same reason as SectionHead.
        self._title_label.setStyleSheet("font-size: 12.5px; font-weight: 500;")
        if self._desc_label:
            self._desc_label.setStyleSheet(f"color: {p.text_3}; font-size: 11px;")


# ── KbdSeq ────────────────────────────────────────────────────────────────
class KbdSeq(QWidget):
    """Render a key combo like `Alt + T` with raised <kbd>-style boxes.

    Used in onboarding step 4, settings Hotkeys tab, popup footer hint,
    and tray menu kbd suffix. Read-only — for editing, the Hotkeys tab
    uses a real QKeySequenceEdit.
    """

    def __init__(self, keys: list[str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._keys = keys
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self._labels: list[QLabel] = []
        for i, key in enumerate(keys):
            if i > 0:
                plus = QLabel("+")
                plus.setProperty("muted", True)
                layout.addWidget(plus)
                self._labels.append(plus)
            kbd = QLabel(key)
            kbd.setProperty("kbd", True)
            kbd.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(kbd)
            self._labels.append(kbd)
        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def _apply_style(self) -> None:
        p = get_theme().palette
        for lbl in self._labels:
            if lbl.property("kbd"):
                lbl.setStyleSheet(
                    f"color: {p.text_2}; background: {p.bg_2}; "
                    f"border: 1px solid {p.border_2}; "
                    f"border-bottom-width: 2px; border-radius: 4px; "
                    f"padding: 1px 6px; min-width: 14px; "
                    f"font-family: {p.font_mono}; font-size: 10px; font-weight: 500;"
                )
            elif lbl.property("muted"):
                lbl.setStyleSheet(f"color: {p.text_3}; font-size: 10px; padding: 0 1px;")


# ── PillBadge ─────────────────────────────────────────────────────────────
class PillBadge(QWidget):
    """Pill-shaped badge — used for provider tag, cached marker, Phase-2
    "soon" pills, etc. Single icon + label.

    Variants via `tone`:
      "default" — text_2 on bg_2
      "success" — success color on success_soft
      "warn"    — warning color
      "muted"   — text_3 with extra dim
    """

    def __init__(
        self,
        label: str,
        *,
        icon_name: str = "",
        tone: str = "default",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._tone = tone
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 2, 8, 2)
        layout.setSpacing(4)
        self._icon_label: Optional[QLabel] = None
        if icon_name:
            self._icon_label = QLabel()
            self._icon_label.setPixmap(icons.get_pixmap(icon_name, size=10))
            self._icon_name = icon_name
            layout.addWidget(self._icon_label)
        else:
            self._icon_name = ""
        self._text_label = QLabel(label)
        layout.addWidget(self._text_label)
        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def _apply_style(self) -> None:
        p = get_theme().palette
        if self._tone == "success":
            fg, bg = p.success, p.bg_2
        elif self._tone == "warn":
            fg, bg = p.warning, p.bg_2
        elif self._tone == "muted":
            fg, bg = p.text_3, p.bg_2
        else:
            fg, bg = p.text_2, p.bg_2
        self.setStyleSheet(
            f"PillBadge {{ background: {bg}; border-radius: {p.r_pill}px; }}"
        )
        self._text_label.setStyleSheet(
            f"color: {fg}; font-size: 10px; font-family: {p.font_mono}; font-weight: 500;"
        )
        if self._icon_label:
            # Repaint icon with the current tone color.
            self._icon_label.setPixmap(icons.get_pixmap(self._icon_name, color=fg, size=10))


# ── SectionHead ───────────────────────────────────────────────────────────
class SectionHead(QWidget):
    """`settings-section-head` — title (h3-ish) + descriptive paragraph.

    Used as the header for each Section in Settings, Onboarding, About.
    """

    def __init__(
        self,
        title: str,
        description: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)
        self._title = QLabel(title)
        layout.addWidget(self._title)
        self._desc: Optional[QLabel] = None
        if description:
            self._desc = QLabel(description)
            self._desc.setWordWrap(True)
            layout.addWidget(self._desc)
        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def _apply_style(self) -> None:
        p = get_theme().palette
        # No explicit `color:` here — we let the global QSS rule
        # `QLabel { color: text_1 }` cascade. Setting it locally caused
        # the label to keep the original-palette color on theme switches
        # (Qt's CSS engine sometimes doesn't re-merge local + global on
        # unpolish/polish reliably). Only properties that need to differ
        # from defaults (font size/weight) stay here.
        self._title.setStyleSheet(
            "font-size: 14px; font-weight: 600;"
        )
        if self._desc:
            # Description is explicitly dimmer than the default text color
            # so it must override — kept inline.
            self._desc.setStyleSheet(f"color: {p.text_2}; font-size: 11.5px;")


# ── Spinner ───────────────────────────────────────────────────────────────
class Spinner(QLabel):
    """Animated rotating arc for loading states.

    Wraps `icons.get_spinner_pixmap` + a QPropertyAnimation on the QLabel's
    pixmap rotation. Use this in popup loading state and toolbar busy hints.
    """

    def __init__(self, size: int = 12, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(size, size))
        self._size = size
        self._angle = 0
        self._timer = None
        self._apply_color()
        get_theme().mode_changed.connect(lambda _p: self._apply_color())

    def _apply_color(self) -> None:
        p = get_theme().palette
        self._color = p.text_2
        self.setPixmap(icons.get_spinner_pixmap(self._color, self._size))

    def start(self) -> None:
        from PySide6.QtCore import QTimer
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
        self._timer.start(80)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        from PySide6.QtGui import QTransform
        pixmap = icons.get_spinner_pixmap(self._color, self._size)
        transformed = pixmap.transformed(QTransform().rotate(self._angle), Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(transformed)


# ── CustomTitlebar (frameless window chrome) ──────────────────────────────
class CustomTitlebar(QWidget):
    """Frameless window's draggable titlebar with minimize/maximize/close.

    Used by `SettingsWindow`, `OnboardingModal`, `AboutDialog` — any
    top-level window that wants Cobalt-themed chrome instead of the
    OS-painted titlebar. Mirrors the design's `settings-titlebar`.

    Emits intent signals; the parent window connects them to its own
    `showMinimized() / showMaximized() / close()`. This separation lets
    the same titlebar work for any QWidget host.
    """

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        title: str,
        *,
        icon_widget: Optional[QWidget] = None,
        show_minimize: bool = True,
        show_maximize: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._press_global: Optional[QPoint] = None
        self._press_frame_topleft: Optional[QPoint] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(8)

        # Left: optional icon widget (e.g. AppGlyph) + title
        if icon_widget is not None:
            layout.addWidget(icon_widget)
        self._title_label = QLabel(title)
        layout.addWidget(self._title_label)
        layout.addStretch(1)

        # Right: window controls
        if show_minimize:
            self._min_btn = IconButton("minus", size=28, icon_size=10, tooltip="Minimize")
            self._min_btn.clicked.connect(self.minimize_requested.emit)
            layout.addWidget(self._min_btn)
        if show_maximize:
            self._max_btn = IconButton("fullscreen", size=28, icon_size=10, tooltip="Maximize")
            self._max_btn.clicked.connect(self.maximize_requested.emit)
            layout.addWidget(self._max_btn)
        self._close_btn = IconButton("close", kind="close", size=28, icon_size=10, tooltip="Close")
        self._close_btn.clicked.connect(self.close_requested.emit)
        layout.addWidget(self._close_btn)

        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def _apply_style(self) -> None:
        p = get_theme().palette
        # Color cascades from global QLabel rule — local color stuck on
        # theme switch (same Qt CSS engine quirk as SectionHead).
        self._title_label.setStyleSheet("font-size: 11.5px; font-weight: 600;")
        self.setStyleSheet(
            f"CustomTitlebar {{ background: {p.bg_1}; "
            f"border-bottom: 1px solid {p.border_1}; }}"
        )

    # Drag the parent window when LMB pressed on the title bar (not on buttons,
    # which consume the event before it reaches us).
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

    # Double-click toggles maximize like Windows native chrome.
    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
        super().mouseDoubleClickEvent(event)


# ── Slider (custom rail + knob with readout) ──────────────────────────────
class Slider(QWidget):
    """A QSlider-like atom matching the design's `.slider` component.

    Why not just style QSlider:
    - QSlider's groove/handle subcontrols are not flexible enough to match
      the design's rail + knob + readout + bound chips layout.
    - Building our own keeps mouse handling consistent and means theme
      switches recolor without QSS tricks for sub-controls.
    """

    value_changed = Signal(float)

    def __init__(
        self,
        *,
        minimum: float = 0.0,
        maximum: float = 1.0,
        value: float = 0.0,
        min_label: str = "",
        max_label: str = "",
        format_readout=lambda v: f"{v:.2f}",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(48)
        self._min = minimum
        self._max = maximum
        self._value = max(minimum, min(value, maximum))
        self._min_label = min_label
        self._max_label = max_label
        self._format = format_readout
        self._dragging = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def value(self) -> float:
        return self._value

    def setValue(self, value: float) -> None:
        clamped = max(self._min, min(value, self._max))
        if clamped == self._value:
            return
        self._value = clamped
        self.update()
        self.value_changed.emit(clamped)

    def _pct(self) -> float:
        rng = self._max - self._min
        return (self._value - self._min) / rng if rng > 0 else 0.0

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._set_from_x(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._set_from_x(event.position().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _set_from_x(self, x: float) -> None:
        rail_w = max(1, self.width() - 24)
        x = max(12, min(x, 12 + rail_w))
        pct = (x - 12) / rail_w
        self.setValue(self._min + pct * (self._max - self._min))

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rail (background + fill)
        rail_top = 14
        rail_left = 12
        rail_right = self.width() - 12
        rail_h = 4
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.bg_3))
        painter.drawRoundedRect(rail_left, rail_top, rail_right - rail_left, rail_h, 2, 2)

        pct = self._pct()
        fill_w = int((rail_right - rail_left) * pct)
        painter.setBrush(QColor(p.accent))
        painter.drawRoundedRect(rail_left, rail_top, fill_w, rail_h, 2, 2)

        # Knob
        knob_x = rail_left + fill_w
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.accent_on))
        painter.drawEllipse(knob_x - 7, rail_top + rail_h // 2 - 7, 14, 14)
        painter.setBrush(QColor(p.accent))
        painter.drawEllipse(knob_x - 4, rail_top + rail_h // 2 - 4, 8, 8)

        # Meta row: min label, readout, max label
        meta_y = rail_top + rail_h + 14
        font_mono = QFont(p.font_mono.split(",")[0].strip("'"))
        font_mono.setPointSize(8)
        painter.setFont(font_mono)
        painter.setPen(QColor(p.text_3))
        if self._min_label:
            painter.drawText(rail_left, meta_y, self._min_label)
        if self._max_label:
            from PySide6.QtGui import QFontMetrics
            metrics = QFontMetrics(font_mono)
            mw = metrics.horizontalAdvance(self._max_label)
            painter.drawText(rail_right - mw, meta_y, self._max_label)

        readout = self._format(self._value)
        painter.setPen(QColor(p.text_1))
        from PySide6.QtGui import QFontMetrics
        metrics = QFontMetrics(font_mono)
        rw = metrics.horizontalAdvance(readout)
        painter.drawText((self.width() - rw) // 2, meta_y, readout)


# ── Segmented control ─────────────────────────────────────────────────────
class Segmented(QWidget):
    """Pill of mutually-exclusive options. Used in Display tab for overlay
    style (subtle / opaque / side-panel).

    Each option is (id, icon, label, sub_label). Emits `value_changed(id)`.
    """

    value_changed = Signal(str)

    def __init__(
        self,
        options: list[tuple[str, str, str, str]],
        *,
        value: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._options = options
        self._value = value or (options[0][0] if options else "")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._buttons: dict[str, QPushButton] = {}
        for opt_id, icon_name, label, sub in options:
            btn = QPushButton()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(46)
            inner = QVBoxLayout(btn)
            inner.setContentsMargins(8, 4, 8, 4)
            inner.setSpacing(2)
            head_row = QHBoxLayout()
            head_row.setSpacing(4)
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icons.get_pixmap(icon_name, size=14))
            head_row.addWidget(icon_lbl)
            lbl = QLabel(label)
            lbl.setStyleSheet("font-size: 11px; font-weight: 600;")
            head_row.addWidget(lbl)
            head_row.addStretch(1)
            sub_lbl = QLabel(sub)
            sub_lbl.setProperty("hint", True)
            sub_lbl.setStyleSheet("font-size: 10px;")
            inner.addLayout(head_row)
            inner.addWidget(sub_lbl)
            btn.clicked.connect(lambda _checked=False, oid=opt_id: self._on_pick(oid))
            self._buttons[opt_id] = btn
            layout.addWidget(btn)
        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def value(self) -> str:
        return self._value

    def setValue(self, value: str) -> None:
        if value not in self._buttons or value == self._value:
            return
        self._value = value
        self._apply_style()
        self.value_changed.emit(value)

    def _on_pick(self, opt_id: str) -> None:
        self.setValue(opt_id)

    def _apply_style(self) -> None:
        p = get_theme().palette
        self.setStyleSheet(
            f"Segmented {{ background: {p.bg_2}; border-radius: 8px; }}"
        )
        for opt_id, btn in self._buttons.items():
            if opt_id == self._value:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {p.bg_1}; "
                    f"border: 1px solid {p.border_2}; border-radius: 6px; "
                    f"color: {p.text_1}; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; border: none; "
                    f"color: {p.text_3}; }}"
                    f"QPushButton:hover {{ color: {p.text_1}; }}"
                )


# ── ThemeCard (theme picker swatch) ───────────────────────────────────────
class ThemeCard(QWidget):
    """Radio-style card showing a mini popup-chrome swatch + name. Used by
    Display tab to pick Dark / Light / Auto.
    """

    selected = Signal(str)

    def __init__(self, mode: str, name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._active = False
        self.setFixedSize(140, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name = name
        get_theme().mode_changed.connect(lambda _p: self.update())

    def setActive(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self._mode)
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Card frame
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(p.bg_1))
        border_color = p.accent if self._active else p.border_1
        painter.setPen(QColor(border_color))
        painter.drawRoundedRect(rect, 10, 10)

        # Swatch — preview of the theme's popup chrome
        swatch_rect = rect.adjusted(10, 10, -10, -40)
        if self._mode == "dark":
            sw_bg = QColor("#131519")
            sw_text = QColor("#ecedef")
        elif self._mode == "light":
            sw_bg = QColor("#ffffff")
            sw_text = QColor("#0f1320")
        else:  # auto
            sw_bg = QColor(p.bg_2)
            sw_text = QColor(p.text_1)

        painter.setBrush(sw_bg)
        painter.setPen(QColor(p.border_2))
        painter.drawRoundedRect(swatch_rect, 6, 6)
        # Faux toolbar dot
        painter.setBrush(QColor(p.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(swatch_rect.left() + 8, swatch_rect.top() + 8, 6, 6)
        # Faux text line
        painter.setBrush(sw_text)
        painter.drawRoundedRect(swatch_rect.left() + 20, swatch_rect.top() + 10, swatch_rect.width() - 30, 2, 1, 1)
        painter.drawRoundedRect(swatch_rect.left() + 8, swatch_rect.top() + 28, swatch_rect.width() - 16, 2, 1, 1)

        # Name row
        name_y = swatch_rect.bottom() + 6
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(p.text_1))
        painter.drawText(
            rect.left(), name_y, rect.width(), 22,
            Qt.AlignmentFlag.AlignCenter,
            self._name,
        )

        # Active checkmark
        if self._active:
            chk_x = rect.right() - 22
            chk_y = rect.top() + 8
            painter.setBrush(QColor(p.accent))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(chk_x, chk_y, 14, 14)
            check_pix = icons.get_pixmap("check", color=p.accent_on, size=10)
            painter.drawPixmap(chk_x + 2, chk_y + 2, check_pix)


# ── ProviderRadioCard (onboarding step 2) ─────────────────────────────────
class ProviderRadioCard(QWidget):
    """Radio card row for picking a provider in onboarding.

    Layout: radio dot · icon · {name + desc} · tag pill (right).
    """

    selected = Signal(str)

    def __init__(
        self,
        provider_id: str,
        *,
        icon_name: str,
        name: str,
        desc: str,
        tag: str = "",
        free: bool = False,
        active: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._id = provider_id
        self._active = active
        self._free = free
        self._tag = tag
        self.setMinimumHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self._dot = QWidget()
        self._dot.setFixedSize(16, 16)
        layout.addWidget(self._dot)

        self._icon_label = QLabel()
        self._icon_name = icon_name
        layout.addWidget(self._icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._name_label = QLabel(name)
        self._desc_label = QLabel(desc)
        text_col.addWidget(self._name_label)
        text_col.addWidget(self._desc_label)
        layout.addLayout(text_col, stretch=1)

        self._tag_label = QLabel(tag)
        self._tag_label.setVisible(bool(tag))
        layout.addWidget(self._tag_label)

        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def setActive(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self._id)
        super().mousePressEvent(event)

    def _apply_style(self) -> None:
        p = get_theme().palette
        border_color = p.accent if self._active else p.border_1
        bg = p.accent_soft if self._active else p.bg_1
        self.setStyleSheet(
            f"ProviderRadioCard {{ background: {bg}; "
            f"border: 1px solid {border_color}; border-radius: 10px; }}"
        )
        self._dot.setStyleSheet(
            f"background: {p.accent if self._active else 'transparent'}; "
            f"border: 1.5px solid {p.accent if self._active else p.border_strong}; "
            f"border-radius: 8px;"
        )
        self._icon_label.setPixmap(icons.get_pixmap(self._icon_name, color=p.text_2, size=16))
        self._name_label.setStyleSheet(f"color: {p.text_1}; font-size: 12px; font-weight: 600;")
        self._desc_label.setStyleSheet(f"color: {p.text_3}; font-size: 11px;")
        tag_color = p.success if self._free else p.text_2
        self._tag_label.setStyleSheet(
            f"color: {tag_color}; font-size: 10px; font-weight: 500; "
            f"background: {p.bg_2}; padding: 3px 8px; border-radius: 999px;"
        )
