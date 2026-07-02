"""Global hotkeys via Win32 RegisterHotKey + WM_HOTKEY.

Previously this wrapped the `keyboard` library, which installs a global
WH_KEYBOARD_LL hook. Windows silently removes that hook when its callback
misses LowLevelHooksTimeout (~300ms) — easy to hit during login when the app
auto-starts while the system is under load — and the library never re-installs
it, so every hotkey stayed dead until the process restarted.

RegisterHotKey has no such failure mode: Windows matches the combo itself and
posts WM_HOTKEY to this thread's message queue, no callback deadline involved.
It also returns a real error when another app owns the combo, instead of
failing silently.

Behavioral difference from the old backend: a registered combo is consumed by
the OS (the focused app no longer sees it) — the desired behavior for
launcher-style hotkeys like Alt+T.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Final

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QCoreApplication,
    QObject,
    QTimer,
    Signal,
)

log = logging.getLogger(__name__)


DEFAULT_BINDINGS: Final[dict[str, str]] = {
    "region_translate": "alt+t",
    "fullscreen_translate": "alt+f",
    "video_subtitle_translate": "alt+v",
    "audio_subtitle_translate": "alt+a",
    "open_settings": "ctrl+alt+s",
}

WM_HOTKEY = 0x0312

_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000

_MODIFIERS: Final[dict[str, int]] = {
    "alt": _MOD_ALT,
    "ctrl": _MOD_CONTROL,
    "control": _MOD_CONTROL,
    "shift": _MOD_SHIFT,
    "win": _MOD_WIN,
    "meta": _MOD_WIN,  # QKeySequence PortableText renders the Windows key as "Meta"
}

# Named keys as produced by `QKeySequence.toString(PortableText).lower()`
# (see settings_window._qt_to_hotkey) → Win32 virtual-key codes.
_NAMED_VK: Final[dict[str, int]] = {
    "space": 0x20,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "backspace": 0x08,
    "return": 0x0D,
    "enter": 0x0D,
    "ins": 0x2D,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "pgup": 0x21,
    "pgdown": 0x22,
    "pause": 0x13,
    "print": 0x2C,
    "capslock": 0x14,
    **{f"f{i}": 0x70 + i - 1 for i in range(1, 25)},
}

_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
if _user32 is not None:
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    _user32.VkKeyScanW.restype = ctypes.c_short


def parse_hotkey(hotkey: str) -> tuple[int, int]:
    """`"ctrl+alt+s"` → `(modifier_flags, virtual_key)`.

    Raises ValueError on an unparseable string so callers can surface it.
    """
    mods = _MOD_NOREPEAT
    vk: int | None = None
    # A literal plus key ("ctrl++") splits into TWO empty trailing parts —
    # fold them back into "+". A single trailing empty ("alt+") is malformed
    # and falls through to the ValueError below.
    parts = [p.strip() for p in hotkey.split("+")]
    if len(parts) >= 3 and parts[-1] == "" and parts[-2] == "":
        parts = parts[:-2] + ["+"]
    for part in parts:
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif part in _NAMED_VK:
            vk = _NAMED_VK[part]
        elif len(part) == 1:
            if _user32 is None:
                raise ValueError(f"cannot resolve key {part!r} off Windows")
            scan = _user32.VkKeyScanW(part)
            if scan == -1:
                raise ValueError(f"no virtual key for {part!r}")
            vk = scan & 0xFF
        else:
            raise ValueError(f"unsupported key part {part!r} in {hotkey!r}")
    if vk is None:
        raise ValueError(f"hotkey {hotkey!r} has no non-modifier key")
    return mods, vk


class _WmHotkeyFilter(QAbstractNativeEventFilter):
    """Routes WM_HOTKEY from the thread message queue to the manager."""

    def __init__(self, manager: "HotkeyManager") -> None:
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt override)
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._manager._dispatch(msg.wParam)
        return False, 0


class HotkeyManager(QObject):
    """Global hotkeys as Qt signals, backed by Win32 RegisterHotKey.

    `RegisterHotKey(hWnd=None)` ties the hotkey to the *calling thread*, and
    WM_HOTKEY lands in that thread's message queue — so `bind`/`unbind` must
    run on the Qt main thread (they do: app startup and the settings-save slot
    both live there). The emit is deferred with a 0-ms timer so handlers never
    run re-entrantly inside the native event filter.
    """

    triggered = Signal(str)  # action_id

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bindings: dict[str, tuple[str, int]] = {}  # action_id -> (hotkey, hk_id)
        self._by_id: dict[int, str] = {}
        self._next_id = 1
        self._filter = _WmHotkeyFilter(self)
        app = QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filter)
        else:  # pure-logic tests construct the manager without a QApplication
            log.warning("No QCoreApplication — WM_HOTKEY filter not installed")

    def bind(self, action_id: str, hotkey: str) -> bool:
        """Register a global hotkey. Replaces existing binding for action_id.

        Returns True on success, False if the string is unparseable or the OS
        rejected the combo (typically: another app already registered it).
        """
        self.unbind(action_id)
        if _user32 is None:
            log.error("Global hotkeys are Windows-only — cannot bind %r", hotkey)
            return False
        try:
            mods, vk = parse_hotkey(hotkey)
        except ValueError:
            log.exception("Unparseable hotkey %r for %r", hotkey, action_id)
            return False
        hk_id = self._next_id
        if not _user32.RegisterHotKey(None, hk_id, mods, vk):
            log.error(
                "RegisterHotKey failed for %r (%s), winerror=%d — combo likely owned by another app",
                hotkey,
                action_id,
                ctypes.get_last_error(),
            )
            return False
        self._next_id += 1
        self._bindings[action_id] = (hotkey, hk_id)
        self._by_id[hk_id] = action_id
        log.info("Bound %s -> %s (id=%d)", hotkey, action_id, hk_id)
        return True

    def unbind(self, action_id: str) -> None:
        entry = self._bindings.pop(action_id, None)
        if entry is None:
            return
        _hotkey, hk_id = entry
        self._by_id.pop(hk_id, None)
        if _user32 is not None:
            _user32.UnregisterHotKey(None, hk_id)

    def unbind_all(self) -> None:
        for action_id in list(self._bindings):
            self.unbind(action_id)

    def bindings(self) -> dict[str, str]:
        return {aid: hotkey for aid, (hotkey, _hk_id) in self._bindings.items()}

    def apply_defaults(self) -> None:
        for action_id, hotkey in DEFAULT_BINDINGS.items():
            self.bind(action_id, hotkey)

    def apply_from_settings(self, hotkeys) -> list[str]:
        """Rebind every action from a `HotkeySettings` instance.

        Replaces all existing bindings — call this on app start and again
        whenever the user saves new bindings in Settings. Empty strings are
        skipped so a user can deliberately disable a hotkey.

        Returns the action_ids that failed to bind, so callers can retry or
        surface the failure to the user.

        `hotkeys` is typed loosely (no `HotkeySettings` import here) to avoid
        a circular import between the hotkeys and config layers.
        """
        self.unbind_all()
        failed: list[str] = []
        for action_id in DEFAULT_BINDINGS:
            value = getattr(hotkeys, action_id, "") or ""
            value = value.strip().lower()
            if not value:
                log.info("Hotkey %s left unbound (user-disabled)", action_id)
                continue
            if not self.bind(action_id, value):
                failed.append(action_id)
        return failed

    def _dispatch(self, hk_id: int) -> None:
        action_id = self._by_id.get(hk_id)
        if action_id is None:
            return
        # Defer out of the native event filter before any UI work happens.
        QTimer.singleShot(0, lambda: self.triggered.emit(action_id))
