"""SearchCombo: accent-insensitive ranked search that never shows a stale value."""
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from transsnip.ui.search_combo import SearchCombo, fold

MODELS = [
    ("Google: Gemma 4 31B (free)", "google/gemma-4-31b-it:free"),
    ("Qwen: Qwen3.7 Flash · $0.03/$0.13", "qwen/qwen3.7-flash"),
    ("DeepSeek: DeepSeek V4.1 Flash · $0.15/$0.6", "deepseek/deepseek-v4.1-flash"),
    ("Tencent: Hy-MT2 30B · $0.074/$0.295", "tencent/hy-mt2-30b-a3b"),
]


@pytest.fixture
def combo(qapp):
    c = SearchCombo()
    for label, data in [*MODELS, ("Tiếng Việt", "vi"), ("Japanese (日本語)", "ja")]:
        c.addItem(label, data)
    c.setCurrentIndex(0)
    return c


def _type(c: SearchCombo, text: str) -> list[str]:
    c.lineEdit().setText(text)
    c.lineEdit().textEdited.emit(text)
    f = c._filter
    return [f.index(r, 0).data() for r in range(f.rowCount())]


def test_fold_strips_accents_and_case():
    assert fold("Tiếng Việt ĐẸP") == "tieng viet dep"


def test_accent_insensitive_and_id_search(combo):
    assert _type(combo, "viet") == ["Tiếng Việt"]
    assert _type(combo, "ja") == ["Japanese (日本語)"]        # by code (exact id ranks first)
    assert _type(combo, "hy-mt2")[0].startswith("Tencent")       # by id


def test_all_words_must_match_and_ranking(combo):
    assert _type(combo, "deep flash") == ["DeepSeek: DeepSeek V4.1 Flash · $0.15/$0.6"]
    ranked = _type(combo, "flash")
    assert set(ranked) == {MODELS[1][0], MODELS[2][0]}


def test_enter_picks_top_match(combo):
    _type(combo, "qwen flash")
    combo.lineEdit().returnPressed.emit()
    assert combo.currentData() == "qwen/qwen3.7-flash"
    assert combo.lineEdit().text() == combo.itemText(combo.currentIndex())


def test_no_match_flags_field_and_leaving_restores_value(combo, qapp):
    assert _type(combo, "zzz-nothing") == []
    assert combo.property("nomatch") is True
    combo._show_current()                     # what focus-out ends in
    assert combo.lineEdit().text() == MODELS[0][0]
    assert combo.property("nomatch") is False


def test_escape_restores_current_text(combo):
    _type(combo, "qwe")
    combo._completer.popup().hide()          # first Esc closes the popup
    esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    combo.eventFilter(combo.lineEdit(), esc)
    assert combo.lineEdit().text() == MODELS[0][0]
