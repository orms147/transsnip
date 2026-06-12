"""OCR language routing — RapidOCR rec-model picker + pipeline lang match."""
from transsnip.ocr.models import rec_for_lang
from transsnip.ocr.registry import _lang_matches


def test_rec_for_lang_ch_family():
    # ch model spans Chinese + Japanese + English.
    assert rec_for_lang("ja").lang_type == "ch"
    assert rec_for_lang("zh-Hant").lang_type == "ch"
    assert rec_for_lang("en").lang_type == "ch"


def test_rec_for_lang_korean_latin():
    assert rec_for_lang("ko").lang_type == "korean"
    assert rec_for_lang("vi").lang_type == "latin"
    assert rec_for_lang("fr").lang_type == "latin"


def test_rec_for_lang_auto_defaults_ch():
    assert rec_for_lang(None).lang_type == "ch"
    assert rec_for_lang("unknown-xx").lang_type == "ch"


def test_lang_matches_primary_subtag():
    assert _lang_matches("en", {"en-US"}) is True
    assert _lang_matches("zh-Hans", {"zh-CN"}) is True   # match by primary "zh"
    assert _lang_matches("ja", {"ja"}) is True


def test_lang_matches_negative():
    assert _lang_matches("ko", {"en-US", "ja"}) is False
