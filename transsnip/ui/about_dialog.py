"""AboutDialog — frameless modal shown from tray menu / Settings footer link.

3 internal tabs (Info / Acknowledgements / Author) sharing one chrome.
Hosts the app icon at large size, version, license, dependency list, and
GitHub/email contact. All content static (no live data) so the dialog is
a single QWidget without any IO.

Mirrors `surface-about.jsx` closely; only the chrome titlebar differs
(uses our CustomTitlebar atom for consistent drag behavior).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from transsnip.ui import icons
from transsnip.ui.atoms import CustomTitlebar, IconButton
from transsnip.ui.theme import get_theme


_VERSION = "v0.2.0-mvp"
_BUILD = "cobalt-dark · 2026"
_REPO_URL = "github.com/orms147/transsnip"

_DEPS = [
    ("RapidOCR", "ONNX OCR fallback"),
    ("winsdk", "Windows OCR binding"),
    ("eng-to-ipa", "CMU phonetic dictionary"),
    ("edge-tts", "Microsoft Edge TTS streaming"),
    ("PySide6", "Qt for Python"),
    ("mss", "fast multi-monitor capture"),
    ("wordninja", "English word segmentation"),
]


class _AppIconLarge(QWidget):
    """The 144-viewBox app icon — crop brackets + chevron mark.

    Drawn with direct QPainter calls (no SVG path parsing) so the size is
    a clean parameter and the colors follow the theme palette. The four
    crop brackets are each a single rounded "L" shape; the chevron is a
    horizontal bar + a small `>` to its right.
    """

    def __init__(self, size: int = 84, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = self._size / 144
        painter.scale(scale, scale)

        # Rounded background tile (gradient: bg_2 → bg_1)
        from PySide6.QtGui import QLinearGradient, QPainterPath
        bg_grad = QLinearGradient(0, 0, 144, 144)
        bg_grad.setColorAt(0.0, QColor(p.bg_2))
        bg_grad.setColorAt(1.0, QColor(p.bg_1))
        painter.setBrush(QBrush(bg_grad))
        painter.setPen(QPen(QColor(p.border_2), 1))
        painter.drawRoundedRect(2, 2, 140, 140, 32, 32)

        # Crop brackets — 4 corners, each one short horizontal + short vertical
        # leg meeting at the corner of an inset 30..114 box.
        pen = QPen(QColor(p.accent), 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        LEG = 20
        for corner_x, corner_y, dx, dy in [
            (30, 30, 1, 1),    # TL
            (114, 30, -1, 1),  # TR
            (114, 114, -1, -1),  # BR
            (30, 114, 1, -1),  # BL
        ]:
            p1 = (corner_x + dx * LEG, corner_y)
            p2 = (corner_x, corner_y)
            p3 = (corner_x, corner_y + dy * LEG)
            path = QPainterPath()
            path.moveTo(*p1)
            path.lineTo(*p2)
            path.lineTo(*p3)
            painter.drawPath(path)

        # Inner chevron: horizontal bar + ">" arrow
        pen2 = QPen(QColor(p.text_1), 7)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen2)
        bar = QPainterPath()
        bar.moveTo(58, 72)
        bar.lineTo(86, 72)
        painter.drawPath(bar)
        chev = QPainterPath()
        chev.moveTo(78, 60)
        chev.lineTo(88, 72)
        chev.lineTo(78, 84)
        painter.drawPath(chev)


class AboutDialog(QWidget):
    """Frameless 480×600 modal. Use `.exec()`-equivalent via .show() + signals."""

    onboarding_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(480, 600)
        self.setMinimumSize(420, 540)

        self._build_ui()
        get_theme().mode_changed.connect(lambda _p: self.update())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # Custom titlebar — no minimize/maximize, just close.
        self._titlebar = CustomTitlebar(
            "About TransSnip",
            show_minimize=False,
            show_maximize=False,
        )
        self._titlebar.close_requested.connect(self.close)
        root.addWidget(self._titlebar)

        # Head (icon + wordmark + tagline)
        head = QWidget()
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(24, 18, 24, 14)
        head_layout.setSpacing(8)
        icon_row = QHBoxLayout()
        icon_row.addStretch(1)
        icon_row.addWidget(_AppIconLarge(84))
        icon_row.addStretch(1)
        head_layout.addLayout(icon_row)

        wordmark_row = QHBoxLayout()
        wordmark_row.setSpacing(8)
        self._name_label = QLabel("TransSnip")
        self._version_label = QLabel(_VERSION)
        wordmark_row.addStretch(1)
        wordmark_row.addWidget(self._name_label)
        wordmark_row.addWidget(self._version_label)
        wordmark_row.addStretch(1)
        head_layout.addLayout(wordmark_row)

        self._tagline = QLabel("Screen translation cho Windows · Made with ♥ in Vietnam")
        self._tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head_layout.addWidget(self._tagline)
        root.addWidget(head)

        # Tab strip
        tab_strip = QWidget()
        tab_row = QHBoxLayout(tab_strip)
        tab_row.setContentsMargins(24, 0, 24, 0)
        tab_row.setSpacing(2)
        self._tab_buttons: list[QPushButton] = []
        self._tabs_meta = [
            ("info", "Thông tin"),
            ("ack", "Acknowledgements"),
            ("author", "Tác giả"),
        ]
        for tid, label in self._tabs_meta:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, t=tid: self._switch_tab(t))
            self._tab_buttons.append(btn)
            tab_row.addWidget(btn)
        tab_row.addStretch(1)
        root.addWidget(tab_strip)

        # Stack
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_info_pane())
        self._stack.addWidget(self._build_ack_pane())
        self._stack.addWidget(self._build_author_pane())
        root.addWidget(self._stack, stretch=1)

        # Footer
        footer = QWidget()
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(20, 10, 20, 14)
        onboarding_link = QLabel("Run onboarding again")
        onboarding_link.setProperty("hint", True)
        onboarding_link.setCursor(Qt.CursorShape.PointingHandCursor)
        onboarding_link.mousePressEvent = lambda _e: self.onboarding_requested.emit()  # type: ignore[assignment]
        footer_row.addWidget(onboarding_link)
        footer_row.addStretch(1)
        close_btn = QPushButton("Đóng")
        close_btn.setProperty("primary", True)
        close_btn.clicked.connect(self.close)
        footer_row.addWidget(close_btn)
        root.addWidget(footer)

        self._apply_style()
        self._switch_tab("info")

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._name_label.setStyleSheet(
            f"color: {p.text_1}; font-size: 20px; font-weight: 700;"
        )
        self._version_label.setStyleSheet(
            f"color: {p.text_3}; font-family: {p.font_mono}; "
            f"font-size: 11px; padding-top: 6px;"
        )
        self._tagline.setStyleSheet(f"color: {p.text_2}; font-size: 12px;")

    def _switch_tab(self, tab_id: str) -> None:
        p = get_theme().palette
        for i, (tid, _l) in enumerate(self._tabs_meta):
            active = tid == tab_id
            btn = self._tab_buttons[i]
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {p.bg_2}; color: {p.text_1}; "
                    f"border: 1px solid {p.border_2}; border-radius: 6px; "
                    f"padding: 6px 14px; font-size: 11.5px; font-weight: 600; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {p.text_2}; "
                    f"border: none; padding: 6px 14px; font-size: 11.5px; }}"
                    f"QPushButton:hover {{ color: {p.text_1}; }}"
                )
            if active:
                self._stack.setCurrentIndex(i)

    # ── Panes ─────────────────────────────────────────────────────────────

    def _build_info_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(8)
        rows = [
            ("License", "MIT", False),
            ("Build", _BUILD, False),
            ("Engine", "Qt 6.7 · Python 3.12", False),
            ("Repo", _REPO_URL, True),
        ]
        for key, val, is_link in rows:
            row = QHBoxLayout()
            key_label = QLabel(key)
            key_label.setProperty("mono", True)
            key_label.setProperty("hint", True)
            key_label.setFixedWidth(80)
            row.addWidget(key_label)
            val_label = QLabel(val)
            val_label.setProperty("mono", True)
            row.addWidget(val_label)
            if is_link:
                ext_icon = QLabel()
                ext_icon.setPixmap(icons.get_pixmap("external", size=10))
                row.addWidget(ext_icon)
            row.addStretch(1)
            container = QWidget()
            container.setLayout(row)
            layout.addWidget(container)

        layout.addSpacing(12)
        update_row = QHBoxLayout()
        update_btn = QPushButton("Kiểm tra cập nhật")
        update_btn.setProperty("soft", True)
        update_btn.setIcon(icons.get_icon("refresh", color="#a4a9b3", size=12))
        update_row.addWidget(update_btn)
        update_meta = QLabel("Đã kiểm tra vừa rồi · mới nhất")
        update_meta.setProperty("hint", True)
        update_row.addWidget(update_meta)
        update_row.addStretch(1)
        layout.addLayout(update_row)
        layout.addStretch(1)
        return pane

    def _build_ack_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(6)
        for name, blurb in _DEPS:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QWidget()
            dot.setFixedSize(6, 6)
            row.addWidget(dot, alignment=Qt.AlignmentFlag.AlignVCenter)
            name_label = QLabel(name)
            name_label.setProperty("mono", True)
            name_label.setFixedWidth(120)
            row.addWidget(name_label)
            blurb_label = QLabel(blurb)
            blurb_label.setProperty("hint", True)
            row.addWidget(blurb_label, stretch=1)
            container = QWidget()
            container.setLayout(row)
            layout.addWidget(container)
        layout.addSpacing(8)
        foot = QLabel("Chi tiết license trong LICENSE.md")
        foot.setProperty("hint", True)
        layout.addWidget(foot)
        layout.addStretch(1)
        return pane

    def _build_author_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(24, 24, 24, 18)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        avatar_row = QHBoxLayout()
        avatar_row.addStretch(1)
        avatar = QLabel()
        avatar.setPixmap(icons.get_pixmap("user", size=42))
        avatar.setFixedSize(72, 72)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            "background: rgba(255,255,255,0.06); border-radius: 36px;"
        )
        avatar_row.addWidget(avatar)
        avatar_row.addStretch(1)
        layout.addLayout(avatar_row)

        name_label = QLabel("orms147")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(name_label)

        handle = QLabel("github.com/orms147")
        handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        handle.setProperty("hint", True)
        layout.addWidget(handle)

        line = QLabel("Made for ĐATN ITSS in Japanese · ITSS K67 HUST")
        line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        line.setProperty("hint", True)
        layout.addWidget(line)

        social_row = QHBoxLayout()
        social_row.addStretch(1)
        gh = IconButton("link", size=32, icon_size=15, tooltip="GitHub")
        mail = IconButton("mail", size=32, icon_size=15, tooltip="Email")
        social_row.addWidget(gh)
        social_row.addWidget(mail)
        social_row.addStretch(1)
        layout.addLayout(social_row)
        layout.addStretch(1)
        return pane

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QBrush(QColor(p.bg_0)))
        painter.setPen(QPen(QColor(p.border_2), 1))
        painter.drawRoundedRect(rect, 10, 10)
