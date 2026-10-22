"""Word card ("Thẻ từ") — everything about one Chinese word, opened by clicking
a word in the popup's study block (or a saved word in the vocab notebook).

Offline sections render instantly: meaning (CVDICT), Hán-Việt + pinyin, HSK
level, per-character anatomy (radical, components, etymology hint) and the
stroke-order animation. The AI usage notes cost an LLM call, so they only run
when "Giải thích cách dùng" is pressed (cached per word + sentence + model).
"""
from __future__ import annotations

import html
import logging
from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transsnip.config.settings import ZhStudySettings
from transsnip.display.popup.constants import cjk_font_css
from transsnip.learning.vocab import VocabEntry, VocabStore
from transsnip.learning.zh import dictionary as zd
from transsnip.learning.zh.text import TONE_COLORS, Syllable, Token, tokenize
from transsnip.tts.edge_tts_player import EdgeTTSPlayer
from transsnip.ui.atoms import CustomTitlebar, IconButton
from transsnip.ui.theme import get_theme
from transsnip.utils.workers import run_in_pool

log = logging.getLogger(__name__)

_ZH_VOICE = "zh-CN-XiaoxiaoNeural"
_ETYM_VI = {"pictographic": "Tượng hình", "ideographic": "Hội ý",
            "pictophonetic": "Hình thanh"}


def _colored(syllables: tuple[Syllable, ...], attr: str, fallback: str, on: bool) -> str:
    return "".join(
        f"<span style='color:{TONE_COLORS.get(s.tone, fallback) if on and s.tone else fallback}'>"
        f"{html.escape(getattr(s, attr) or '')}</span>" + (" " if attr == "pinyin" else "")
        for s in syllables if getattr(s, attr)
    ).strip()


def _components(ids: str) -> list[str]:
    """IDS "⿰女子" → ["女", "子"]. The ⿰⿱… operators and "？" (unknown part)
    render as boxes in most fonts, and "女 + 子" reads better anyway."""
    return [c for c in ids if not ("⿰" <= c <= "⿿") and c not in "？?"]


def _section(title: str) -> QLabel:
    lab = QLabel(title.upper())
    lab.setProperty("cardSection", True)
    return lab


