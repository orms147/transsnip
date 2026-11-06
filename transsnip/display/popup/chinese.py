"""Chinese source block for the result popup (study mode).

Each word is a small clickable "cell" of three rows — pinyin (tone-coloured),
the characters, and their Hán-Việt reading — wrapped like text across lines,
followed by the sentence's full Hán-Việt reading. Clicking a word opens the
word card (`word_clicked`). Long passages start in the compact reading view
(compact.py): plain flowing characters, the reading in a hover tooltip.
Segmentation, pinyin and Hán-Việt are offline (learning/zh), so the block
appears with the OCR result, before translation.
"""
from __future__ import annotations

import html
import logging

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QLabel,
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from transsnip.display.popup.compact import COMPACT_HAN_CHARS, CompactText, ModeToggle
from transsnip.display.popup.constants import cjk_font_css
from transsnip.learning.zh.text import TONE_COLORS, Token
from transsnip.ui.theme import get_theme

log = logging.getLogger(__name__)


class FlowLayout(QLayout):
    """Left-to-right layout that wraps to new lines (Qt's classic example)."""

    def __init__(self, parent: QWidget | None = None, *, h_gap: int = 4, v_gap: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h, self._v = h_gap, v_gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int) -> QLayoutItem | None:
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int) -> QLayoutItem | None:
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _do_layout(self, rect: QRect, *, apply: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + self._v, 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class _WordCell(QWidget):
    """pinyin / hanzi / Hán-Việt stacked; hover-highlighted; click = open card."""

    clicked = Signal(str)

    def __init__(self, token: Token, hanviet: str, *, show_pinyin: bool, show_hv: bool,
                 tone_colors: bool, scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._word = token.text
        self._clickable = token.is_word
        p = get_theme().palette
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 1, 3, 2)
        lay.setSpacing(0)

        def color_of(tone: int, fallback: str) -> str:
            return TONE_COLORS.get(tone, fallback) if tone_colors and tone else fallback

        if show_pinyin:
            py = QLabel(" ".join(
                f"<span style='color:{color_of(s.tone, p.text_2)}'>{html.escape(s.pinyin)}</span>"
                for s in token.syllables if s.pinyin) or "&nbsp;")
            py.setStyleSheet(f"font-size:{max(7, round(9 * scale))}pt; background:transparent;")
            py.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            py.setTextFormat(Qt.TextFormat.RichText)  # '&nbsp;' alone isn't auto-detected
            lay.addWidget(py)
        hz = QLabel("".join(
            f"<span style='color:{color_of(s.tone, p.text_1)}'>{html.escape(s.char)}</span>"
            for s in token.syllables))
        hz.setStyleSheet(f"font-size:{max(10, round(15 * scale))}pt; background:transparent;"
                         + cjk_font_css("zh-Hans"))
        hz.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hz.setTextFormat(Qt.TextFormat.RichText)  # '&nbsp;' alone isn't auto-detected
        lay.addWidget(hz)
        if show_hv:
            hv = QLabel(html.escape(hanviet) if token.is_word else "&nbsp;")
            hv.setStyleSheet(f"color:{p.text_3}; font-size:{max(7, round(8.5 * scale))}pt;"
                             " background:transparent;")
            hv.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            hv.setTextFormat(Qt.TextFormat.RichText)  # '&nbsp;' alone isn't auto-detected
            lay.addWidget(hv)
        if self._clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Bấm để tra từ")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setObjectName("cell")
        self.setStyleSheet(
            f"#cell {{ border-radius:6px; }} #cell:hover {{ background:{p.accent_soft}; }}"
            if self._clickable else "")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._word)
        super().mouseReleaseEvent(event)


