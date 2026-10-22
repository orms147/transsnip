"""Popup pin: persists across snips; unpinned popups hide on a click outside."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QPoint, QRect

from transsnip.config.settings import Settings
from transsnip.display.popup import dismiss
from transsnip.display.popup.window import FloatingPopup

FAR = QPoint(-5000, -5000)       # nowhere near the popup


@pytest.fixture
def popup(qapp, monkeypatch):
    w = FloatingPopup()
    yield w
    w.hide_popup()
    w.deleteLater()


def _click_at(popup, monkeypatch, pos: QPoint, *, own_widget=None) -> None:
    """Drive one poll tick as if a mouse button just went down at `pos`."""
    monkeypatch.setattr(dismiss.QCursor, "pos", staticmethod(lambda: pos))
    monkeypatch.setattr(dismiss.QApplication, "widgetAt", staticmethod(lambda _p: own_widget))
    monkeypatch.setattr(type(popup), "_mouse_buttons_down", staticmethod(lambda: True))
    popup._buttons_down = False
    popup._poll_outside_click()


def test_defaults_are_plain_mode() -> None:
    s = Settings()
    assert s.display.popup_pinned is False
    assert s.zh.enabled is False
    assert s.translate.display_mode == "simple"
    assert s.translate.phonetic_audio_en is False


def test_pin_survives_a_new_snip(popup) -> None:
    popup.set_pinned(True)
    popup.show_for_region(QRect(100, 100, 200, 40))
    assert popup._pinned and popup._header.is_pinned()


@pytest.mark.skipif(sys.platform != "win32", reason="mouse poll is Windows-only")
def test_unpinned_popup_hides_on_outside_click(popup, monkeypatch) -> None:
    popup.show_for_region(QRect(100, 100, 200, 40))
    _click_at(popup, monkeypatch, FAR)
    assert not popup.isVisible()


@pytest.mark.skipif(sys.platform != "win32", reason="mouse poll is Windows-only")
def test_pinned_popup_stays_on_outside_click(popup, monkeypatch) -> None:
    popup.set_pinned(True)
    popup.show_for_region(QRect(100, 100, 200, 40))
    _click_at(popup, monkeypatch, FAR)
    assert popup.isVisible()


@pytest.mark.skipif(sys.platform != "win32", reason="mouse poll is Windows-only")
def test_click_inside_or_on_own_window_keeps_popup(popup, monkeypatch) -> None:
    popup.show_for_region(QRect(100, 100, 200, 40))
    _click_at(popup, monkeypatch, popup.geometry().center())
    assert popup.isVisible()
    _click_at(popup, monkeypatch, FAR, own_widget=popup)    # e.g. its language menu
    assert popup.isVisible()


@pytest.mark.skipif(sys.platform != "win32", reason="mouse poll is Windows-only")
def test_held_button_is_not_a_new_click(popup, monkeypatch) -> None:
    popup.show_for_region(QRect(100, 100, 200, 40))
    _click_at(popup, monkeypatch, FAR)          # sets the poll's state…
    popup.show_for_region(QRect(100, 100, 200, 40))
    popup._buttons_down = True                  # …button still held from before
    popup._poll_outside_click()
    assert popup.isVisible()