class WordCardWindow(QWidget):
    """Companion of the result popup: it closes together with the popup when
    the user clicks elsewhere (see dismiss.py), unless its pin is on."""

    open_vocab_requested = Signal()
    # Focus left this card for a window outside the popup group.
    focus_left_group = Signal()

    def __init__(self, vocab: VocabStore, translator_provider: Callable[[], object],
                 parent: QWidget | None = None) -> None:
        # Tool window: no taskbar button of its own (it belongs with the popup).
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self._pinned = False
        self._group_owner: Callable[[QWidget | None], bool] | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(430, 640)
        self._vocab = vocab
        self._translator_provider = translator_provider   # active LLM translator, if any
        self._settings = ZhStudySettings()
        self._tts = EdgeTTSPlayer(self)
        self._word = ""
        self._sentence = ""
        self._translation = ""
        self._token: Token | None = None
        self._gen = 0                       # drops stale async results

        self._root = QWidget(self)
        self._root.setObjectName("cardRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._root)
        root = QVBoxLayout(self._root)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._titlebar = CustomTitlebar("Thẻ từ", show_minimize=False, show_maximize=False)
        self._titlebar.close_requested.connect(self.hide)
        root.addWidget(self._titlebar)
        self._pin_btn = IconButton("pin", size=28, icon_size=14,
                                   tooltip="Ghim thẻ (không tự đóng khi bấm ra ngoài)")
        self._pin_btn.clicked.connect(self._toggle_pin)
        self._titlebar.layout().insertWidget(self._titlebar.layout().count() - 1, self._pin_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._body = QWidget()
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(18, 10, 18, 18)
        self._lay.setSpacing(10)
        scroll.setWidget(self._body)
        root.addWidget(scroll, stretch=1)

        # Header: word · pinyin · Hán-Việt · HSK · speak · save
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        self._word_lbl = QLabel()
        self._word_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._pinyin_lbl = QLabel()
        self._hv_lbl = QLabel()
        for w in (self._word_lbl, self._pinyin_lbl, self._hv_lbl):
            col.addWidget(w)
        head.addLayout(col, stretch=1)
        side = QVBoxLayout()
        side.setSpacing(6)
        btns = QHBoxLayout()
        self._speak_btn = IconButton("volume", size=32, icon_size=16, tooltip="Nghe phát âm")
        self._speak_btn.clicked.connect(lambda: self.speak(self._word))
        self._save_btn = QPushButton("☆ Lưu")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setToolTip("Lưu vào Sổ từ (kèm câu gốc)")
        self._save_btn.clicked.connect(self._on_save)
        btns.addWidget(self._speak_btn)
        btns.addWidget(self._save_btn)
        side.addLayout(btns)
        self._hsk_lbl = QLabel()
        self._hsk_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        side.addWidget(self._hsk_lbl)
        side.addStretch(1)
        head.addLayout(side)
        self._lay.addLayout(head)

        self._meaning_lbl = QLabel()
        self._meaning_lbl.setWordWrap(True)
        self._meaning_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lay.addWidget(_section("Nghĩa"))
        self._lay.addWidget(self._meaning_lbl)

        self._lay.addWidget(_section("Từng chữ"))
        self._chars_box = QVBoxLayout()
        self._chars_box.setSpacing(6)
        self._lay.addLayout(self._chars_box)

        self._stroke_head = _section("Cách viết")
        self._lay.addWidget(self._stroke_head)
        self._stroke_area = QVBoxLayout()
        self._lay.addLayout(self._stroke_area)
        self._stroke_widget = None          # built lazily (Qt timer + data)
        self._stroke_char = ""

        self._lay.addWidget(_section("Cách dùng (AI)"))
        self._usage_btn = QPushButton("✨ Giải thích cách dùng + câu ví dụ")
        self._usage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._usage_btn.clicked.connect(self._on_usage)
        self._lay.addWidget(self._usage_btn)
        self._usage_lbl = QLabel()
        self._usage_lbl.setWordWrap(True)
        self._usage_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lay.addWidget(self._usage_lbl)

        foot = QHBoxLayout()
        foot.addStretch(1)
        vocab_btn = QPushButton("Mở Sổ từ")
        vocab_btn.setProperty("soft", True)
        vocab_btn.clicked.connect(self.open_vocab_requested.emit)
        foot.addWidget(vocab_btn)
        self._lay.addStretch(1)
        self._lay.addLayout(foot)

        get_theme().mode_changed.connect(lambda _p: self._apply_style())
        self._apply_style()

    # ── public ───────────────────────────────────────────────────────────

    def set_group_owner(self, owns: Callable[[QWidget | None], bool]) -> None:
        """`owns(window)` → True if `window` is part of this card's popup group."""
        self._group_owner = owns

    def hide_unless_pinned(self) -> None:
        if not self._pinned:
            self.hide()

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        self._pin_btn.set_kind("accent" if self._pinned else "default")
        self._pin_btn.setToolTip("Bỏ ghim" if self._pinned else
                                 "Ghim thẻ (không tự đóng khi bấm ra ngoài)")

    def changeEvent(self, event) -> None:
        from PySide6.QtCore import QEvent, QTimer
        if (event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow()
                and self.isVisible()):
            QTimer.singleShot(0, self._close_if_focus_left_group)
        super().changeEvent(event)

    def _close_if_focus_left_group(self) -> None:
        from PySide6.QtWidgets import QApplication
        active = QApplication.activeWindow()
        if active is self or (self._group_owner and self._group_owner(active)):
            return
        if not self._pinned:
            self.hide()
        # Always tell the popup — an unpinned popup closes even if this card is pinned.
        self.focus_left_group.emit()

    def set_settings(self, zs: ZhStudySettings) -> None:
        self._settings = zs

    def set_output_device(self, description: str) -> None:
        self._tts.set_output_device(description)

    def show_word(self, word: str, sentence: str = "", translation: str = "",
                  *, near: QRect | None = None) -> None:
        self._gen += 1
        self._word, self._sentence, self._translation = word, sentence, translation
        # Read the word as it was pronounced IN the sentence (polyphones).
        self._token = next((t for t in tokenize(sentence or word) if t.text == word), None) \
            or (tokenize(word) or [Token(word)])[0]
        self._render()
        if not self.isVisible():
            self._place(near)
        self.show()
        self.raise_()

    # ── rendering ────────────────────────────────────────────────────────

    def _render(self) -> None:
        p = get_theme().palette
        tone_on = self._settings.tone_colors
        tok = self._token
        dictionary = zd.shared() if zd.available() else None
        syl = tok.syllables if tok else ()
        self._word_lbl.setText(_colored(syl, "char", p.text_1, tone_on))
        self._pinyin_lbl.setText(_colored(syl, "pinyin", p.text_2, tone_on))
        hv = dictionary.token_hanviet(tok) if dictionary and tok else ""
        self._hv_lbl.setText(f"<span style='color:{p.text_3}'>Hán-Việt:</span> "
                             f"<b>{html.escape(hv.upper())}</b>" if hv else "")
        level = dictionary.hsk_level(self._word) if dictionary else None
        self._hsk_lbl.setText(
            f"<span style='background:{p.accent_soft}; color:{p.accent}; padding:2px 6px;"
            f" border-radius:6px'>&nbsp;HSK {'7-9' if level == 7 else level}&nbsp;</span>"
            if level else "")
        self._render_meaning(dictionary)
        self._render_chars(dictionary)
        self._render_strokes()
        self._usage_lbl.setText("")
        self._usage_btn.setEnabled(True)
        self._usage_btn.setText("✨ Giải thích cách dùng + câu ví dụ")
        self._refresh_save()

    def _render_meaning(self, dictionary) -> None:
        p = get_theme().palette
        entries = dictionary.lookup(self._word) if dictionary else []
        want = " ".join(s.numbered for s in (self._token.syllables if self._token else ())
                        if s.numbered)
        # Entry matching the in-context pronunciation first (行 háng vs xíng).
        entries.sort(key=lambda e: e.pinyin.lower() != want)
        lines: list[str] = []
        for e in entries[:3]:
            meanings = [m for m in e.meanings if not m.startswith("LT:")][:5]
            if meanings:
                lines.append("<br>".join(
                    f"<span style='color:{p.text_3}'>{i}.</span> {html.escape(m)}"
                    for i, m in enumerate(meanings, 1)))
        if not lines:
            lines = [f"<span style='color:{p.text_3}'>Không có trong từ điển offline — "
                     "thử “Giải thích cách dùng”.</span>"]
        if self._sentence and self._sentence != self._word:
            lines.append(
                f"<span style='color:{p.text_3}'>Trong câu:</span> "
                f'<span style="{cjk_font_css("zh-Hans")[1:]}">{html.escape(self._sentence)}'
                "</span>" + (f"<br><span style='color:{p.text_3}'>"
                             f"{html.escape(self._translation)}</span>"
                             if self._translation else ""))
        self._meaning_lbl.setText("<br><br>".join(lines))

    def _render_chars(self, dictionary) -> None:
        while (item := self._chars_box.takeAt(0)) is not None:
            if item.widget():
                item.widget().deleteLater()
        if not dictionary or not self._token:
            return
        p = get_theme().palette
        for s in self._token.syllables:
            if not s.tone:
                continue
            info = dictionary.char_info(s)
            row = QLabel()
            row.setWordWrap(True)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip("Bấm để xem cách viết chữ này")
            others = [r.strip() for r in info.hanviet_all.split(",")
                      if r.strip() and r.strip() != info.hanviet]
            bits = [f"<b>{html.escape(info.hanviet.upper())}</b>"
                    + (f" <span style='color:{p.text_3}'>({', '.join(others[:4])})</span>"
                       if others else ""),
                    f"<span style='color:{TONE_COLORS.get(s.tone, p.text_2)}'>{s.pinyin}</span>"]
            if info.radical:
                bits.append(f"bộ {html.escape(info.radical)}")
            parts = _components(info.decomposition)
            if parts:
                bits.append(f"cấu tạo {html.escape(' + '.join(parts))}")
            meaning = "; ".join(m for m in info.meanings[:3] if not m.startswith("LT:"))
            etym = _ETYM_VI.get(info.etym_type, "")
            row.setText(
                f'<table><tr><td style="padding-right:10px; font-size:24pt;'
                f'{cjk_font_css("zh-Hans")[1:]}">{html.escape(s.char)}</td><td>'
                + " · ".join(bits)
                + (f"<br>{html.escape(meaning)}" if meaning else "")
                + (f"<br><span style='color:{p.text_3}'>{etym}"
                   f"{': ' + html.escape(info.etym_hint) if info.etym_hint else ''}</span>"
                   if etym else "")
                + "</td></tr></table>")
            row.mousePressEvent = (  # type: ignore[method-assign]
                lambda _e, c=s.char: self._show_strokes(c))
            self._chars_box.addWidget(row)

    # ── stroke order ─────────────────────────────────────────────────────

    def _render_strokes(self) -> None:
        first = next((s.char for s in (self._token.syllables if self._token else ())
                      if s.tone), "")
        self._show_strokes(first)

    def _show_strokes(self, char: str) -> None:
        from transsnip.learning.zh.strokes import StrokeStore

        while (item := self._stroke_area.takeAt(0)) is not None:
            w = item.widget()
            if w is not None and w is not self._stroke_widget:
                w.deleteLater()
        p = get_theme().palette
        if not self._settings.stroke_animation:
            hint = QLabel("Đang tắt — bật “Cách viết (animation)” trong Cài đặt → "
                          "Học tiếng Trung.")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color:{p.text_3}")
            self._stroke_area.addWidget(hint)
            if self._stroke_widget is not None:
                self._stroke_widget.hide()
            return
        store = StrokeStore()
        if not store.available():
            btn = QPushButton("⬇ Tải dữ liệu cách viết (~30 MB, một lần)")
            btn.clicked.connect(lambda: self._download_strokes(btn))
            self._stroke_area.addWidget(btn)
            return
        if self._stroke_widget is None:
            from transsnip.ui.stroke_widget import StrokeOrderWidget
            self._stroke_widget = StrokeOrderWidget()
            self._stroke_widget.setFixedSize(180, 180)
        self._stroke_char = char
        self._stroke_widget.set_char(char, store.get(char) if char else None)
        self._stroke_area.addWidget(self._stroke_widget, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._stroke_widget.show()
        self._stroke_widget.replay()

    def _download_strokes(self, btn: QPushButton) -> None:
        from transsnip.learning.zh import strokes

        btn.setEnabled(False)
        btn.setText("Đang tải…")
        gen = self._gen
        run_in_pool(strokes.download,
                    lambda _r: gen == self._gen and self._show_strokes(self._stroke_char or
                                                                       self._word[:1]),
                    lambda err: btn.setText(f"Lỗi tải: {err} — bấm để thử lại")
                    or btn.setEnabled(True),
                    label="stroke data download")

    # ── AI usage ─────────────────────────────────────────────────────────

    def _on_usage(self) -> None:
        from transsnip.learning.zh.usage import explain
        from transsnip.translate.llm import LLMTranslator

        translator = self._translator_provider()
        if not isinstance(translator, LLMTranslator) or not translator.is_available():
            self._usage_lbl.setText(
                "Cần chọn một model AI (Gemini / Claude / OpenRouter) trong Cài đặt → "
                "Nhà cung cấp — Google dịch miễn phí không giải thích được cách dùng.")
            return
        self._usage_btn.setEnabled(False)
        self._usage_btn.setText("Đang hỏi AI… (~5 giây)")
        gen, word, sentence = self._gen, self._word, self._sentence
        run_in_pool(lambda: explain(translator, word, sentence),
                    lambda note: gen == self._gen and self._show_usage(note),
                    lambda err: gen == self._gen and self._usage_failed(err),
                    label="usage notes")

    def _usage_failed(self, err: str) -> None:
        self._usage_btn.setEnabled(True)
        self._usage_btn.setText("Thử lại")
        self._usage_lbl.setText(f"Không lấy được giải thích: {html.escape(err)}")

    def _show_usage(self, note) -> None:
        p = get_theme().palette
        self._usage_btn.hide()
        parts: list[str] = []
        if note.meaning_here:
            parts.append(f"<b>Nghĩa ở đây:</b> {html.escape(note.meaning_here)}")
        if note.explanation:
            parts.append(html.escape(note.explanation))
        if note.grammar:
            parts.append("<b>Mẫu câu:</b><br>" + "<br>".join(
                f"• {html.escape(g)}" for g in note.grammar))
        if note.examples:
            parts.append("<b>Ví dụ:</b><br>" + "<br>".join(
                f'<span style="font-size:13pt;{cjk_font_css("zh-Hans")[1:]}">'
                f"{html.escape(e.zh)}</span><br>"
                f"<span style='color:{p.accent}'>{html.escape(e.pinyin)}</span><br>"
                f"<span style='color:{p.text_2}'>{html.escape(e.vi)}</span>"
                for e in note.examples))
        if note.collocations:
            parts.append("<b>Hay đi kèm:</b> " + ", ".join(map(html.escape, note.collocations)))
        if note.confusables:
            parts.append("<b>Dễ nhầm:</b><br>" + "<br>".join(
                f"• {html.escape(w)} — {html.escape(d)}" for w, d in note.confusables))
        self._usage_lbl.setText("<br><br>".join(parts))

    # ── notebook / speech ────────────────────────────────────────────────

    def _refresh_save(self) -> None:
        self._usage_btn.show()
        saved = self._vocab.contains(self._word)
        self._save_btn.setText("★ Đã lưu" if saved else "☆ Lưu")

    def _on_save(self) -> None:
        if self._vocab.contains(self._word):
            self._vocab.remove(self._word)
        else:
            tok = self._token
            dictionary = zd.shared() if zd.available() else None
            entries = dictionary.lookup(self._word) if dictionary else []
            self._vocab.add(VocabEntry(
                word=self._word, pinyin=tok.pinyin if tok else "",
                hanviet=dictionary.token_hanviet(tok) if dictionary and tok else "",
                meaning="; ".join(entries[0].meanings[:3]) if entries else "",
                example=self._sentence if self._sentence != self._word else "",
                example_vi=self._translation))
        self._refresh_save()

    def speak(self, text: str) -> None:
        if text:
            self._tts.speak(text, voice=_ZH_VOICE)

    # ── chrome ───────────────────────────────────────────────────────────

    def _place(self, near: QRect | None) -> None:
        screen = (QGuiApplication.screenAt(near.center()) if near else None) \
            or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        if near is not None:
            x = near.right() + 12
            if x + self.width() > avail.right():
                x = near.left() - 12 - self.width()
            y = min(near.top(), avail.bottom() - self.height())
            pos = QPoint(max(avail.left(), x), max(avail.top(), y))
        else:
            pos = avail.center() - QPoint(self.width() // 2, self.height() // 2)
        self.move(pos)

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._root.setStyleSheet(
            f"QWidget#cardRoot {{ background:{p.bg_1}; border:1px solid {p.border_2};"
            f" border-radius:12px; }}"
            f"QLabel[cardSection='true'] {{ color:{p.text_3}; font-size:10px;"
            f" font-weight:600; letter-spacing:1px; margin-top:6px; }}")
        self._word_lbl.setStyleSheet(f"font-size:30pt; {cjk_font_css('zh-Hans')[1:]}")
        self._pinyin_lbl.setStyleSheet("font-size:14pt;")
        self._hv_lbl.setStyleSheet(f"color:{p.text_2}; font-size:11pt;")
        self._meaning_lbl.setStyleSheet(f"color:{p.text_1}; font-size:11pt;")
        self._usage_lbl.setStyleSheet(f"color:{p.text_1}; font-size:10.5pt;")
        if self._word:
            self._render()
