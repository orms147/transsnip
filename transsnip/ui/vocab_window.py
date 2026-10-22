"""VocabWindow — "Sổ từ": browse saved words and review them as flashcards.

Same frameless chrome as HistoryWindow. Two tabs (Segmented):
  • Danh sách — searchable list (accent-insensitive via `fold`), speak / delete /
    open per row, Anki export.
  • Ôn tập (N) — SM-2 flashcards over `store.due()`; each grade button previews
    the interval `schedule()` would give, so the user sees the cost of "Dễ".

The window never speaks or opens the word card itself — it emits signals and the
app wires them to the TTS player / word card it already owns.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from transsnip.learning.vocab import GRADES, VocabEntry, VocabStore, schedule
from transsnip.ui.atoms import CustomTitlebar, IconButton, Segmented
from transsnip.ui.glass import Glass
from transsnip.ui.search_combo import fold
from transsnip.ui.theme import get_theme

_GRADE_LABELS = {"again": "Quên", "hard": "Khó", "good": "Được", "easy": "Dễ"}


def fmt_interval(seconds: float) -> str:
    """Human Vietnamese duration: "10 phút", "5 giờ", "3 ngày", "2 tháng"."""
    s = max(0, int(seconds))
    if s < 3600:
        return f"{max(1, round(s / 60))} phút"
    if s < 86_400:
        return f"{round(s / 3600)} giờ"
    days = round(s / 86_400)
    if days < 30:
        return f"{days} ngày"
    if days < 365:
        return f"{round(days / 30)} tháng"
    return f"{days / 365:.1f} năm".replace(".0 ", " ")


def fmt_due(due_at: int, now: int | None = None) -> str:
    now = int(now if now is not None else time.time())
    return "hôm nay" if due_at <= now else f"sau {fmt_interval(due_at - now)}"


class _ConfirmDeleteButton(QPushButton):
    """Two-step delete: first click arms ("Xoá?"), second click confirms.
    Disarms itself after 3 s — avoids a modal dialog for a cheap action."""

    confirmed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Xoá", parent)
        self._armed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26)
        self._timer = QTimer(self, singleShot=True, interval=3000)
        self._timer.timeout.connect(self._disarm)
        self.clicked.connect(self._on_click)
        self._style()

    @property
    def armed(self) -> bool:
        return self._armed

    def _on_click(self) -> None:
        if self._armed:
            self._timer.stop()
            self.confirmed.emit()
            return
        self._armed = True
        self.setText("Xoá?")
        self._style()
        self._timer.start()

    def _disarm(self) -> None:
        self._armed = False
        self.setText("Xoá")
        self._style()

    def _style(self) -> None:
        p = get_theme().palette
        if self._armed:
            css = (f"background: {p.danger}; color: {p.accent_on}; border: none;")
        else:
            css = (f"background: transparent; color: {p.text_3}; "
                   f"border: 1px solid {p.border_2};")
        self.setStyleSheet(f"QPushButton {{ {css} border-radius: 6px; padding: 0 9px; "
                           f"font-size: 11px; }}")


class _Row(QFrame):
    """One saved word. Clicking anywhere except the buttons opens the word."""

    clicked = Signal(str)

    def __init__(self, entry: VocabEntry) -> None:
        super().__init__()
        self.entry = entry
        self.haystack = fold(" ".join((entry.word, entry.pinyin, entry.hanviet,
                                       entry.meaning, entry.example)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.entry.word)
        super().mouseReleaseEvent(event)


class VocabWindow(QWidget):
    speak_requested = Signal(str)
    open_word_requested = Signal(str)

    def __init__(self, store: VocabStore, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._glass = Glass(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(480, 620)
        self._store = store
        self._rows: list[_Row] = []
        self._queue: list[VocabEntry] = []
        self._idx = 0
        self._revealed = False

        self._root = QWidget(self)
        self._root.setObjectName("vocabRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._root)
        root = QVBoxLayout(self._root)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._titlebar = CustomTitlebar("Sổ từ", show_minimize=False, show_maximize=False)
        self._titlebar.close_requested.connect(self.hide)
        root.addWidget(self._titlebar)

        self._tabs = Segmented([("list", "edit", "Danh sách", "Từ đã lưu"),
                                ("review", "brain", "Ôn tập", "Thẻ đến hạn")])
        self._tabs.value_changed.connect(self._on_tab)
        tabs_wrap = QHBoxLayout()
        tabs_wrap.setContentsMargins(12, 8, 12, 6)
        tabs_wrap.addWidget(self._tabs)
        root.addLayout(tabs_wrap)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_list_page())
        self._stack.addWidget(self._build_review_page())
        root.addWidget(self._stack, stretch=1)

        get_theme().mode_changed.connect(lambda _p: self._apply_style())
        self._apply_style()

    # ── Public ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._reload_list()
        self._update_due_label()
        if self._tabs.value() == "review":
            self._start_review()

    def open_list(self) -> None:
        self._tabs.setValue("list")
        self._stack.setCurrentIndex(0)
        self._show()

    def open_review(self) -> None:
        self._tabs.setValue("review")
        self._stack.setCurrentIndex(1)
        self._show()

    # ── List page ────────────────────────────────────────────────────────────

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Tìm từ, pinyin, Hán-Việt, nghĩa…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        s_wrap = QHBoxLayout()
        s_wrap.setContentsMargins(12, 4, 12, 8)
        s_wrap.addWidget(self._search)
        lay.addLayout(s_wrap)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list = QWidget()
        self._list.setObjectName("vocabList")
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(12, 2, 12, 8)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list)
        lay.addWidget(self._scroll, stretch=1)

        self._empty = QLabel("")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._list_layout.insertWidget(0, self._empty)

        foot = QHBoxLayout()
        foot.setContentsMargins(16, 8, 12, 12)
        foot.setSpacing(8)
        foot_left = QVBoxLayout()
        foot_left.setSpacing(0)
        self._count_label = QLabel("")
        self._status_label = QLabel("")
        foot_left.addWidget(self._count_label)
        foot_left.addWidget(self._status_label)
        foot.addLayout(foot_left, stretch=1)
        self._export_btn = QPushButton("Xuất Anki…")
        self._export_btn.clicked.connect(self._on_export)
        self._review_now_btn = QPushButton("Ôn tập ngay")
        self._review_now_btn.clicked.connect(self.open_review)
        foot.addWidget(self._export_btn)
        foot.addWidget(self._review_now_btn)
        lay.addLayout(foot)
        return page

    def _reload_list(self) -> None:
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.hide()  # deleteLater may wait a while; don't paint stale rows meanwhile
            row.deleteLater()
        self._rows = []
        now = int(time.time())
        for i, e in enumerate(self._store.all()):
            row = self._make_row(e, now)
            self._rows.append(row)
            self._list_layout.insertWidget(i, row)
        self._count_label.setText(f"{len(self._rows)} từ")
        self._apply_filter()

    def _make_row(self, e: VocabEntry, now: int) -> _Row:
        p = get_theme().palette
        row = _Row(e)
        row.setObjectName("vocabRow")
        row.clicked.connect(self.open_word_requested)
        lay = QVBoxLayout(row)
        lay.setContentsMargins(12, 8, 8, 10)
        lay.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(8)
        word = QLabel(e.word)
        word.setStyleSheet(f"color: {p.text_1}; font-size: 22px; font-weight: 600;")
        head.addWidget(word, alignment=Qt.AlignmentFlag.AlignBottom)
        sub = QVBoxLayout()
        sub.setSpacing(0)
        if e.pinyin:
            py = QLabel(e.pinyin)
            py.setStyleSheet(f"color: {p.accent}; font-size: 13px;")
            sub.addWidget(py)
        if e.hanviet:
            hv = QLabel(e.hanviet.upper())
            hv.setStyleSheet(f"color: {p.text_3}; font-size: 10px; letter-spacing: 1px;")
            sub.addWidget(hv)
        head.addLayout(sub)
        head.addStretch(1)
        speak = IconButton("volume", size=26, icon_size=13, tooltip="Phát âm")
        speak.clicked.connect(lambda _=False, w=e.word: self.speak_requested.emit(w))
        head.addWidget(speak, alignment=Qt.AlignmentFlag.AlignTop)
        delete = _ConfirmDeleteButton()
        delete.setObjectName("deleteBtn")
        delete.confirmed.connect(lambda w=e.word: self._on_delete(w))
        head.addWidget(delete, alignment=Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        if e.meaning:
            meaning = _ElidedLabel(e.meaning)
            meaning.setStyleSheet(f"color: {p.text_1}; font-size: 13px;")
            lay.addWidget(meaning)
        if e.example:
            ex = QLabel(e.example)
            ex.setWordWrap(True)
            ex.setStyleSheet(f"color: {p.text_3}; font-size: 12px;")
            lay.addWidget(ex)
        due = QLabel(f"Ôn lại: {fmt_due(e.due_at, now)}")
        due.setStyleSheet(f"color: {p.text_mute}; font-size: 10.5px;")
        lay.addWidget(due)

        row.setStyleSheet(
            f"QFrame#vocabRow {{ background: {p.glass_1}; border: 1px solid {p.border_1}; "
            f"border-radius: 10px; }}"
            f"QFrame#vocabRow:hover {{ border-color: {p.border_strong}; }}"
        )
        return row

    def _apply_filter(self) -> None:
        q = fold(self._search.text().strip())
        shown = 0
        for row in self._rows:
            vis = not q or q in row.haystack
            row.setVisible(vis)
            shown += vis
        if not self._rows:
            self._empty.setText("Chưa có từ nào. Lưu từ từ thẻ tra từ để bắt đầu.")
        elif not shown:
            self._empty.setText("Không tìm thấy từ phù hợp.")
        self._empty.setVisible(shown == 0)

    def _on_delete(self, word: str) -> None:
        self._store.remove(word)
        self._status_label.setText(f"Đã xoá “{word}”")
        # Defer: the clicked button lives inside the row being destroyed.
        QTimer.singleShot(0, self.refresh)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất sang Anki", str(Path.home() / "transsnip-vocab.txt"),
            "Tệp văn bản (*.txt)")
        if not path:
            return
        try:
            n = self._store.export_anki_tsv(Path(path))
        except OSError as exc:
            self._status_label.setText(f"Lỗi khi xuất: {exc}")
            return
        self._status_label.setText(f"Đã xuất {n} thẻ → {Path(path).name}")

    # ── Review page ──────────────────────────────────────────────────────────

    def _build_review_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 4, 16, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self._progress = QLabel("")
        top.addWidget(self._progress)
        top.addStretch(1)
        self._card_speak = IconButton("volume", size=30, icon_size=15, tooltip="Phát âm")
        self._card_speak.clicked.connect(self._speak_current)
        top.addWidget(self._card_speak)
        lay.addLayout(top)

        self._card = QFrame()
        self._card.setObjectName("vocabCard")
        card = QVBoxLayout(self._card)
        card.setContentsMargins(20, 24, 20, 20)
        card.setSpacing(6)
        self._c_word = QLabel("")
        self._c_word.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._c_word.setWordWrap(True)
        self._c_pinyin = QLabel("")
        self._c_hanviet = QLabel("")
        self._c_meaning = QLabel("")
        self._c_example = QLabel("")
        self._c_example_vi = QLabel("")
        card.addStretch(1)
        card.addWidget(self._c_word)
        for w in (self._c_pinyin, self._c_hanviet, self._c_meaning,
                  self._c_example, self._c_example_vi):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.setWordWrap(True)
            card.addWidget(w)
        card.addStretch(1)
        lay.addWidget(self._card, stretch=1)

        self._reveal_btn = QPushButton("Hiện đáp án  (Space)")
        self._reveal_btn.setMinimumHeight(40)
        self._reveal_btn.clicked.connect(self._reveal)
        lay.addWidget(self._reveal_btn)

        grades = QHBoxLayout()
        grades.setSpacing(8)
        self._grade_btns: dict[str, QPushButton] = {}
        for i, g in enumerate(GRADES, start=1):
            btn = QPushButton()
            btn.setMinimumHeight(48)
            btn.setToolTip(f"Phím {i}")
            btn.clicked.connect(lambda _=False, gr=g: self._grade(gr))
            self._grade_btns[g] = btn
            grades.addWidget(btn)
        self._grades_wrap = QWidget()
        self._grades_wrap.setLayout(grades)
        grades.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._grades_wrap)
        return page

    def _start_review(self) -> None:
        self._queue = self._store.due()
        self._idx = 0
        self._show_card()

    def _current(self) -> VocabEntry | None:
        return self._queue[self._idx] if self._idx < len(self._queue) else None

    def _show_card(self) -> None:
        e = self._current()
        self._revealed = False
        if e is None:
            self._show_done()
            return
        self._progress.setText(f"{self._idx + 1}/{len(self._queue)}")
        self._card_speak.setVisible(True)
        self._c_word.setText(e.word)
        self._c_pinyin.setText(e.pinyin)
        self._c_hanviet.setText(e.hanviet.upper())
        self._c_meaning.setText(e.meaning)
        self._c_example.setText(e.example)
        self._c_example_vi.setText(e.example_vi)
        self._set_answer_visible(False)
        self._reveal_btn.setVisible(True)
        self._grades_wrap.setVisible(False)

    def _show_done(self) -> None:
        self._progress.setText("")
        self._card_speak.setVisible(False)
        self._c_word.setText("Hết từ cần ôn 🎉")
        entries = self._store.all()
        if entries:
            nxt = min(e.due_at for e in entries)
            self._c_meaning.setText(f"Lần ôn tiếp theo: {fmt_due(nxt)}")
        else:
            self._c_meaning.setText("Sổ từ đang trống.")
        self._set_answer_visible(False)
        self._c_meaning.setVisible(True)
        self._reveal_btn.setVisible(False)
        self._grades_wrap.setVisible(False)
        self._update_due_label()

    def _set_answer_visible(self, on: bool) -> None:
        for w in (self._c_pinyin, self._c_hanviet, self._c_meaning,
                  self._c_example, self._c_example_vi):
            w.setVisible(on and bool(w.text()))

    def _reveal(self) -> None:
        e = self._current()
        if e is None or self._revealed:
            return
        self._revealed = True
        self._set_answer_visible(True)
        self._reveal_btn.setVisible(False)
        now = int(time.time())
        for g, btn in self._grade_btns.items():
            nxt = schedule(e, g, now)
            btn.setText(f"{_GRADE_LABELS[g]}\n{fmt_interval(nxt.due_at - now)}")
        self._grades_wrap.setVisible(True)

    def _grade(self, grade: str) -> None:
        e = self._current()
        if e is None or not self._revealed:
            return
        self._store.answer(e, grade)
        self._idx += 1
        self._show_card()
        self._update_due_label()

    def _speak_current(self) -> None:
        e = self._current()
        if e is not None:
            self.speak_requested.emit(e.word)

    def _update_due_label(self) -> None:
        n = len(self._store.due())
        btn = self._tabs._buttons.get("review")  # Segmented has no label setter
        if btn is not None:
            labels = [lb for lb in btn.findChildren(QLabel) if lb.text()]
            if labels:
                labels[0].setText(f"Ôn tập ({n})")
        self._review_now_btn.setEnabled(n > 0)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._stack.currentIndex() == 1:
            key = event.key()
            if key == Qt.Key.Key_Space:
                self._reveal()
                return
            keys = (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4)
            if key in keys:
                self._grade(GRADES[keys.index(key)])
                return
        super().keyPressEvent(event)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _on_tab(self, tab: str) -> None:
        self._stack.setCurrentIndex(1 if tab == "review" else 0)
        if tab == "review":
            self._start_review()
            self.setFocus()  # so Space / 1-4 reach keyPressEvent
        else:
            self._reload_list()

    def _show(self) -> None:
        self.refresh()
        if not self.isVisible():
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                self.move(geo.center().x() - self.width() // 2,
                          geo.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        if self._stack.currentIndex() == 1:
            self.setFocus()

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._root.setStyleSheet(
            "QWidget#vocabRoot { background: transparent; }"
        )
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }"
                                   "QWidget#vocabList { background: transparent; }")
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {p.glass_2}; color: {p.text_1}; "
            f"border: 1px solid {p.border_2}; border-radius: 8px; padding: 6px 10px; "
            f"font-size: 13px; }} QLineEdit:focus {{ border-color: {p.accent}; }}")
        self._count_label.setStyleSheet(f"color: {p.text_2}; font-size: 12px;")
        self._status_label.setStyleSheet(f"color: {p.text_3}; font-size: 11px;")
        self._empty.setStyleSheet(f"color: {p.text_3}; padding: 40px;")
        secondary = (f"QPushButton {{ background: {p.glass_2}; color: {p.text_1}; "
                     f"border: 1px solid {p.border_2}; border-radius: 8px; padding: 6px 12px; }}"
                     f"QPushButton:hover {{ border-color: {p.border_strong}; }}")
        primary = (f"QPushButton {{ background: {p.accent}; color: {p.accent_on}; border: none; "
                   f"border-radius: 8px; padding: 6px 12px; font-weight: 600; }}"
                   f"QPushButton:hover {{ background: {p.accent_hover}; }}"
                   f"QPushButton:disabled {{ background: {p.glass_1}; color: {p.text_mute}; }}")
        self._export_btn.setStyleSheet(secondary)
        self._review_now_btn.setStyleSheet(primary)
        self._reveal_btn.setStyleSheet(primary)
        self._progress.setStyleSheet(f"color: {p.text_2}; font-size: 12px;")
        self._card.setStyleSheet(
            f"QFrame#vocabCard {{ background: {p.glass_1}; border: 1px solid {p.border_1}; "
            f"border-radius: 14px; }}")
        self._c_word.setStyleSheet(f"color: {p.text_1}; font-size: 44px; font-weight: 600;")
        self._c_pinyin.setStyleSheet(f"color: {p.accent}; font-size: 18px;")
        self._c_hanviet.setStyleSheet(f"color: {p.text_3}; font-size: 11px; letter-spacing: 1px;")
        self._c_meaning.setStyleSheet(f"color: {p.text_1}; font-size: 15px; padding-top: 6px;")
        self._c_example.setStyleSheet(f"color: {p.text_2}; font-size: 14px; padding-top: 8px;")
        self._c_example_vi.setStyleSheet(f"color: {p.text_3}; font-size: 12px;")
        tints = {"again": p.danger, "hard": p.warning, "good": p.success, "easy": p.accent}
        for g, btn in self._grade_btns.items():
            btn.setStyleSheet(
                f"QPushButton {{ background: {p.glass_2}; color: {tints[g]}; "
                f"border: 1px solid {p.border_2}; border-radius: 8px; font-weight: 600; }}"
                f"QPushButton:hover {{ border-color: {tints[g]}; }}")
        self._reload_list()  # rows bake palette colours in


class _ElidedLabel(QLabel):
    """One-line label that elides with "…" to the available width."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._full = text
        self.setToolTip(text)
        # Ignored width: the long full text must not stretch the row.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def resizeEvent(self, event) -> None:
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, self.width()))
        super().resizeEvent(event)
