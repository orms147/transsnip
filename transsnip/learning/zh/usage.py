"""AI-written usage notes for a Chinese word (word card → "Giải thích cách dùng").

On demand only (the user presses the button): one LLM call with the word and
the sentence it was snipped from returns a short Vietnamese explanation,
grammar notes, example sentences (hanzi + pinyin + Vietnamese), common
collocations and easily-confused words. Results are cached on disk per
(word, sentence-context, model) so a word costs at most one call.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field

from transsnip.translate.prompts import parse_json_object
from transsnip.utils.paths import app_data_dir

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a patient Chinese teacher for Vietnamese learners. "
    "Reply with ONE JSON object only — no markdown fences, no commentary."
)


def build_prompt(word: str, sentence: str) -> str:
    return "\n".join([
        f"Explain how the Chinese word「{word}」is used, for a Vietnamese learner.",
        f"It appeared in this sentence: 「{sentence}」" if sentence and sentence != word else "",
        "",
        "Return JSON with exactly these keys (all text in Vietnamese except Chinese/pinyin):",
        '{"meaning_here": "<its meaning in the sentence above, or the main meaning>",',
        ' "explanation": "<2-3 sentences: what it means, register, when to use it>",',
        ' "grammar": ["<short usage/grammar pattern, e.g. 在…实习>", "..."],',
        ' "examples": [{"zh": "<natural sentence>", "pinyin": "<pinyin with tone marks>",',
        '               "vi": "<Vietnamese translation>"}],   // exactly 3, simple to medium',
        ' "collocations": ["<common word combination with it>", "..."],',
        ' "confusables": [{"word": "<similar word>", "difference": "<how it differs>"}]}',
    ])


@dataclass(frozen=True)
class Example:
    zh: str
    pinyin: str = ""
    vi: str = ""


@dataclass(frozen=True)
class UsageNote:
    word: str
    meaning_here: str = ""
    explanation: str = ""
    grammar: tuple[str, ...] = ()
    examples: tuple[Example, ...] = ()
    collocations: tuple[str, ...] = ()
    confusables: tuple[tuple[str, str], ...] = field(default=())


def parse(word: str, raw: str) -> UsageNote:
    """Model reply → UsageNote. Raises ValueError if it isn't the JSON asked for."""
    data = parse_json_object(raw)
    if data is None:
        raise ValueError("model did not return JSON")

    def strs(key: str) -> tuple[str, ...]:
        return tuple(str(x).strip() for x in data.get(key) or [] if str(x).strip())

    examples = tuple(
        Example(str(e.get("zh", "")).strip(), str(e.get("pinyin", "")).strip(),
                str(e.get("vi", "")).strip())
        for e in data.get("examples") or [] if isinstance(e, dict) and e.get("zh")
    )
    confusables = tuple(
        (str(c.get("word", "")).strip(), str(c.get("difference", "")).strip())
        for c in data.get("confusables") or [] if isinstance(c, dict) and c.get("word")
    )
    return UsageNote(
        word=word,
        meaning_here=str(data.get("meaning_here", "")).strip(),
        explanation=str(data.get("explanation", "")).strip(),
        grammar=strs("grammar"),
        examples=examples,
        collocations=strs("collocations"),
        confusables=confusables,
    )


def _cache_path(word: str, sentence: str, model_id: str):
    key = hashlib.sha256(f"v1|{model_id}|{word}|{sentence}".encode()).hexdigest()[:32]
    return app_data_dir("zh-usage") / f"{key}.json"


def explain(translator, word: str, sentence: str = "") -> UsageNote:
    """Ask the active LLM translator (cached). Blocking — call off the GUI thread.

    `translator` must be an LLMTranslator (has `_call` + `cache_id`); the UI
    disables the button for non-LLM providers such as Google free.
    """
    path = _cache_path(word, sentence, translator.cache_id)
    if path.exists():
        try:
            return parse(word, path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
    raw = translator._call(SYSTEM_PROMPT, build_prompt(word, sentence))
    note = parse(word, raw)               # raises before caching a bad reply
    try:
        path.write_text(json.dumps(parse_json_object(raw), ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.debug("usage cache write failed: %s", exc)
    return note
