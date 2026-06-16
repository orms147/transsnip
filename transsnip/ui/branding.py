"""App logo/icon resolution — single source of truth for the brand mark.

The logo lives at `assets/TransSnip.ico` (repo root in dev, `sys._MEIPASS/assets`
when frozen by PyInstaller — mirrors the resource-path pattern in
`transsnip/ocr/models.py`). Every surface that shows the app icon — the EXE icon
(via the .spec), the taskbar/window icon (QApplication.setWindowIcon), the tray
icon, the popup header glyph, and the About dialog — loads it from here.

All accessors degrade gracefully: if the .ico is missing (e.g. a partial dev
checkout), `app_qicon()` returns a null QIcon / `app_pixmap()` an empty pixmap,
and callers fall back to the procedural monogram so the app never crashes or
shows a broken-image box.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

_ICON_NAME = "TransSnip.ico"


def app_icon_path() -> Path:
    """Absolute path to the bundled app .ico (frozen-aware)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets" / _ICON_NAME
    # ui/branding.py → ui → transsnip → <repo root>
    return Path(__file__).resolve().parents[2] / "assets" / _ICON_NAME


def has_app_icon() -> bool:
    return app_icon_path().exists()


@lru_cache(maxsize=1)
def app_qicon() -> QIcon:
    """The app QIcon (multi-size from the .ico), or a null QIcon if absent.

    Cached — must be called after QApplication exists.
    """
    path = app_icon_path()
    return QIcon(str(path)) if path.exists() else QIcon()


def app_pixmap(size: int) -> QPixmap:
    """Best pixmap from the .ico at `size`px square; empty pixmap if no icon."""
    icon = app_qicon()
    return icon.pixmap(size, size) if not icon.isNull() else QPixmap()
