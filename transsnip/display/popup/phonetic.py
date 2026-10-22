"""English source + IPA rendering (two-row furigana layout, per-word breakdown)."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
)
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from transsnip.display.popup.compact import (
    COMPACT_BREAKDOWN_WORDS,
    COMPACT_WORDS,
    CompactText,
    ModeToggle,
)
from transsnip.display.popup.constants import (
    _FONT_IPA_PT,
    _FONT_SOURCE_PT,
    _IPA_FONT_CSS,
    _IPA_FONT_FAMILIES,
    _IPA_TOKEN_RE,
    _SPEAK_LINK_PREFIX,
)
from transsnip.linguistic.ipa import get_ipa
from transsnip.ui.theme import get_theme


# ── PhoneticSource (2-row English source + IPA, click-to-speak) ───────────
class _PhoneticSource(QWidget):
    """English source rendered as two stacked rows: words on top, IPA below.

    Each word + its IPA share a `speak:<word>` anchor → click either to
    fire `speak_requested(word)` which the parent popup wires to TTS.

    Implemented as a single rich-text QLabel for now (HTML two-row layout
    with `<div>` blocks). A future iteration could move to per-word
    QPushButtons for keyboard navigation, but the QLabel approach mirrors
    the React component's behavior closely and stays lightweight.
    """

    speak_requested = Signal(str)
    relayout = Signal()   # switched compact/full — popup refits its height

    _COL_GAP = 12  # px between word columns

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        # Long text: plain prose, IPA on hover (compact.py).
        self._compact = False
        self._toggle = ModeToggle()
        self._toggle.toggled.connect(self._set_compact)
        layout.addWidget(self._toggle)
        self._compact_text = CompactText()
        self._compact_text.activated.connect(self.speak_requested.emit)
        layout.addWidget(self._compact_text)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._label.setOpenExternalLinks(False)
        self._label.linkActivated.connect(self._on_link)
        layout.addWidget(self._label)
        self._text = ""
        self._scale = 1.0
        self._avail_px = 380  # fallback width hint; the live widget width wins
        self._last_render_w = 0
        get_theme().mode_changed.connect(lambda _p: self._render())

    def set_text(self, text: str, *, scale: float = 1.0, avail_px: int | None = None) -> None:
        self._text = text
        self._scale = scale
        if avail_px and avail_px > 80:
            self._avail_px = avail_px
        long_text = len(_IPA_TOKEN_RE.findall(text)) > COMPACT_WORDS
        self._toggle.setVisible(long_text)
        self._compact = long_text
        self._render()

    def _set_compact(self, compact: bool) -> None:
        self._compact = compact
        self._render()
        self.relayout.emit()

    def resizeEvent(self, event) -> None:
        # Re-pack rows to the widget's REAL width whenever it changes. This is
        # the reliable source of width — a snapshot avail_px passed at set_text
        # time can be stale (computed before the popup reached its final size),
        # which left the phonetic rows breaking early with empty space on the
        # right. Guard against re-render loops (only when width actually moved).
        super().resizeEvent(event)
        if self._text and abs(self.width() - self._last_render_w) > 4:
            self._render()

    def _wrap_width(self) -> int:
        # Prefer the widget's actual width once laid out; fall back to the hint.
        w = self.width()
        return (w if w > 80 else self._avail_px)

    def _on_link(self, href: str) -> None:
        if href.startswith(_SPEAK_LINK_PREFIX):
            word = href[len(_SPEAK_LINK_PREFIX):].strip()
            if word:
                self.speak_requested.emit(word)

    def _render(self) -> None:
        # Each line's words are packed into ROWS that fit the available width;
        # every row is a 2-row table (words over IPA, aligned per column). This
        # wraps VERTICALLY by stacking tables — unlike the old single-line
        # approach which used non-breaking spaces and overflowed on long text.
        self._toggle.set_compact(self._compact)
        self._compact_text.setVisible(self._compact)
        self._label.setVisible(not self._compact)
        if self._compact:
            self._render_compact()
            return
        p = get_theme().palette
        word_color = p.text_1
        ipa_color = p.accent
        dash_color = p.text_mute
        source_pt = max(8, round(_FONT_SOURCE_PT * self._scale))
        ipa_pt = max(7, round(_FONT_IPA_PT * self._scale))

        wf = QFont()
        wf.setPointSize(source_pt)
        ipf = QFont()
        ipf.setPointSize(ipa_pt)
        ipf.setFamilies(_IPA_FONT_FAMILIES)  # keep width math on the render font
        wm = QFontMetrics(wf)
        im = QFontMetrics(ipf)
        self._last_render_w = self.width()
        avail = max(120, self._wrap_width() - 6)

        out: list[str] = []
        for raw_line in (self._text or "").splitlines() or [self._text or ""]:
            # Build columns: (word, ipa, column_width_px).
            cols: list[tuple[str, str | None, int]] = []
            for token in _IPA_TOKEN_RE.findall(raw_line):
                if not token.strip():
                    continue
                ipa = get_ipa(token)
                ww = wm.horizontalAdvance(token)
                iw = im.horizontalAdvance(f"/{ipa}/") if ipa else 0
                cols.append((token, ipa, max(ww, iw) + self._COL_GAP))
            if not cols:
                continue
            # Greedy-pack columns into rows that fit `avail`.
            rows: list[list[tuple[str, str | None, int]]] = []
            cur: list[tuple[str, str | None, int]] = []
            cur_w = 0
            for col in cols:
                if cur and cur_w + col[2] > avail:
                    rows.append(cur)
                    cur, cur_w = [], 0
                cur.append(col)
                cur_w += col[2]
            if cur:
                rows.append(cur)
            for row in rows:
                out.append(self._row_table(row, source_pt, ipa_pt,
                                           word_color, ipa_color, dash_color))
        self._label.setText("".join(out))

    def _render_compact(self) -> None:
        p = get_theme().palette
        runs: list[tuple[str, str | None, str]] = []
        pos = 0
        text = self._text or ""
        for m in _IPA_TOKEN_RE.finditer(text):
            if m.start() > pos:
                runs.append((text[pos:m.start()], None, ""))
            token = m.group(0)
            ipa = get_ipa(token) if token.strip() else None
            tip = (f"<span style='color:{p.accent}; font-family:{_IPA_FONT_CSS}; "
                   f"font-size:12pt'>/{html.escape(ipa)}/</span><br>"
                   f"<span style='color:{p.text_3}'>Bấm để nghe</span>") if ipa else ""
            runs.append((token, token if ipa else None, tip))
            pos = m.end()
        if pos < len(text):
            runs.append((text[pos:], None, ""))
        self._compact_text.set_runs(runs, size_pt=max(8, round(_FONT_SOURCE_PT * self._scale)))

    @staticmethod
    def _row_table(row, source_pt, ipa_pt, word_color, ipa_color, dash_color) -> str:
        """One packed row → a 2-row HTML table (word over IPA, aligned columns)."""
        word_tds: list[str] = []
        ipa_tds: list[str] = []
        for token, ipa, _w in row:
            esc = html.escape(token)
            pad = "padding:0 6px 0 0; white-space:nowrap;"
            if ipa:
                href = f"{_SPEAK_LINK_PREFIX}{esc}"
                word_tds.append(
                    f"<td style='{pad}'><a href='{href}' style='color:{word_color}; "
                    f"text-decoration:none; font-size:{source_pt}pt;'>{esc}</a></td>"
                )
                ipa_tds.append(
                    f"<td style='{pad}'><a href='{href}' style='color:{ipa_color}; "
                    f"text-decoration:none; font-size:{ipa_pt}pt; "
                    f"font-family:{_IPA_FONT_CSS};'>/{html.escape(ipa)}/</a></td>"
                )
            else:
                word_tds.append(
                    f"<td style='{pad} color:{word_color}; font-size:{source_pt}pt;'>{esc}</td>"
                )
                ipa_tds.append(
                    f"<td style='{pad} color:{dash_color}; font-size:{ipa_pt}pt;'>—</td>"
                )
        return (
            "<table cellspacing='0' cellpadding='0' style='margin-bottom:6px;'>"
            f"<tr>{''.join(word_tds)}</tr><tr>{''.join(ipa_tds)}</tr></table>"
        )


class _WordBreakdown(QWidget):
    """Learning-mode per-word gloss: one line per word — token (click to speak)
    + IPA + meaning + part of speech.

    Rendered as a single rich-text QLabel (same approach as `_PhoneticSource`):
    Qt's rich-text engine doesn't do flow-of-cards layouts reliably, so a
    vertical list is both robust and the clearest format for studying.
    """

    speak_requested = Signal(str)
    relayout = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(6)
        # Many words: one flowing line of words, gloss on hover (compact.py).
        self._compact = False
        self._toggle = ModeToggle()
        self._toggle.toggled.connect(self._set_compact)
        layout.addWidget(self._toggle)
        self._compact_text = CompactText()
        self._compact_text.activated.connect(self.speak_requested.emit)
        layout.addWidget(self._compact_text)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._label.setOpenExternalLinks(False)
        self._label.linkActivated.connect(self._on_link)
        layout.addWidget(self._label)
        self._words: list = []
        self._scale = 1.0
        get_theme().mode_changed.connect(lambda _p: self._render())

    def set_words(self, words: list, *, scale: float = 1.0) -> None:
        self._words = words or []
        self._scale = scale
        long_list = len(self._words) > COMPACT_BREAKDOWN_WORDS
        self._toggle.setVisible(long_list)
        self._compact = long_list
        self._render()

    def _set_compact(self, compact: bool) -> None:
        self._compact = compact
        self._render()
        self.relayout.emit()

    def _on_link(self, href: str) -> None:
        if href.startswith(_SPEAK_LINK_PREFIX):
            word = href[len(_SPEAK_LINK_PREFIX):].strip()
            if word:
                self.speak_requested.emit(word)

    def _render(self) -> None:
        p = get_theme().palette
        token_pt = max(8, round(_FONT_SOURCE_PT * self._scale))
        small_pt = max(7, round(_FONT_IPA_PT * self._scale))
        self._toggle.set_compact(self._compact)
        self._compact_text.setVisible(self._compact)
        self._label.setVisible(not self._compact)
        if self._compact:
            runs: list[tuple[str, str | None, str]] = []
            for i, w in enumerate(self._words):
                if i:
                    runs.append((" ", None, ""))
                tip = []
                if getattr(w, "ipa", None):
                    tip.append(f"<span style='color:{p.accent}; font-family:{_IPA_FONT_CSS};"
                               f" font-size:12pt'>/{html.escape(w.ipa)}/</span>")
                if getattr(w, "pos", None):
                    tip.append(f"<span style='color:{p.text_3}'>{html.escape(w.pos)}</span>")
                if getattr(w, "meaning", None):
                    tip.append(html.escape(w.meaning))
                runs.append((w.token, w.token, "<br>".join(tip)))
            self._compact_text.set_runs(runs, size_pt=token_pt)
            return
        rows: list[str] = []
        for w in self._words:
            esc = html.escape(w.token)
            href = f"{_SPEAK_LINK_PREFIX}{esc}"
            ipa = (f" <span style='color:{p.accent}; font-family:{_IPA_FONT_CSS};'>"
                   f"/{html.escape(w.ipa)}/</span>"
                   if getattr(w, "ipa", None) else "")
            pos = (f" <span style='color:{p.text_mute};'>· {html.escape(w.pos)}</span>"
                   if getattr(w, "pos", None) else "")
            meaning = (
                f"<span style='color:{p.text_2};'>{html.escape(w.meaning)}</span>"
                if getattr(w, "meaning", None)
                else f"<span style='color:{p.text_mute};'>—</span>"
            )
            rows.append(
                f"<div style='font-size:{small_pt}pt; line-height:1.65; margin-bottom:4px;'>"
                f"<a href='{href}' style='color:{p.text_1}; text-decoration:none; "
                f"font-size:{token_pt}pt; font-weight:600;'>{esc}</a>"
                f"{ipa}{pos} &nbsp;&nbsp;{meaning}</div>"
            )
        self._label.setText("".join(rows))
