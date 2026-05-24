---
name: test-mode-flow
description: Use this skill when testing or debugging a TransSnip mode end-to-end (e.g., "test region translate flow", "kiểm tra video subtitle mode chạy đúng không", "debug full-screen translate"). Explains how to launch dev mode, mock OCR/translate layers, capture logs, and verify each pipeline step.
---

# Test a TransSnip mode end-to-end

Use when you need to verify a complete flow: hotkey → capture → OCR → translate → display.

## Dev mode launch

Run app với debug logging:
```bash
TRANSSNIP_LOG_LEVEL=DEBUG python -m transsnip --dev
```

`--dev` flag bật:
- Settings window mở ngay (không chỉ tray)
- Log ra stdout (không chỉ file)
- Show debug overlay (vẽ bounding box OCR lên screenshot, save vào `%TEMP%\transsnip-dev\`)
- Disable cache (mỗi request mới)

## Mock layers cho test nhanh

Khi muốn test display/UX mà không tốn API call:

```python
# Set env vars trước khi launch
TRANSSNIP_MOCK_OCR=1      # OCR trả về text fixture từ tests/fixtures/ocr_mock.json
TRANSSNIP_MOCK_TRANSLATE=1 # Translate trả về "[MOCK] " + reversed text
```

Hoặc trong code, swap registry:
```python
from transsnip.translate.registry import use_mock_translator
use_mock_translator()
```

## Pipeline trace

Mỗi mode emit signal qua [transsnip/utils/telemetry.py](../../../transsnip/utils/telemetry.py). Bật trace:
```bash
TRANSSNIP_TRACE=1 python -m transsnip --dev
```

Output mẫu:
```
[T+0.000] hotkey.region_translate fired
[T+0.012] region_selector.show
[T+2.341] region_selector.selected rect=(120,340,800,420)
[T+2.343] capture.screen rect=... size=680x80 bytes=163200
[T+2.398] ocr.recognize engine=windows_ocr lang=en
[T+2.612] ocr.result text="Hello world" blocks=1
[T+2.613] translate.cache_miss key=sha256:abc123
[T+2.614] translate.request provider=claude model=claude-haiku-4-5
[T+3.012] translate.response tokens_in=42 tokens_out=18 latency=398ms
[T+3.014] display.floating_popup.show pos=(120,420)
```

Dùng trace để xác định step nào chậm hoặc fail.

## Per-mode verification

### Region translate
- [ ] Hotkey fire → region_selector.show trong <100ms
- [ ] Drag rectangle → selected rect đúng tọa độ (visual confirm bằng debug overlay)
- [ ] OCR result có text (không empty string)
- [ ] Translate response hợp lệ (không error)
- [ ] Popup hiện gần region, không bị clip ngoài màn hình
- [ ] Click ngoài popup → đóng
- [ ] Esc khi đang chọn region → cancel, không gọi OCR

### Full-screen translate
- [ ] Capture toàn screen đúng monitor active
- [ ] OCR trả về nhiều blocks với bounding box
- [ ] Mỗi block dịch xong → overlay render đè đúng vị trí (debug overlay vẽ box rõ ràng)
- [ ] Click vào overlay → có thể click-through xuống app gốc

### Video subtitle (Phase 2)
- [ ] Vẽ subtitle region → polling loop start
- [ ] Trace log "ssim.skip" khi frame giống nhau (pause video → toàn skip)
- [ ] Trace log "fuzzy.skip" khi OCR text giống lần trước
- [ ] Subtitle thay đổi → translation update trong <500ms
- [ ] Esc → loop stop, overlay biến mất

## Trap thường gặp

- Mock OCR trả text rỗng → translate fail silently. Mock luôn trả ít nhất 1 từ.
- Test trên monitor secondary nhưng debug overlay save screenshot của primary — verify `--monitor` flag.
- Hotkey không fire vì conflict với app khác (Photoshop, OBS) — đóng các app này khi test.
- Cache disabled trong dev mode nhưng cache vẫn hit nếu disk cache không clear — `rm -rf %APPDATA%/transsnip/cache` trước.
