"""frozen_crop_box — logical-global selection → crop box in the frozen frame.

The invariant that matters: the crop must contain the same pixels a LIVE
`capture_rect(sel_rect)` would have grabbed, including its scale-then-truncate
coordinate handling, or freeze-frame OCR would read shifted pixels on
125%/150% DPI setups.
"""
from PySide6.QtCore import QRect

from transsnip.capture.region_selector import frozen_crop_box


def test_dpr_1_basic():
    mon = QRect(0, 0, 1920, 1080)
    sel = QRect(100, 50, 400, 300)
    assert frozen_crop_box(mon, sel, 1.0, 1920, 1080) == (100, 50, 500, 350)


def test_dpr_150_matches_capture_rect_truncation():
    # capture_rect computes int(x * dpr) per GLOBAL coordinate; the crop
    # offset must be int(sel.x*dpr) - int(mon.x*dpr), not int((sel.x-mon.x)*dpr).
    mon = QRect(0, 0, 1280, 720)  # physical 1920x1080 at 1.5x
    sel = QRect(33, 21, 100, 50)
    box = frozen_crop_box(mon, sel, 1.5, 1920, 1080)
    assert box == (int(33 * 1.5), int(21 * 1.5), int(33 * 1.5) + 150, int(21 * 1.5) + 75)


def test_secondary_monitor_negative_origin():
    # A monitor left of the primary has negative global coords; the crop is
    # relative to ITS frame, so offsets must come out non-negative.
    mon = QRect(-1920, 0, 1920, 1080)
    sel = QRect(-1820, 100, 200, 100)
    assert frozen_crop_box(mon, sel, 1.0, 1920, 1080) == (100, 100, 300, 200)


def test_clamped_to_image_bounds():
    mon = QRect(0, 0, 1920, 1080)
    sel = QRect(1800, 1000, 400, 300)  # spills past bottom-right
    assert frozen_crop_box(mon, sel, 1.0, 1920, 1080) == (1800, 1000, 1920, 1080)


def test_selection_outside_monitor_returns_none():
    mon = QRect(0, 0, 1920, 1080)
    sel = QRect(2000, 1200, 100, 100)
    assert frozen_crop_box(mon, sel, 1.0, 1920, 1080) is None
