"""Chinese study: segmentation/pinyin, Hán-Việt, dictionary, popup block, word card."""
import json
import time

import pytest

from transsnip.learning.zh import dictionary as zd
from transsnip.learning.zh.text import tokenize

needs_data = pytest.mark.skipif(not zd.available(),
                                reason="run scripts/fetch_zh_data.py to build zh.sqlite")


def test_tokenize_pinyin_tones_and_polyphones():
    toks = {t.text: t for t in tokenize("董事长去长城银行")}
    assert toks["董事长"].pinyin == "dǒng shì zhǎng"
    assert toks["长城"].syllables[0].numbered == "chang2"
    assert toks["银行"].syllables[1].numbered == "hang2"
    assert [s.tone for s in toks["董事长"].syllables] == [3, 4, 3]


@needs_data
@pytest.mark.parametrize(("text", "expected"), [
    ("实习不久，老董事长就遭到内鬼暗算。",
     "thực tập bất cửu, lão đổng sự trưởng tựu tao đáo nội quỷ ám toán."),
    ("我们一起去长城吧", "ngã môn nhất khởi khứ trường thành ba"),
    ("效率很高，价格很便宜，办法很简单",
     "hiệu suất ngận cao, giá cách ngận tiện nghi, biện pháp ngận giản đơn"),
    ("银行", "ngân hàng"),
])
def test_sentence_hanviet(text, expected):
    assert zd.sentence_hanviet(tokenize(text)) == expected


@needs_data
def test_lookup_hsk_and_char_info():
    d = zd.shared()
    assert any("thực tập" in m for e in d.lookup("实习") for m in e.meanings)
    assert d.hsk_level("银行") == 2
    info = d.char_info(tokenize("好")[0].syllables[0])
    assert info.hanviet == "hảo" and info.radical == "女" and "子" in info.decomposition
    # Exact-case pinyin first: 董 "dong3" (common), not the "Dong3" surname entry.
    dong = d.char_info(tokenize("董")[0].syllables[0])
    assert not dong.meanings[0].startswith("họ")


@needs_data
def test_popup_chinese_block_emits_clicked_word(qapp):
    from transsnip.display.popup.chinese import ChineseSource

    w = ChineseSource()
    w.resize(420, 200)
    assert w.set_text("实习不久")
    got = []
    w.word_clicked.connect(lambda word, sentence: got.append((word, sentence)))
    cells = [w._flow.itemAt(i).widget() for i in range(w._flow.count())]
    assert [c._word for c in cells] == ["实习", "不久"]
    cells[0].clicked.emit(cells[0]._word)
    assert got == [("实习", "实习不久")]
    assert w.heightForWidth(420) > 0


@needs_data
def test_word_card_save_and_ai_usage(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from transsnip.learning.vocab import VocabStore
    from transsnip.translate.llm import LLMTranslator
    from transsnip.ui.word_card import WordCardWindow

    class FakeLLM(LLMTranslator):
        name, default_model, sdk_module, sdk_package = "fake", "m", "json", "json"

        def _complete(self, system, user):
            example = {"zh": "我在银行实习。", "pinyin": "wǒ zài yínháng shíxí",
                       "vi": "Tôi thực tập ở ngân hàng."}
            return json.dumps({"meaning_here": "thực tập", "explanation": "Chỉ việc thực tập.",
                               "examples": [example]})

    store = VocabStore(tmp_path / "v.sqlite3")
    card = WordCardWindow(store, lambda: FakeLLM(api_key="k"))
    card.show_word("实习", "实习不久", "Thực tập chưa lâu")
    assert "THỰC TẬP" in card._hv_lbl.text()
    card._on_save()
    (entry,) = store.all()
    assert entry.hanviet == "thực tập" and entry.example == "实习不久"
    assert card._save_btn.text().startswith("★")

    card._on_usage()
    deadline = time.monotonic() + 5
    while "银行实习" not in card._usage_lbl.text() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert "Tôi thực tập ở ngân hàng." in card._usage_lbl.text()
    card.hide()


def test_sentence_at_picks_the_words_sentence() -> None:
    from transsnip.learning.zh.text import sentence_at
    t = "美国时间10月21日，公司发布了模型。CEO写道：从零开始！他向Wired解释了原因"
    i = t.index("从零")
    assert sentence_at(t, i, i + 2) == "CEO写道：从零开始！"
    assert sentence_at(t, 0, 2) == "美国时间10月21日，公司发布了模型。"
    i = t.index("Wired")
    assert sentence_at(t, i, i + 5) == "他向Wired解释了原因"
