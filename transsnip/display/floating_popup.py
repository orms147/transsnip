"""Compatibility shim — the popup now lives in `transsnip.display.popup`."""
from transsnip.display.popup.window import FloatingPopup

__all__ = ["FloatingPopup"]
