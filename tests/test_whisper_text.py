"""Whisper post-processing: phantom-credit stripping, CJK joins, zh script."""
import pytest

from transsnip.asr.whisper import _join_segments, _strip_phantom_tail, _zh_converter


def test_phantom_credits_cut_from_the_tail_of_real_speech():
    # Real outputs from scripts/asr_bench.py on cut chunks.
    zh = "老板说,明天早日请不吝点赞,订阅、转发、打赏支持明镜与点点栏目"
    ja = "ありがとう! 本当にご視聴ありがとうございました。"
    assert _strip_phantom_tail(zh) == "老板说,明天早日"
    assert _strip_phantom_tail(ja) == "ありがとう! 本当に"
    assert _strip_phantom_tail("Okay. Thanks for watching!") == "Okay"


def test_normal_speech_untouched():
    for text in ("我们明天见。", "それ本当に言ってるの？", "Thanks for the help."):
        assert _strip_phantom_tail(text) == text


def test_segments_join_without_spaces_in_cjk():
    assert _join_segments(["我跟你说", "这件事"]) == "我跟你说这件事"
    assert _join_segments(["Hello", "world"]) == "Hello world"


def test_zh_script_follows_the_pinned_source_language():
    pytest.importorskip("zhconv")
    assert _zh_converter("zh-Hans")("我跟你說,這件事") == "我跟你说,这件事"
    assert _zh_converter("zh-Hant")("这个功能") == "這個功能"
    assert _zh_converter("ja") is None
    assert _zh_converter(None) is None
