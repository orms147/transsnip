from __future__ import annotations

import logging
from typing import Final

import keyboard
from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


DEFAULT_BINDINGS: Final[dict[str, str]] = {
    "region_translate": "alt+t",
    "fullscreen_translate": "alt+f",
    "video_subtitle_translate": "alt+v",
}


class HotkeyManager(QObject):
    """Wraps the `keyboard` library, exposing global hotkeys as Qt signals.

    `keyboard.add_hotkey()` invokes its callback on its own background thread.
    Emitting a Qt signal from that thread is safe — Qt queues the slot call onto
    the receiver's thread (the main/UI thread), so handlers can touch widgets
    without locking.
    """

    triggered = Signal(str)  # action_id

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bindings: dict[str, str] = {}

    def bind(self, action_id: str, hotkey: str) -> bool:
        """Register a global hotkey. Replaces existing binding for action_id.

        Returns True on success, False if the OS rejected the binding (e.g. another
        app has already grabbed the combo with exclusive access).
        """
        if action_id in self._bindings:
            self.unbind(action_id)
        try:
            keyboard.add_hotkey(
                hotkey,
                lambda aid=action_id: self.triggered.emit(aid),
                suppress=False,
            )
        except Exception:
            log.exception("Failed to register hotkey %r for %r", hotkey, action_id)
            return False
        self._bindings[action_id] = hotkey
        log.info("Bound %s -> %s", hotkey, action_id)
        return True

    def unbind(self, action_id: str) -> None:
        hotkey = self._bindings.pop(action_id, None)
        if hotkey is None:
            return
        try:
            keyboard.remove_hotkey(hotkey)
        except KeyError:
            pass  # `keyboard` raises if the hotkey is already gone — safe to ignore

    def unbind_all(self) -> None:
        for action_id in list(self._bindings):
            self.unbind(action_id)

    def bindings(self) -> dict[str, str]:
        return dict(self._bindings)

    def apply_defaults(self) -> None:
        for action_id, hotkey in DEFAULT_BINDINGS.items():
            self.bind(action_id, hotkey)

    def apply_from_settings(self, hotkeys) -> None:
        """Rebind every action from a `HotkeySettings` instance.

        Replaces all existing bindings — call this on app start and again
        whenever the user saves new bindings in Settings. Empty strings are
        skipped so a user can deliberately disable a hotkey.

        `hotkeys` is typed loosely (no `HotkeySettings` import here) to avoid
        a circular import between the hotkeys and config layers.
        """
        self.unbind_all()
        for action_id in DEFAULT_BINDINGS:
            value = getattr(hotkeys, action_id, "") or ""
            value = value.strip().lower()
            if not value:
                log.info("Hotkey %s left unbound (user-disabled)", action_id)
                continue
            self.bind(action_id, value)
