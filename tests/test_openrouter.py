"""OpenRouter: reasoning is switched off for translation, with a fallback for
models that require it."""
from types import SimpleNamespace

from transsnip.translate.base import TranslationContext
from transsnip.translate.openrouter import OpenRouterTranslator


def _reply(text: str):
    msg = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


class _FakeCompletions:
    def __init__(self, reject_reasoning: bool) -> None:
        self.reject, self.calls = reject_reasoning, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject and "extra_body" in kwargs:
            raise RuntimeError("400: reasoning is mandatory for this model")
        return _reply("xin chào")


def _translator(reject: bool):
    t = OpenRouterTranslator(model="qwen/qwen3.7-flash", api_key="k")
    t._sdk_ok = True
    fake = _FakeCompletions(reject)
    t._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return t, fake


def test_reasoning_disabled_by_default():
    t, fake = _translator(reject=False)
    assert t.translate("hello", TranslationContext()).translated_text == "xin chào"
    assert fake.calls[0]["extra_body"] == {"reasoning": {"effort": "none"}}


def test_mandatory_reasoning_model_falls_back_and_remembers():
    t, fake = _translator(reject=True)
    assert t.translate("hello", TranslationContext()).translated_text == "xin chào"
    assert [("extra_body" in c) for c in fake.calls] == [True, False]
    t.translate("again", TranslationContext())
    assert "extra_body" not in fake.calls[-1]


def test_thinking_setting_reaches_the_translator_and_cache_identity():
    from transsnip.config.settings import Settings
    from transsnip.translate.registry import pipeline_from_settings

    s = Settings()
    s.translate.provider, s.translate.openrouter_model = "openrouter", "qwen/qwen3.7-flash"
    off = pipeline_from_settings(s)._translator
    s.translate.openrouter_thinking = True
    on = pipeline_from_settings(s)._translator
    assert (off._reasoning_off, on._reasoning_off) == (True, False)
    assert off.cache_id != on.cache_id
