"""Liquid-glass helper: token colours, theme toggle, painting without a compositor."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from transsnip.ui.glass import Glass
from transsnip.ui.theme import get_theme
from transsnip.ui.tokens import DARK, LIGHT, qcolor


def test_qcolor_parses_hex_and_rgba() -> None:
    assert qcolor("#131519").name() == "#131519"
    c = qcolor("rgba(255, 255, 255, 0.5)")
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (255, 255, 255, 128)


def test_glass_tokens_are_translucent() -> None:
    for pal in (DARK, LIGHT):
        for token in (pal.glass_1, pal.glass_2, pal.glass_3):
            assert 0 < qcolor(token).alpha() < 255


def test_set_glass_emits_mode_changed_once(qapp) -> None:
    theme = get_theme()
    seen: list[object] = []
    theme.mode_changed.connect(seen.append)
    try:
        theme.set_glass(False)
        theme.set_glass(False)          # no-op: unchanged
        assert not theme.glass
        assert len(seen) == 1
    finally:
        theme.set_glass(True)
        theme.mode_changed.disconnect(seen.append)


def test_glass_window_shows_and_paints_offscreen(qapp) -> None:
    win = QWidget(None, Qt.WindowType.FramelessWindowHint)
    win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    glass = Glass(win)
    area = QScrollArea(win)
    area.setWidget(QLabel("x"))
    QVBoxLayout(win).addWidget(area)
    assert area.widget().autoFillBackground()   # QScrollArea turns it on…
    win.resize(200, 120)
    win.show()
    win.grab()                                  # runs the Paint filter
    assert not area.widget().autoFillBackground()   # …Glass turns it off
    assert glass.blurred is False               # no compositor offscreen → opaque fallback
    win.close()
