---
name: debug-overlay
description: Use this skill when overlay/popup/transparent windows in TransSnip don't show, show at wrong position, are clipped, have wrong size on high-DPI displays, or behave incorrectly across multiple monitors. Provides a systematic checklist for diagnosing Qt overlay issues on Windows.
---

# Debug overlay rendering issues

Use when [floating_popup.py](../../../transsnip/display/floating_popup.py), [inline_overlay.py](../../../transsnip/display/inline_overlay.py), or [region_selector.py](../../../transsnip/capture/region_selector.py) has rendering problems.

## Systematic checklist

### 1. Window flags & attributes
Print window flags ngay sau khi tạo widget:
```python
print(f"flags: {bin(int(widget.windowFlags()))}")
print(f"WA_TranslucentBackground: {widget.testAttribute(Qt.WA_TranslucentBackground)}")
print(f"WA_NoSystemBackground: {widget.testAttribute(Qt.WA_NoSystemBackground)}")
```
Expected flags for transparent always-on-top overlay:
- `Qt.FramelessWindowHint`
- `Qt.WindowStaysOnTopHint`
- `Qt.Tool` (không hiện trong taskbar)
- `Qt.WA_TranslucentBackground = True`

### 2. DPI scaling
Windows high-DPI (125%, 150%, 175%) thường làm overlay sai vị trí. Kiểm tra:
```python
screen = QApplication.screenAt(global_point)
print(f"devicePixelRatio: {screen.devicePixelRatio()}")
print(f"logicalDotsPerInch: {screen.logicalDotsPerInch()}")
print(f"geometry: {screen.geometry()}, availableGeometry: {screen.availableGeometry()}")
```
Coordinate từ `mss` (physical pixels) và Qt (logical pixels) khác nhau — phải chia/nhân `devicePixelRatio`.

### 3. Multi-monitor
```python
for screen in QApplication.screens():
    print(f"{screen.name()}: {screen.geometry()}")
```
Test edge case: overlay trên monitor 2, primary monitor là 1, monitor 2 có scaling khác.

### 4. Z-order / always-on-top
Nếu overlay bị che bởi app khác (full-screen game, taskbar):
- Verify `Qt.WindowStaysOnTopHint` set
- Verify `widget.raise_()` và `widget.activateWindow()` được gọi sau show
- Một số game DirectX exclusive full-screen sẽ luôn che overlay — chỉ work với borderless windowed mode (document limitation)

### 5. Geometry & paint
- Geometry set TRƯỚC khi show? Hay sau? Set sau show có thể không apply ngay
- `paintEvent` được trigger? Add print trong paintEvent để xác nhận
- Background không transparent? Check stylesheet không có `background-color` solid

### 6. Click-through (cho inline overlay)
Inline overlay không nên ăn click chuột (user phải click được app gốc bên dưới):
- `Qt.WA_TransparentForMouseEvents = True`
- Hoặc dùng Win32 API: `SetWindowLong(hwnd, GWL_EXSTYLE, ... | WS_EX_TRANSPARENT | WS_EX_LAYERED)`

## Trap thường gặp

- Tạo overlay khi chưa có `QApplication` instance → silent fail
- Update overlay từ thread khác main → crash hoặc không render. Phải dùng `QMetaObject.invokeMethod` hoặc signal/slot
- Bounding box từ OCR tính theo image pixel, không phải screen pixel — phải offset thêm vị trí của capture region
- `widget.hide()` trên Windows giữ window trong taskbar nếu không có `Qt.Tool` flag

## Verification

- [ ] Overlay show đúng vị trí trên cả primary monitor và secondary monitor
- [ ] Test với DPI 100%, 125%, 150% — overlay không lệch
- [ ] Inline overlay không chặn click chuột vào app bên dưới
- [ ] Resize overlay smooth, không flicker
- [ ] Closing overlay không leak window handle (verify qua Task Manager)
