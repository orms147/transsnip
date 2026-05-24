---
name: add-translator-provider
description: Use this skill when the user asks to add a new translation provider to TransSnip (e.g., "add provider X", "thêm dịch giả X", "add DeepSeek translator"). Walks through the full integration: subclassing the Translator ABC, registry registration, settings UI field, API key handling via keyring, and tests.
---

# Add a new translation provider

Use this skill when extending [transsnip/translate/](../../../transsnip/translate/) with a new provider.

## Steps

1. **Create the provider module** `transsnip/translate/<provider_name>.py`:
   - Subclass `Translator` from [base.py](../../../transsnip/translate/base.py)
   - Implement `translate(text: str, context: TranslationContext) -> TranslationResult`
   - Honor `context.target_lang`, `context.system_prompt`, `context.glossary`
   - When `context.want_word_breakdown` is True, return populated `words: list[WordInfo]` (for LLM providers prompt for JSON output; for non-LLM, leave None)
   - Use `httpx` async client. Wrap network calls in try/except with retry/backoff (see [utils/retry.py](../../../transsnip/utils/retry.py) if exists)

2. **Register in registry** `transsnip/translate/registry.py`:
   - Add entry to `PROVIDERS` dict with metadata: `{name, display_name, requires_api_key, supports_context, supports_word_breakdown}`
   - The registry is the single source of truth — UI reads from it to populate dropdowns

3. **Add UI field** in [transsnip/ui/provider_tab.py](../../../transsnip/ui/provider_tab.py):
   - The tab auto-renders from registry metadata. Just ensure registry entry is correct
   - If provider needs custom config (model variant dropdown, endpoint URL), extend the metadata schema

4. **API key handling**:
   - NEVER store API keys in JSON config. Use [transsnip/config/keyring_store.py](../../../transsnip/config/keyring_store.py)
   - Service name pattern: `transsnip:<provider_name>`

5. **Test** in `tests/translate/test_<provider_name>.py`:
   - Use `respx` to mock HTTP calls
   - Test: basic translation, context injection, glossary application, error handling (rate limit, network fail), word breakdown when requested

## Trap thường gặp

- Forgetting to call `cache.get_or_compute()` wrapper — gây gọi API mỗi request kể cả khi text giống nhau
- LLM provider không validate JSON output — khi model trả invalid JSON cho word breakdown, app crash. Luôn try/except + fallback sang text-only translation
- Provider trả về bản dịch có markdown formatting (`**bold**`, ```code```) — strip trước khi render trong overlay

## Verification

- [ ] Provider xuất hiện trong dropdown ở Settings → Provider tab
- [ ] Nhập API key → lưu vào Windows Credential Manager (kiểm tra qua `keyring get transsnip:<name> apikey`)
- [ ] Region translate hoạt động với provider mới
- [ ] Bản dịch thứ 2 cùng text → lấy từ cache (verify qua log)
- [ ] Pytest pass: `pytest tests/translate/test_<provider_name>.py`
