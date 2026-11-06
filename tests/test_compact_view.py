"""Compact reading view: long study text flows like prose, annotations on demand."""
from __future__ import annotations

import pytest

from transsnip.display.popup.chinese import ChineseSource
from transsnip.display.popup.compact import COMPACT_HAN_CHARS, CompactText
from transsnip.display.popup.phonetic import _PhoneticSource, _WordBreakdown
from transsnip.learning.zh import dictionary as zd
from transsnip.translate.base import WordInfo

needs_data = pytest.mark.skipif(not zd.available(),
                                reason="resources/zh/zh.sqlite not built")

LONG_ZH = "美国时间十月二十一日，人工智能创业公司发布了第一个模型。" * 3
SHORT_ZH = "实习不久，老董事长就遭到内鬼暗算。"


def test_compact_text_hover_and_click(qapp) -> None:
    t = CompactText()
    t.set_runs([("你好", "你好", "nǐ hǎo"), ("，", None, ""), ("世界", "世界", "")], size_pt=12)
    got: list[str] = []
    t.activated.connect(got.append)
    t._on_activate("w:1")
    t._on_activate("bogus")
    assert got == ["世界"]
    assert "你好" in t.text() and "w:0" in t.text()


@needs_data
def test_long_chinese_starts_compact_and_toggles(qapp) -> None:
    assert sum(1 for c in LONG_ZH if "㐀" <= c <= "鿿") > COMPACT_HAN_CHARS
    src = ChineseSource()
    assert src.set_text(LONG_ZH)
    assert src._compact and not src._toggle.isHidden()
    assert src._flow.count() == 0                     # no per-word cells
    clicked: list[tuple[str, str]] = []
    src.word_clicked.connect(lambda w, s: clicked.append((w, s)))
    src._compact_text._on_activate("w:0")
    # the card gets the word's own sentence, not the whole paragraph
    assert clicked and clicked[0][1] == LONG_ZH[:len(LONG_ZH) // 3]
    relayouts: list[bool] = []
    src.relayout.connect(lambda: relayouts.append(True))
    src._toggle.toggled.emit(False)                   # "Hiện chú thích từng từ"
    assert not src._compact and src._flow.count() > 0 and relayouts


@needs_data
def test_short_chinese_keeps_full_annotations(qapp) -> None:
    src = ChineseSource()
    assert src.set_text(SHORT_ZH)
    assert not src._compact and src._toggle.isHidden()
    assert src._flow.count() > 0


def test_long_english_ipa_is_compact(qapp) -> None:
    ph = _PhoneticSource()
    ph.set_text("word " * 40)
    assert ph._compact and ph._label.isHidden()
    ph.set_text("a short line")
    assert not ph._compact


def test_long_breakdown_is_compact(qapp) -> None:
    wb = _WordBreakdown()
    words = [WordInfo(token=f"w{i}", ipa="x", meaning="m") for i in range(30)]
    wb.set_words(words)
    assert wb._compact and "w29" in wb._compact_text.text()
    wb.set_words(words[:5])
    assert not wb._compact