class ChineseSource(QWidget):
    """The study-mode Chinese source block. `set_text()` is cheap after warm-up
    (jieba segmentation + SQLite lookups, a few ms per sentence)."""

    word_clicked = Signal(str, str)   # (word, the sentence it's in)
    relayout = Signal()               # switched compact/full — popup refits its height

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sentence = ""
        self._compact = False
        self._opts: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._toggle = ModeToggle()
        self._toggle.toggled.connect(self._set_compact)
        lay.addWidget(self._toggle)
        self._compact_text = CompactText()
        self._compact_text.activated.connect(self._on_compact_click)
        lay.addWidget(self._compact_text)
        self._cells_host = QWidget()
        self._flow = FlowLayout(self._cells_host)
        self._cells_host.setSizePolicy(QSizePolicy.Policy.Preferred,
                                       QSizePolicy.Policy.Preferred)
        lay.addWidget(self._cells_host)
        self._hv_line = QLabel()
        self._hv_line.setWordWrap(True)
        self._hv_line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._hv_line)

    def set_text(self, text: str, *, scale: float = 1.0, show_pinyin: bool = True,
                 show_hanviet: bool = True, tone_colors: bool = True) -> bool:
        """Render `text`. Returns False (and stays empty) if the Chinese data
        isn't installed — the caller then shows the plain source label."""
        from transsnip.learning.zh import dictionary as zd
        from transsnip.learning.zh.text import tokenize

        if not zd.available():
            return False
        self._sentence = text
        try:
            tokens = tokenize(text)
        except Exception:
            log.exception("Chinese tokenize failed")
            return False
        self._opts = dict(tokens=tokens, scale=scale, show_pinyin=show_pinyin,
                          show_hanviet=show_hanviet, tone_colors=tone_colors)
        long_text = sum(1 for c in text if "㐀" <= c <= "鿿") > COMPACT_HAN_CHARS
        self._toggle.setVisible(long_text)
        self._compact = long_text
        self._render()
        return True

    def _set_compact(self, compact: bool) -> None:
        self._compact = compact
        self._render()
        self.relayout.emit()

    def _render(self) -> None:
        from transsnip.learning.zh import dictionary as zd

        o = self._opts
        tokens, scale = o["tokens"], o["scale"]
        dictionary = zd.shared()
        self._toggle.set_compact(self._compact)
        self._compact_text.setVisible(self._compact)
        self._cells_host.setVisible(not self._compact)
        while (item := self._flow.takeAt(0)) is not None:
            if (w := item.widget()) is not None:
                w.deleteLater()
        if self._compact:
            runs, pos = [], 0
            for t in tokens:     # key = the token's span, to find its sentence on click
                key = f"{pos}:{pos + len(t.text)}" if t.is_word else None
                runs.append((t.text, key, self._tooltip(t, dictionary) if key else ""))
                pos += len(t.text)
            self._compact_text.set_runs(
                runs, size_pt=max(10, round(13 * scale)), font_css=cjk_font_css("zh-Hans"),
                line_height=160)
        show_pinyin, show_hanviet = o["show_pinyin"], o["show_hanviet"]
        tone_colors = o["tone_colors"]
        pos = 0
        for t in tokens if not self._compact else ():
            start, pos = pos, pos + len(t.text)
            if t.text.isspace():
                continue
            cell = _WordCell(t, dictionary.token_hanviet(t) if t.is_word else "",
                             show_pinyin=show_pinyin, show_hv=show_hanviet,
                             tone_colors=tone_colors, scale=scale)
            cell.clicked.connect(lambda w, a=start, b=pos: self._emit_word(w, a, b))
            self._flow.addItem(QWidgetItem(cell))
            cell.setParent(self._cells_host)
            cell.show()
        p = get_theme().palette
        # A whole paragraph's Hán-Việt reading is a second wall of text — in the
        # compact view it's per word, in the tooltip.
        self._hv_line.setVisible(show_hanviet and not self._compact)
        if show_hanviet and not self._compact:
            reading = zd.sentence_hanviet(tokens, dictionary)
            self._hv_line.setText(
                f"<span style='color:{p.text_3}'>Hán-Việt: </span>"
                f"<span style='color:{p.text_2}'>{html.escape(reading)}</span>")
            self._hv_line.setStyleSheet(
                f"font-size:{max(8, round(10 * scale))}pt; background:transparent;")
        self._cells_host.updateGeometry()
        self.updateGeometry()

    def _emit_word(self, word: str, start: int, end: int) -> None:
        from transsnip.learning.zh.text import sentence_at
        self.word_clicked.emit(word, sentence_at(self._sentence, start, end))

    def _on_compact_click(self, key: str) -> None:
        start, end = (int(x) for x in key.split(":"))
        self._emit_word(self._sentence[start:end], start, end)

    @staticmethod
    def _tooltip(token: Token, dictionary) -> str:
        """Hover card: characters + tone-coloured pinyin, Hán-Việt, meanings."""
        p = get_theme().palette
        pinyin = " ".join(
            f'<span style="color:{TONE_COLORS.get(s.tone, p.text_1)}">{html.escape(s.pinyin)}'
            "</span>" for s in token.syllables if s.pinyin)
        hv = dictionary.token_hanviet(token)
        entries = dictionary.lookup(token.text)
        meanings = [m for m in (entries[0].meanings if entries else ()) if not m.startswith("LT:")]
        lines = [f'<span style="font-size:16pt;{cjk_font_css("zh-Hans")}">'
                 f"{html.escape(token.text)}</span>&nbsp;&nbsp;"
                 f'<b style="font-size:12pt">{pinyin}</b>']
        if hv:
            lines.append(f'<span style="color:{p.text_3}">Hán-Việt</span>&nbsp; '
                         f"<b>{html.escape(hv)}</b>")
        lines += [f'<span style="color:{p.text_3}">{i}.</span> {html.escape(m)}'
                  for i, m in enumerate(meanings[:3], 1)]
        lines.append(f'<span style="color:{p.text_3}; font-size:9pt">Bấm để mở thẻ từ</span>')
        return "<br>".join(lines)

    def hasHeightForWidth(self) -> bool:
        return True

    def sizeHint(self) -> QSize:
        # The popup sizes itself from sizeHint(); report the height the words
        # actually wrap to at the current width (the default hint assumed one
        # very narrow column and inflated the popup with blank space).
        w = self.width() if self.width() > 50 else 420
        return QSize(w, self.heightForWidth(w))

    def heightForWidth(self, width: int) -> int:
        if self._compact:
            h = self._compact_text.heightForWidth(width)
        else:
            h = self._flow.heightForWidth(width)
        if not self._toggle.isHidden():
            h += 8 + self._toggle.sizeHint().height()
        if not self._hv_line.isHidden():
            h += 8 + self._hv_line.heightForWidth(width)
        return h
