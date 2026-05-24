---
name: translate-prompt-tuning
description: Use this skill when improving translation quality in TransSnip — adjusting LLM prompts, adding few-shot examples, integrating glossary, or A/B testing prompt variants. Covers prompt templates for Claude/OpenAI providers, JSON-structured output for Learning mode, and pitfalls.
---

# Tune translation prompts for quality

Use when bản dịch không tự nhiên, lệch context, hoặc Learning mode JSON output không stable.

## Prompt structure (Claude/OpenAI providers)

[transsnip/translate/claude.py](../../../transsnip/translate/claude.py) build prompt từ 3 thành phần:

```python
def build_prompt(text: str, ctx: TranslationContext) -> list[Message]:
    return [
        {"role": "system", "content": SYSTEM_TEMPLATE.format(
            target_lang=ctx.target_lang,
            preset_prompt=ctx.system_prompt or "",
            glossary=format_glossary(ctx.glossary),
            output_format=JSON_SCHEMA if ctx.want_word_breakdown else "plain"
        )},
        # Few-shot examples (optional, from preset)
        *ctx.few_shot_examples,
        {"role": "user", "content": text}
    ]
```

## Best practices

### 1. Glossary injection
- **Hard glossary** (force replace): Inject as system rule "ALWAYS translate X as Y". Risk: làm câu thiếu tự nhiên nếu context không phù hợp.
- **Soft glossary** (suggestion): "Prefer X for Y when meaning matches." LLM tự quyết. Tốt hơn cho ngôn ngữ tự nhiên.
- Format glossary thành table, KHÔNG dùng JSON inline (LLM hay nhầm với output format).

### 2. Few-shot examples
Mỗi context preset có thể đính kèm 2-3 ví dụ:
```python
few_shot = [
    {"role": "user", "content": "The DPS check is brutal."},
    {"role": "assistant", "content": "Pha check sát thương/giây này khoai vãi."},
]
```
- Examples phải MATCH domain (gaming examples cho gaming preset).
- Tránh examples quá generic ("Hello → Xin chào") — không dạy được LLM gì mới.

### 3. JSON output cho Learning mode
Khi `want_word_breakdown = True`, prompt yêu cầu JSON:
```
Respond with ONLY valid JSON, no markdown fences, matching this schema:
{
  "translation": "<full translation>",
  "words": [{"token": "<src word>", "ipa": "<IPA>", "meaning": "<word meaning in target lang>", "pos": "noun|verb|adj|..."}]
}
```
- Parse với `json.loads`, retry 1 lần nếu fail (LLM hay đính kèm ``` fence).
- Validate schema với Pydantic, log invalid → fallback plain translation.

### 4. Context-aware tone
Inject tone vào system prompt:
- Gaming: "Use casual Vietnamese, slang acceptable, keep English game terms"
- Programming: "Keep code identifiers in English, translate prose only"
- Medical: "Use formal Vietnamese, prefer Sino-Vietnamese medical terms"

## A/B testing flow

Khi tune prompt:
1. Tạo 2 variant của prompt template trong [transsnip/translate/prompts.py](../../../transsnip/translate/prompts.py)
2. Set `TRANSSNIP_PROMPT_VARIANT=B` env để switch
3. Dịch 10-20 text mẫu trong `tests/fixtures/translate_eval.txt`
4. Compare side-by-side, ghi nhận diff trong `docs/prompt-eval/`
5. Chọn winner, xóa variant kia

## Trap thường gặp

- Prompt quá dài → tốn token, latency tăng. Giữ system prompt < 300 token cho text ngắn.
- Glossary >50 entries trong prompt → LLM bỏ qua nhiều entry. Filter glossary theo text input (chỉ inject term có trong text).
- Few-shot examples bị cache với cache key cũ → user thấy bản dịch không update. Hash cả prompt template vào cache key.
- `temperature=0` cho translate → an toàn nhưng ít tự nhiên. Default `0.3` cho prose, `0` cho technical.

## Verification

- [ ] Dịch text gaming với "Gaming" preset → output có tone phù hợp (so với "Default" preset)
- [ ] Glossary term xuất hiện trong text → bản dịch dùng đúng glossary
- [ ] Learning mode → JSON parse được, mỗi word có đủ 4 field
- [ ] Cùng text dịch lần 2 → cache hit (verify log)
- [ ] Eval: 10 text fixture → tỷ lệ "ổn"/"tốt" >= 80% (đánh giá thủ công)
