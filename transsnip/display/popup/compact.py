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

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolTip, QWidget

from transsnip.ui.theme import get_theme

# Above these sizes the annotated layout is more noise than help.
COMPACT_HAN_CHARS = 40        # Chinese: Han characters in the text
COMPACT_WORDS = 25            # English IPA: words
COMPACT_BREAKDOWN_WORDS = 15  # learning-mode per-word gloss: entries


class CompactText(QLabel):
    """Flowing rich text where some runs are hoverable/clickable words."""

    activated = Signal(str)   # the run's key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.setOpenExternalLinks(False)
        self.setStyleSheet("background: transparent;")
        self._runs: list[tuple[str, str]] = []     # index → (key, tooltip html)
        self.linkHovered.connect(self._on_hover)
        self.linkActivated.connect(self._on_activate)

    def set_runs(self, runs: list[tuple[str, str | None, str]], *, size_pt: int,
                 font_css: str = "", line_height: int = 150) -> None:
        """`runs`: (text, key or None for plain text, tooltip html)."""
        p = get_theme().palette
        self._runs = []
        out: list[str] = []
        for text, key, tip in runs:
            esc = html.escape(text).replace("\n", "<br>")
            if key is None:
                out.append(esc)
                continue
            out.append(f"<a href='w:{len(self._runs)}' style='color:{p.text_1}; "
                       f"text-decoration:none;'>{esc}</a>")
            self._runs.append((key, tip))
        # Double-quoted style: font_css carries single-quoted family names.
        self.setText(f'<div style="font-size:{size_pt}pt; line-height:{line_height}%; '
                     f'color:{p.text_1};{font_css}">{"".join(out)}</div>')

    def _run(self, href: str) -> tuple[str, str] | None:
        if not href.startswith("w:"):
            return None
        i = int(href[2:])
        return self._runs[i] if 0 <= i < len(self._runs) else None

    def _on_hover(self, href: str) -> None:
        run = self._run(href) if href else None
        if run and run[1]:
            QToolTip.showText(QCursor.pos(), run[1], self)
        else:
            QToolTip.hideText()

    def _on_activate(self, href: str) -> None:
        run = self._run(href)
        if run:
            self.activated.emit(run[0])


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
