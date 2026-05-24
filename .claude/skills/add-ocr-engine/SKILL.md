---
name: add-ocr-engine
description: Use this skill when the user asks to add a new OCR engine to TransSnip (e.g., "add OCR X", "thêm Tesseract", "support Google Vision OCR"). Walks through subclassing the OCREngine ABC, language support matrix, fallback chain integration, and tests.
---

# Add a new OCR engine

Use this skill when extending [transsnip/ocr/](../../../transsnip/ocr/) with a new OCR backend.

## Steps

1. **Create engine module** `transsnip/ocr/<engine_name>.py`:
   - Subclass `OCREngine` from [base.py](../../../transsnip/ocr/base.py)
   - Implement `recognize(image: PIL.Image, lang: str) -> OCRResult` returning blocks with bounding boxes (needed for inline overlay positioning)
   - Implement `supported_languages() -> set[str]` (returns BCP-47 codes like `en`, `ja`, `vi`, `zh-Hans`)
   - Implement `is_available() -> bool` (vd Windows OCR check Windows version; PaddleOCR check model files exist)

2. **Image preprocessing**:
   - Reuse helpers in [transsnip/utils/image.py](../../../transsnip/utils/image.py): grayscale, contrast boost, denoise
   - Different engines prefer different inputs — document what works best in module docstring

3. **Register in registry** `transsnip/ocr/registry.py`:
   - Add to `ENGINES` list with priority (lower = tried first in fallback chain)
   - Default: Windows OCR priority 0, PaddleOCR priority 10, cloud OCR priority 20

4. **Fallback logic**:
   - `OCRPipeline.recognize()` thử engines theo priority. Engine skip nếu `lang` không trong `supported_languages()` hoặc `is_available()` False
   - Nếu engine raise exception → log warning, thử engine kế tiếp
   - Nếu confidence < threshold → có thể thử engine kế tiếp (cấu hình trong settings)

5. **Test** `tests/ocr/test_<engine_name>.py`:
   - Test fixture images trong `tests/fixtures/ocr/` (English, Vietnamese, Japanese samples)
   - Assert text accuracy bằng fuzzy match (Levenshtein ratio > 0.9)
   - Test bounding box trả về hợp lệ (within image bounds)

## Trap thường gặp

- PaddleOCR cold start chậm (~5s load model lần đầu) — phải lazy-load và show loading indicator
- Windows OCR chỉ work với image format cụ thể (BGRA) — convert trước khi gọi
- Cloud OCR cost cao nếu user dùng full-screen mode liên tục — phải có rate limit warning trong settings
- Bounding box coordinate system khác nhau giữa engines (top-left vs bottom-left origin) — chuẩn hóa trong OCRResult

## Verification

- [ ] `engine.is_available()` return đúng trên máy test
- [ ] Region select trên text English/Vietnamese/Japanese → engine mới đều OCR được (hoặc fallback sang engine khác đúng)
- [ ] Full-screen translate: bounding box render đúng vị trí trên overlay
- [ ] Test pass: `pytest tests/ocr/test_<engine_name>.py`
- [ ] Engine xuất hiện trong Settings → OCR engine dropdown với checkbox enable/disable
