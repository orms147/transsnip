import json

import pytest

from transsnip.translate.base import TranslationContext, TranslationError, TranslationResult
from transsnip.translate.cache import TranslationCache
from transsnip.translate.llm import LLMTranslator
from transsnip.translate.prompts import build_system_prompt, parse_json_object
from transsnip.translate.registry import TranslationPipeline


class _FakeLLM(LLMTranslator):
    name = "fake"
    default_model = "m1"
    sdk_module = "json"  # always importable
    sdk_package = "json"

    def __init__(self, reply: str | Exception = "xin chào", **kw) -> None:
        super().__init__(api_key="k", **kw)
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def _complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_plain_translation_uses_shared_system_prompt() -> None:
    llm = _FakeLLM()
    ctx = TranslationContext(target_lang="vi", glossary={"HP": "máu"})
    result = llm.translate("hello", ctx)
    assert result.translated_text == "xin chào"
    assert result.provider == "fake"
    system, user = llm.calls[0]
    assert system == build_system_prompt(ctx)
    assert "Vietnamese" in system and "HP → máu" in system
    assert user == "hello"


def test_breakdown_mode_parses_words() -> None:
    reply = json.dumps({"translation": "xin chào", "words": [{"token": "hello", "ipa": "x"}]})
    result = _FakeLLM(f"```json\n{reply}\n```").translate(
        "hello", TranslationContext(want_word_breakdown=True)
    )
    assert result.translated_text == "xin chào"
    assert result.words is not None and result.words[0].token == "hello"


def test_breakdown_mode_degrades_to_raw_text() -> None:
    result = _FakeLLM("not json").translate("hi", TranslationContext(want_word_breakdown=True))
    assert result.translated_text == "not json"
    assert result.words is None


def test_sdk_errors_are_wrapped() -> None:
    with pytest.raises(TranslationError, match="fake API call failed: boom"):
        _FakeLLM(RuntimeError("boom")).translate("x", TranslationContext())


def test_empty_reply_is_an_error() -> None:
    with pytest.raises(TranslationError, match="empty"):
        _FakeLLM("   ").translate("x", TranslationContext())


def test_missing_key_is_reported() -> None:
    llm = _FakeLLM()
    llm._api_key = None
    assert not llm.is_available()
    with pytest.raises(TranslationError, match="API key"):
        llm.translate("x", TranslationContext())


def test_cache_is_keyed_by_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cache = TranslationCache()
    ctx = TranslationContext()
    a = TranslationPipeline(_FakeLLM("from m1", model="m1"), cache)
    b = TranslationPipeline(_FakeLLM("from m2", model="m2"), cache)
    assert a.translate("x", ctx).translated_text == "from m1"
    second: TranslationResult = b.translate("x", ctx)
    assert second.translated_text == "from m2" and not second.cached
    assert a.translate("x", ctx).cached


def test_parse_json_object_rejects_non_objects() -> None:
    assert parse_json_object("[1, 2]") is None
    assert parse_json_object('{"a": 1}') == {"a": 1}
