from transsnip.modes.fullscreen import build_numbered_batch, overlay_boxes, parse_numbered_batch
from transsnip.ocr.base import OCRBlock


def _blocks(*texts: str) -> list[OCRBlock]:
    return [OCRBlock(text=t, bbox=(10 * i, 20 * i, 100, 30)) for i, t in enumerate(texts)]


def test_build_numbered_batch() -> None:
    assert build_numbered_batch(_blocks("a", "b")) == "[1] a\n[2] b"


def test_parse_ignores_preface_and_maps_out_of_order() -> None:
    out = "Sure, here you go:\n[2] hai\n[1] một\n"
    assert parse_numbered_batch(out, 2) == ["một", "hai"]


def test_parse_missing_and_out_of_range_indices() -> None:
    assert parse_numbered_batch("[1] x [7] y", 3) == ["x", "", ""]


def test_overlay_boxes_scales_by_dpr_and_drops_empty() -> None:
    blocks = _blocks("a", "b")
    boxes = overlay_boxes(blocks, ["  A ", ""], dpr=2.0)
    assert boxes == [((0, 0, 50, 15), "A")]
