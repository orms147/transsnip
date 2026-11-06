"""Compact reading view for LONG study text (Chinese pinyin/Hán-Việt, English IPA).

Per-word annotations (a reading row over every word, tone colours) help on a
short line but turn a paragraph into a wall of rainbow cells. Past a length
threshold the study blocks switch to this view: the text flows like normal
prose, each word is a link — hover shows its reading in a tooltip, click does
the block's usual action (open the word card / speak). A small toggle brings
the full annotations back on demand.
"""
from __future__ import annotations

import html

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from transsnip.ui.theme import get_theme
from transsnip.ui.tokens import qcolor

# Above these sizes the annotated layout is more noise than help.
COMPACT_HAN_CHARS = 40        # Chinese: Han characters in the text
COMPACT_WORDS = 25            # English IPA: words
COMPACT_BREAKDOWN_WORDS = 15  # learning-mode per-word gloss: entries


class HoverCard(QWidget):
    """Small themed card that follows the hovered word.

    Replaces QToolTip, whose native tooltip window came out black with dark
    text inside the glass popup (it doesn't take our theme reliably).
    """

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(320)
        self._label.setStyleSheet("background: transparent;")
        lay.addWidget(self._label)

    def show_html(self, body: str, near: QPoint) -> None:
        p = get_theme().palette
        self._label.setText(f'<div style="color:{p.text_1}; font-size:10.5pt; '
                            f'line-height:140%;">{body}</div>')
        self.adjustSize()
        screen = QGuiApplication.screenAt(near) or QGuiApplication.primaryScreen()
        x, y = near.x() + 12, near.y() + 22
        if screen is not None:
            avail = screen.availableGeometry()
            x = min(x, avail.right() - self.width() - 4)
            if y + self.height() > avail.bottom():
                y = near.y() - self.height() - 12      # flip above the cursor
        self.move(x, y)
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(p.bg_1))
        painter.setPen(QPen(qcolor(p.border_strong), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)


class CompactText(QLabel):
    """Flowing rich text where some runs are hoverable/clickable words.

    The hovered word gets a soft accent background and a HoverCard with its
    reading; click emits `activated(key)`.
    """

    activated = Signal(str)   # the run's key

    _card: HoverCard | None = None   # one shared card for every block

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.setOpenExternalLinks(False)
        self.setStyleSheet("background: transparent;")
        self._runs: list[tuple[str, str]] = []     # index → (key, card html)
        self._pieces: list[tuple[str, int | None]] = []   # (escaped text, run index)
        self._wrap = ("", "")
        self._hot: int | None = None
        self.linkHovered.connect(self._on_hover)
        self.linkActivated.connect(self._on_activate)

    def set_runs(self, runs: list[tuple[str, str | None, str]], *, size_pt: int,
                 font_css: str = "", line_height: int = 150) -> None:
        """`runs`: (text, key or None for plain text, hover-card html)."""
        p = get_theme().palette
        self._runs, self._pieces, self._hot = [], [], None
        for text, key, tip in runs:
            esc = html.escape(text).replace("\n", "<br>")
            if key is None:
                self._pieces.append((esc, None))
            else:
                self._pieces.append((esc, len(self._runs)))
                self._runs.append((key, tip))
        # Double-quoted style: font_css carries single-quoted family names.
        self._wrap = (f'<div style="font-size:{size_pt}pt; line-height:{line_height}%; '
                      f'color:{p.text_1};{font_css}">', "</div>")
        self._paint_text()

    def _paint_text(self) -> None:
        p = get_theme().palette
        out: list[str] = []
        for esc, i in self._pieces:
            if i is None:
                out.append(esc)
                continue
            bg = f" background-color:{p.accent_soft};" if i == self._hot else ""
            out.append(f'<a href="w:{i}" style="color:{p.text_1}; text-decoration:none;{bg}">'
                       f"{esc}</a>")
        self.setText(self._wrap[0] + "".join(out) + self._wrap[1])

    def _index(self, href: str) -> int | None:
        if not href.startswith("w:"):
            return None
        i = int(href[2:])
        return i if 0 <= i < len(self._runs) else None

    @classmethod
    def _shared_card(cls) -> HoverCard:
        if cls._card is None:
            cls._card = HoverCard()
        return cls._card

    def _on_hover(self, href: str) -> None:
        i = self._index(href) if href else None
        if i != self._hot:
            self._hot = i
            self._paint_text()
        if i is not None and self._runs[i][1]:
            self._shared_card().show_html(self._runs[i][1], QCursor.pos())
        elif CompactText._card is not None:
            CompactText._card.hide()

    def _on_activate(self, href: str) -> None:
        i = self._index(href)
        if i is not None:
            if CompactText._card is not None:
                CompactText._card.hide()
            self.activated.emit(self._runs[i][0])

    def leaveEvent(self, event) -> None:
        self._on_hover("")
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        if CompactText._card is not None:
            CompactText._card.hide()
        super().hideEvent(event)


class ModeToggle(QWidget):
    """Right-aligned "Hiện chú thích" / "Thu gọn" switch above a study block."""

    toggled = Signal(bool)    # True = compact

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        self._btn = QPushButton()
        self._btn.setProperty("ghost", True)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(lambda: self.toggled.emit(not self._compact))
        lay.addWidget(self._btn)
        self._compact = False
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self._btn.setText("Hiện chú thích từng từ" if compact else "Thu gọn")
        self._btn.setToolTip("Hiện cách đọc dưới mỗi từ" if compact else
                             "Đọc như văn bản thường — rê chuột vào từ để xem cách đọc")
        self._btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
