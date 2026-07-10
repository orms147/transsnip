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

High-priority mode (settings → hotkeys.high_priority) additionally runs a
WH_KEYBOARD_LL hook (see ll_hook.py) IN PARALLEL with RegisterHotKey: the
hook sees keystrokes before the system's hotkey matching and before
fullscreen games, and swallowing a matched keydown means WM_HOTKEY is never
generated — so both backends stay armed with no double-fire, and either one
dying leaves the other delivering.
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

from transsnip.hotkeys.ll_hook import LowLevelHotkeyHook

log = logging.getLogger(__name__)

# Watchdog period for the high-priority hook. Windows silently removes an LL
# hook whose callback overruns; re-installing on this cadence resurrects it.
# RegisterHotKey covers any gap, so this doesn't need to be aggressive.
_HOOK_REFRESH_MS = 30_000


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
        # Every action whose hotkey PARSED, keyed to (MOD_* flags sans
        # NOREPEAT, vk) — superset of _bindings, because the high-priority
        # hook can serve a combo RegisterHotKey was refused (already owned by
        # another app: the hook runs first and swallows, so we win anyway).
        self._wanted: dict[str, tuple[int, int]] = {}
        self._hook: LowLevelHotkeyHook | None = None
        self._hook_timer: QTimer | None = None
        # apply_from_settings rebinds ~10 actions; without batching, each
        # unbind/bind would push a partial table to the live hook — leaving a
        # window where NEITHER backend covers a combo (RegisterHotKey already
        # unregistered, hook table emptied) and re-arming held keys.
        self._suppress_hook_push = False
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
        # Parsed OK — the high-priority hook can serve it even when
        # RegisterHotKey below is refused.
        self._wanted[action_id] = (mods & ~_MOD_NOREPEAT, vk)
        self._push_combos_to_hook()
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
        if self._wanted.pop(action_id, None) is not None:
            self._push_combos_to_hook()
        entry = self._bindings.pop(action_id, None)
        if entry is None:
            return
        _hotkey, hk_id = entry
        self._by_id.pop(hk_id, None)
        if _user32 is not None:
            _user32.UnregisterHotKey(None, hk_id)

    def unbind_all(self) -> None:
        for action_id in list(self._wanted.keys() | self._bindings.keys()):
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
        surface the failure to the user. An action RegisterHotKey refused but
        the running high-priority hook covers is NOT reported as failed — the
        hook fires it regardless of who owns the OS registration.

        `hotkeys` is typed loosely (no `HotkeySettings` import here) to avoid
        a circular import between the hotkeys and config layers.
        """
        # Batch the hook update: keep the live hook serving the OLD table for
        # the whole rebind, then push the new table once — no window where a
        # combo is covered by neither backend.
        self._suppress_hook_push = True
        try:
            self.unbind_all()
            failed = []
            for action_id in DEFAULT_BINDINGS:
                value = getattr(hotkeys, action_id, "") or ""
                value = value.strip().lower()
                if not value:
                    log.info("Hotkey %s left unbound (user-disabled)", action_id)
                    continue
                if not self.bind(action_id, value):
                    failed.append(action_id)
        finally:
            self._suppress_hook_push = False
        self._push_combos_to_hook()
        self.set_high_priority(bool(getattr(hotkeys, "high_priority", False)))
        if self.high_priority_active():
            # Suppress only actions the hook actually serves — with duplicate
            # combos, first-wins means the losing action is NOT covered and
            # its failure must still reach the user.
            combos = self._hook_combos()
            covered = [
                aid for aid in failed
                if aid in self._wanted and combos.get(self._wanted[aid]) == aid
            ]
            if covered:
                log.info(
                    "RegisterHotKey refused %s but the high-priority hook covers them",
                    covered,
                )
            failed = [aid for aid in failed if aid not in covered]
        return failed

    def unregistered_actions(self) -> list[str]:
        """Parsed actions with no live RegisterHotKey registration.

        The high-priority hook may serve them right now, but they have no
        WM_HOTKEY fallback if it dies — __main__'s startup backoff keeps
        re-applying while this is non-empty so transient login-time refusals
        get registered eventually.
        """
        return [aid for aid in self._wanted if aid not in self._bindings]

    # ── High-priority (low-level hook) backend ──────────────────────────────

    def set_high_priority(self, enabled: bool) -> bool:
        """Start/stop the WH_KEYBOARD_LL backend next to RegisterHotKey.

        Returns whether the requested state is in effect (False = the hook
        failed to install; RegisterHotKey keeps working alone).
        """
        if not enabled:
            if self._hook_timer is not None:
                self._hook_timer.stop()
            if self._hook is not None:
                self._hook.stop()
                self._hook = None
                log.info("High-priority hotkey hook stopped")
            return True
        if self._hook is not None:
            if self._hook.is_running():
                self._push_combos_to_hook()
                return True
            # Alive-but-broken (thread died / install lost): stop it fully
            # before building a replacement, or its message-loop thread and
            # queue leak for the life of the process.
            self._hook.stop()
            self._hook = None
        # `triggered` may be emitted from the hook thread: the receiver lives
        # on the main thread, so Qt auto-queues the delivery — same path the
        # WM_HOTKEY dispatch takes, just from another thread.
        self._hook = LowLevelHotkeyHook(self.triggered.emit)
        if not self._hook.start():
            log.error("High-priority hook failed to install — RegisterHotKey only")
            self._hook = None
            return False
        self._push_combos_to_hook()
        if self._hook_timer is None:
            self._hook_timer = QTimer(self)
            self._hook_timer.setInterval(_HOOK_REFRESH_MS)
            self._hook_timer.timeout.connect(self._refresh_hook)
        self._hook_timer.start()
        log.info("High-priority hotkey hook installed (%d combos)", len(self._wanted))
        return True

    def high_priority_active(self) -> bool:
        return self._hook is not None and self._hook.is_running()

    def shutdown(self) -> None:
        """Full teardown on app quit: OS registrations + hook thread."""
        self.unbind_all()
        self.set_high_priority(False)

    def _hook_combos(self) -> dict[tuple[int, int], str]:
        """(mods, vk) → action_id with FIRST-wins on duplicate combos.

        RegisterHotKey gives a duplicated combo to whichever action bound
        first; the hook must agree, or the same keystroke would fire one
        action while the hook is alive and a different one when WM_HOTKEY
        takes over. (dict comprehension inversion would be last-wins.)
        """
        combos: dict[tuple[int, int], str] = {}
        for aid, combo in self._wanted.items():
            combos.setdefault(combo, aid)
        return combos

    def _push_combos_to_hook(self) -> None:
        if self._hook is not None and not self._suppress_hook_push:
            self._hook.set_combos(self._hook_combos())

    def _refresh_hook(self) -> None:
        """Watchdog tick: health-check, not just a blind refresh.

        A hook whose THREAD died (or never recovered an install) reports
        is_running() False and refresh() alone could never bring it back —
        rebuild it here, otherwise high-priority mode stays silently dead
        until the user happens to re-save settings.
        """
        if self._hook is None:
            return
        if self._hook.is_running():
            self._hook.refresh()
            return
        log.warning("High-priority hook found dead by watchdog — restarting")
        self._hook.stop()
        if self._hook.start():
            self._push_combos_to_hook()
        else:
            log.error("High-priority hook restart failed — will retry next tick")

    def _dispatch(self, hk_id: int) -> None:
        action_id = self._by_id.get(hk_id)
        if action_id is None:
            return
        # Defer out of the native event filter before any UI work happens.
        QTimer.singleShot(0, lambda: self.triggered.emit(action_id))
