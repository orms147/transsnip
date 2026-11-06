from __future__ import annotations

import time
from pathlib import Path

import pytest

from transsnip.learning.vocab import VocabEntry, VocabStore


@pytest.fixture
def store(tmp_path: Path) -> VocabStore:
    s = VocabStore(tmp_path / "vocab.sqlite3")
    s.add(VocabEntry(word="实习", pinyin="shíxí", hanviet="thực tập", meaning="thực tập",
                     example="我在公司实习。", example_vi="Tôi thực tập ở công ty."))
    s.add(VocabEntry(word="学习", pinyin="xuéxí", hanviet="học tập", meaning="học"))
    return s


@pytest.fixture
def win(qapp, store):
    from transsnip.ui.vocab_window import VocabWindow
    w = VocabWindow(store)
    w.refresh()
    yield w
    w.deleteLater()


def _visible_words(w) -> set[str]:
    return {r.entry.word for r in w._rows if not r.isHidden()}


def test_list_and_accent_insensitive_search(win):
    assert _visible_words(win) == {"实习", "学习"}
    win._search.setText("thuc tap")
    assert _visible_words(win) == {"实习"}
    win._search.setText("XUEXI")
    assert _visible_words(win) == {"学习"}


def test_delete_two_step(qapp, win, store):
    from transsnip.ui.vocab_window import _ConfirmDeleteButton
    row = next(r for r in win._rows if r.entry.word == "学习")
    btn = row.findChild(_ConfirmDeleteButton)
    btn.click()
    assert store.contains("学习") and btn.armed
    btn.click()
    assert not store.contains("学习")
    qapp.processEvents()
    assert {r.entry.word for r in win._rows} == {"实习"}


def test_review_flow(win, store):
    win.open_review()
    assert len(win._queue) == 2
    first = win._current()
    win._grade("good")  # ignored before reveal
    assert win._current() == first
    win._reveal()
    assert "1 ngày" in win._grade_btns["good"].text()
    win._grade("good")
    assert store.all()[0].due_at > time.time() or store.all()[1].due_at > time.time()
    assert first.word not in {e.word for e in store.due()}
    assert win._progress.text() == "2/2"
    win._reveal()
    win._grade("easy")
    assert win._current() is None
    assert "Hết từ cần ôn" in win._c_word.text()
    win.hide()


def test_anki_export(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    dest = tmp_path / "out.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(dest), "")))
    win._on_export()
    assert dest.exists() and "实习" in dest.read_text(encoding="utf-8")
    assert "2" in win._status_label.text()
