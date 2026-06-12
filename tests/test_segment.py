"""segment_english_runon — splits real run-ons, leaves words/IDs intact."""
import pytest

from transsnip.ocr.segment import segment_english_runon


def test_random_id_is_preserved():
    out = segment_english_runon("Track / XRCCN8DFDZKMUXBJ")
    assert "XRCCN8DFDZKMUXBJ" in out  # ID must not be shredded into fragments


def test_single_long_word_not_oversplit():
    # "Disassembler" is 12 chars (hits the run-on threshold) but is one real
    # word — must not become "Disassemble r".
    assert segment_english_runon("Bytecode to Opcode Disassembler") \
        == "Bytecode to Opcode Disassembler"


def test_genuine_camel_runon_is_split():
    # This is the only case that actually depends on wordninja being installed;
    # skip (don't fail) if the optional dep is missing in this environment.
    pytest.importorskip("wordninja")
    assert segment_english_runon("OpeningTitle") == "Opening Title"


def test_normal_spaced_text_unchanged():
    s = "This is a normal sentence already spaced."
    assert segment_english_runon(s) == s


def test_idempotent():
    once = segment_english_runon("OpeningTitle")
    assert segment_english_runon(once) == once
