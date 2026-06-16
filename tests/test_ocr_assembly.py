"""OCRResult.text — line grouping, CJK join, sentence-terminator paragraphs."""
from transsnip.ocr.base import OCRBlock, OCRResult, _join_blocks_smart


def test_cjk_join_no_space():
    # Adjacent CJK chars must not get a space between them.
    assert _join_blocks_smart(["世", "界"]) == "世界"


def test_latin_join_with_space():
    assert _join_blocks_smart(["Hello", "world"]) == "Hello world"


def test_single_line_words_join():
    blocks = [
        OCRBlock("Hello", (0, 0, 50, 20)),
        OCRBlock("world", (60, 0, 50, 20)),
    ]
    assert OCRResult("test", blocks).text == "Hello world"


def test_sentence_terminator_splits_paragraphs():
    # Two JP sentences each ending in 。 on closely-spaced lines → separate lines.
    blocks = [
        OCRBlock("こんにちは。", (0, 0, 100, 20)),
        OCRBlock("世界です。", (0, 30, 100, 20)),
    ]
    assert OCRResult("t", blocks).text == "こんにちは。\n世界です。"


def test_wrapped_sentence_merges():
    # A single sentence (no terminator on line 1) wrapping across two close
    # lines should merge into one paragraph.
    blocks = [
        OCRBlock("the quick brown", (0, 0, 100, 20)),
        OCRBlock("fox jumps", (0, 26, 100, 20)),
    ]
    assert "\n" not in OCRResult("t", blocks).text


def test_list_items_not_merged():
    # Two list items "a." / "b." on close lines (no 。 terminator) must NOT be
    # merged into one paragraph — the wrap-merge would otherwise collapse them.
    blocks = [
        OCRBlock("a. 進捗管理シートのURL", (0, 0, 200, 20)),
        OCRBlock("b. アプリが動作するURL", (0, 26, 200, 20)),
    ]
    out = OCRResult("t", blocks).text
    assert "\n" in out, out
    assert out.startswith("a.") and "b." in out.split("\n")[1]


def test_list_item_with_dropped_marker_not_merged():
    # Engine dropped "b." — the second line has no marker, but the PREVIOUS line
    # is a list item ("a. …"), so they still stay on separate lines.
    blocks = [
        OCRBlock("a. 進捗管理シートのURL", (0, 0, 200, 20)),
        OCRBlock("アプリが動作するURL", (0, 26, 200, 20)),  # marker dropped
    ]
    assert "\n" in OCRResult("t", blocks).text


def test_empty_result():
    assert OCRResult("t", []).text == ""
