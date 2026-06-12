"""Learning-mode breakdown — prompt shape, JSON parsing, offline fallback."""
from transsnip.linguistic.word_breakdown import (
    build_breakdown_prompt,
    local_breakdown,
    parse_breakdown,
)
from transsnip.translate.base import TranslationContext


def test_prompt_requests_json_shape():
    ctx = TranslationContext(target_lang="vi", source_lang="en", want_word_breakdown=True)
    prompt = build_breakdown_prompt("Hello world", ctx)
    assert '"translation"' in prompt and '"words"' in prompt
    assert "Hello world" in prompt


def test_parse_fenced_json():
    raw = ('```json\n{"translation":"Xin chào","words":'
           '[{"token":"Hello","ipa":"h\\u0259\\u02c8lo\\u028a",'
           '"meaning":"xin chào","pos":"interjection"}]}\n```')
    translation, words = parse_breakdown(raw)
    assert translation == "Xin chào"
    assert len(words) == 1
    assert words[0].token == "Hello"
    assert words[0].meaning == "xin chào"
    assert words[0].pos == "interjection"


def test_parse_malformed_returns_empty():
    translation, words = parse_breakdown("not json at all")
    assert translation == "" and words == []


def test_parse_skips_blank_tokens():
    raw = '{"translation":"x","words":[{"token":"","meaning":"y"},{"token":"ok"}]}'
    _, words = parse_breakdown(raw)
    assert [w.token for w in words] == ["ok"]


def test_local_breakdown_attaches_ipa():
    words = local_breakdown("Hello world")
    assert [w.token for w in words] == ["Hello", "world"]
    assert all(w.meaning is None for w in words)  # non-LLM: IPA only, no meaning
