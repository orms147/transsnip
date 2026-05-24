from __future__ import annotations

import logging

import mss
from PIL import Image
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

log = logging.getLogger(__name__)


def _device_pixel_ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def capture_rect(rect: QRect, *, dpr: float | None = None) -> Image.Image:
    """Capture a screen region into a PIL RGB image.

    `rect` is in Qt logical (global) coordinates. Windows reports physical pixels
    through `mss`, so we scale by `devicePixelRatio` — without this, captures on
    125% / 150% / 175% scaling come out offset and clipped.
    """
    if dpr is None:
        dpr = _device_pixel_ratio()
    monitor = {
        "left": int(rect.x() * dpr),
        "top": int(rect.y() * dpr),
        "width": int(rect.width() * dpr),
        "height": int(rect.height() * dpr),
    }
    log.debug("Capturing %s (dpr=%.2f) -> monitor=%s", rect, dpr, monitor)
    with mss.mss() as sct:
        raw = sct.grab(monitor)
        return Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)
