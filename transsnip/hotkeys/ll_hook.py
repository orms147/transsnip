"""High-priority hotkey backend: WH_KEYBOARD_LL low-level keyboard hook.

Why this exists next to RegisterHotKey (manager.py): fullscreen games and
apps that grabbed our combo first can make RegisterHotKey useless — either
the combo is already owned (RegisterHotKey fails at bind time) or the user
wants a guarantee that the game never reacts to the keystroke. A low-level
keyboard hook runs BEFORE the system's hotkey matching and before the
foreground app sees the event, so returning 1 from the callback both fires
our action and swallows the key system-wide.

This is the mechanism the old `keyboard`-library backend used, and it was
dropped for a real reason (see manager.py's module docstring): Windows
silently removes an LL hook whose callback misses LowLevelHooksTimeout
(~300ms) and never tells you. Two mitigations make it safe to bring back:

1. Watchdog re-install — HotkeyManager posts `refresh()` on a timer; the
   hook thread unhooks + rehooks, resurrecting a silently-removed hook (and
   keeping us at the front of the hook chain).
2. RegisterHotKey stays active in parallel. While the hook is alive it
   swallows matched keydowns, so WM_HOTKEY is never generated — no double
   fire. The moment the hook dies, WM_HOTKEY delivery resumes. The two
   backends hand over automatically with zero coordination.

Known limit (by OS design): if the foreground app runs elevated and
TransSnip does not, UIPI hides its keystrokes from this hook — the
RegisterHotKey path still works there.

The hook lives on its own thread because the callback is invoked via the
message loop of the *installing* thread — putting it on the Qt main thread
would add UI jank to every keystroke system-wide and make hook-timeout
removal far more likely.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, Final

log = logging.getLogger(__name__)

_WH_KEYBOARD_LL: Final = 13
_HC_ACTION: Final = 0

_WM_KEYDOWN: Final = 0x0100
_WM_KEYUP: Final = 0x0101
_WM_SYSKEYDOWN: Final = 0x0104
_WM_SYSKEYUP: Final = 0x0105
_WM_QUIT: Final = 0x0012
# Private thread message asking the hook thread to unhook + rehook.
_WM_REHOOK: Final = 0x8000 + 0x0001  # WM_APP + 1

# Virtual keys polled for the modifier snapshot. Generic VK_SHIFT/VK_CONTROL/
# VK_MENU cover both left and right variants; Win needs both polled.
_VK_SHIFT: Final = 0x10
_VK_CONTROL: Final = 0x11
_VK_MENU: Final = 0x12
_VK_LWIN: Final = 0x5B
_VK_RWIN: Final = 0x5C

# Same bit values as RegisterHotKey's MOD_* flags so manager.parse_hotkey
# output (minus MOD_NOREPEAT) can be used as-is for combo keys.
MOD_ALT: Final = 0x0001
MOD_CONTROL: Final = 0x0002
MOD_SHIFT: Final = 0x0004
MOD_WIN: Final = 0x0008

_LRESULT = ctypes.c_ssize_t  # LONG_PTR — not in ctypes.wintypes


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),  # ULONG_PTR
    )


if sys.platform == "win32":
    # WINFUNCTYPE only exists on Windows builds of ctypes — defining it
    # unconditionally would crash the module import (and everything that
    # imports the hotkey manager) on other platforms.
    _HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD,
    ]
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
    ]
    _user32.CallNextHookEx.restype = _LRESULT
    _user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
    ]
    _user32.GetMessageW.restype = ctypes.c_int  # -1 on error, not just 0/1
    _user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND,
        wintypes.UINT, wintypes.UINT, wintypes.UINT,
    ]
    _user32.PeekMessageW.restype = wintypes.BOOL
    _user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
else:
    _HOOKPROC = None
    _user32 = None
    _kernel32 = None


def _vk_physically_down(vk: int) -> bool:
    """Is the key physically held right now, per GetAsyncKeyState?

    Note the asymmetry that makes this usable: keydowns WE swallow never
    reach the OS state tables (reads as up), but keydowns that fired while
    the hook was dead did — which is exactly the "already handled by the
    WM_HOTKEY fallback" population sync_physical needs to detect.
    """
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def _current_mods() -> int:
    """Snapshot of held modifiers as MOD_* flags, via GetAsyncKeyState.

    GetAsyncKeyState (not GetKeyState) because the hook thread processes no
    input of its own — its synchronous key state never updates. The trigger
    key's own event hasn't been consumed yet at callback time, but modifiers
    were pressed earlier so their async state is already accurate.
    """
    down = _user32.GetAsyncKeyState
    mods = 0
    if down(_VK_MENU) & 0x8000:
        mods |= MOD_ALT
    if down(_VK_CONTROL) & 0x8000:
        mods |= MOD_CONTROL
    if down(_VK_SHIFT) & 0x8000:
        mods |= MOD_SHIFT
    if (down(_VK_LWIN) & 0x8000) or (down(_VK_RWIN) & 0x8000):
        mods |= MOD_WIN
    return mods


class HookState:
    """Pure decision logic for the hook callback — no Win32, unit-testable.

    Mirrors RegisterHotKey semantics: exact modifier match (Ctrl+Alt+T does
    NOT fire an Alt+T binding) and MOD_NOREPEAT (holding the key fires once;
    OS auto-repeats are swallowed without re-firing so the game never sees a
    stream of T's).
    """

    # A held trigger key produces auto-repeats every few dozen ms, each one
    # refreshing its _held timestamp. A matched keydown whose last event is
    # older than this can't be part of a repeat train we watched — the hook
    # was dead in between (silently removed by Windows) and missed the keyup,
    # so it's a genuine new press. Firing it beats swallowing it into nothing.
    # Must clear Windows' slowest configurable repeat: FilterKeys allows a
    # 2.0s RepeatKeys interval, and a threshold at exactly that value would
    # re-fire on roughly half of a slow-repeat user's legitimate repeats.
    HELD_STALE_S: Final = 3.0

    def __init__(self) -> None:
        self._combos: dict[tuple[int, int], str] = {}
        self._vks: frozenset[int] = frozenset()
        # Trigger keys currently held that already fired → last-event time.
        self._held: dict[int, float] = {}

    def set_combos(self, combos: dict[tuple[int, int], str]) -> None:
        """Replace the (mods, vk) → action_id table.

        Called from the Qt main thread while the callback reads from the hook
        thread. The _combos/_vks writes aren't atomic together, but the worst
        interleaving is one keystroke matched against the outgoing table —
        benign, so no lock in the per-keystroke hot path.

        Held-state survives for trigger keys that stay bound: a settings
        re-apply while the user holds a combo must NOT re-arm it, or the next
        OS auto-repeat would fire the action a second time from one press.
        Unbound keys are pruned IN PLACE (snapshot the keys, pop one by one)
        — a rebuild-and-swap would race the hook thread's concurrent
        pop/insert on _held: iteration could raise RuntimeError, and a
        fresh-press insert landing between snapshot and swap would be
        discarded, double-firing on the next auto-repeat.
        """
        self._combos = dict(combos)
        self._vks = frozenset(vk for _mods, vk in combos)
        for vk in list(self._held):
            if vk not in self._vks:
                self._held.pop(vk, None)

    def sync_physical(self, is_down: Callable[[int], bool], now: float) -> None:
        """Reconcile _held with the physical keyboard after a hook (re)install.

        While the hook was dead, keydowns reached the OS (so RegisterHotKey
        already fired for them) and keyups vanished from our view. Per bound
        trigger key:
        - physically DOWN → mark held: the press was handled by the WM_HOTKEY
          fallback; re-firing on its next auto-repeat would double-toggle
          Alt+F/Alt+V from a single physical press.
        - physically UP → re-arm: a stale _held entry here means we missed
          the keyup, and leaving it would swallow the user's next press
          (within HELD_STALE_S) into nothing at all.
        Runs on the hook thread, like all other _held writers.
        """
        for vk in self._vks:
            if is_down(vk):
                self._held[vk] = now
            else:
                self._held.pop(vk, None)

    def on_key(
        self, vk: int, is_down: bool, mods_getter: Callable[[], int], now: float
    ) -> tuple[str | None, bool]:
        """Decide (action_to_fire, swallow_event) for one keyboard event.

        `mods_getter` is a callable so the (comparatively) expensive modifier
        snapshot only happens for keydowns of registered trigger keys — the
        common case (any other key) exits on the frozenset check alone.
        `now` is a monotonic timestamp supplied by the caller (keeps this
        class clock-free for tests).
        """
        if vk not in self._vks:
            return None, False
        if not is_down:
            self._held.pop(vk, None)
            return None, False
        action = self._combos.get((mods_getter(), vk))
        if action is None:
            # Trigger key pressed with the wrong modifiers (or user released a
            # modifier mid-hold) — let it through and re-arm.
            self._held.pop(vk, None)
            return None, False
        last = self._held.get(vk)
        self._held[vk] = now
        if last is not None and now - last < self.HELD_STALE_S:
            return None, True  # OS auto-repeat: keep swallowing, fire once
        # Fresh press — or a stale _held entry whose keyup the (then-dead)
        # hook never saw. Either way the user pressed the combo: fire.
        return action, True


class LowLevelHotkeyHook:
    """Owns the hook thread. All public methods are called from the Qt main
    thread; the callback runs on the hook thread.

    `on_trigger(action_id)` is invoked ON THE HOOK THREAD and must be cheap
    and thread-safe — HotkeyManager passes a cross-thread Qt signal emit,
    which queues into the main event loop.
    """

    def __init__(self, on_trigger: Callable[[str], None]) -> None:
        self._on_trigger = on_trigger
        self._state = HookState()
        self._thread: threading.Thread | None = None
        self._tid: int = 0
        self._hook: int | None = None
        self._installed = False
        self._ready = threading.Event()
        # Monotonic start() generation. Each thread captures its generation at
        # spawn; start()-timeout and stop() bump the counter, so a late-waking
        # starved thread finds itself outdated and tears down its own hook
        # instead of living on as a zombie. (A shared clearable Event can't do
        # this: the NEXT start() would clear it and un-cancel the old thread.)
        self._generation = 0
        # Keep the WINFUNCTYPE wrapper alive for the hook's whole lifetime —
        # if it's garbage-collected, Windows calls into freed memory.
        # (None off Windows: construction must not crash so the manager can
        # reach the graceful start() → False path.)
        self._callback = _HOOKPROC(self._proc) if _HOOKPROC is not None else None

    # ── Main-thread API ─────────────────────────────────────────────────────

    def start(self) -> bool:
        """Spawn the hook thread and install the hook. Returns install success."""
        if _user32 is None:
            log.error("Low-level keyboard hook is Windows-only")
            return False
        if self.is_running():
            return True
        self._generation += 1
        gen = self._generation
        self._ready.clear()
        self._installed = False
        self._tid = 0
        self._thread = threading.Thread(
            target=self._run, args=(gen,), name="transsnip-ll-hook", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=5):
            # Starved thread. Outdate its generation so it can't wake up later
            # as an orphaned system-wide hook: _tid is published before ready
            # is set, so either it already published (the WM_QUIT ends its
            # loop) or it will still fail its generation check after install
            # and tear its own hook down.
            log.error("LL hook thread did not come up within 5s")
            self._generation += 1
            if self._tid:
                _user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)
            self._thread = None
            return False
        if not self._installed:
            self._thread = None
        return self._installed

    def stop(self) -> None:
        if self._thread is None:
            return
        self._generation += 1  # outdate any not-yet-checked late starter too
        # Only post to a LIVE thread: Windows recycles thread ids, and a
        # WM_QUIT aimed at a long-dead tid could terminate the message loop
        # of whatever unrelated thread inherited the id.
        if self._tid and self._thread.is_alive():
            _user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)
        self._thread.join(timeout=2)
        if self._thread.is_alive():
            log.warning("LL hook thread did not exit within 2s")
        self._thread = None
        self._installed = False

    def refresh(self) -> None:
        """Ask the hook thread to unhook + rehook (watchdog tick).

        Windows gives no notification when it removes a timed-out LL hook, so
        the manager calls this periodically: a healthy hook is re-installed at
        the front of the hook chain, a dead one is resurrected.

        Gated on thread liveness, NOT on is_running(): after a failed
        re-install the message loop is still spinning with no hook in place,
        and this very retry is what brings the hook back.
        """
        if self._thread is not None and self._thread.is_alive() and self._tid:
            _user32.PostThreadMessageW(self._tid, _WM_REHOOK, 0, 0)

    def set_combos(self, combos: dict[tuple[int, int], str]) -> None:
        """Combo table: (MOD_* flags, vk) → action_id. Safe while running."""
        self._state.set_combos(combos)

    def is_running(self) -> bool:
        return (
            self._thread is not None and self._thread.is_alive() and self._installed
        )

    # ── Hook thread ─────────────────────────────────────────────────────────

    def _run(self, gen: int) -> None:
        # Force-create this thread's message queue BEFORE signalling ready, so
        # a stop()/refresh() racing in right after start() can't lose its
        # PostThreadMessageW (which fails against a queue-less thread).
        msg = wintypes.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, _WM_QUIT, _WM_QUIT, 0)  # PM_NOREMOVE
        tid = _kernel32.GetCurrentThreadId()
        # The handle stays a LOCAL for this thread's lifetime — a late-waking
        # outdated thread must only ever unhook its OWN hook, never the
        # replacement thread's (self._hook may already belong to that one).
        hook = self._install_handle()
        if self._generation == gen:
            self._tid = tid
            self._hook = hook
            self._installed = bool(hook)
        self._ready.set()
        if not hook or self._generation != gen:
            # Install failed, or start() gave up on this generation while we
            # were starved — vanish without touching shared state.
            if hook:
                _user32.UnhookWindowsHookEx(hook)
            return
        self._state.sync_physical(_vk_physically_down, time.monotonic())
        while True:
            rv = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if rv == 0:  # WM_QUIT
                break
            if rv == -1:
                log.error("GetMessage failed in hook thread (winerror=%d)",
                          ctypes.get_last_error())
                break
            if msg.message == _WM_REHOOK:
                hook = self._rehook(hook)
                self._hook = hook
                self._installed = bool(hook)
        if hook:
            _user32.UnhookWindowsHookEx(hook)

    def _rehook(self, old: int | None) -> int | None:
        """Replace the hook with zero coverage gap; returns the live handle.

        Install the new hook FIRST: new LL hooks go to the front of the
        chain, both handles share this object's _proc and state, and a
        matched keydown returns 1 which stops the chain before the old hook
        runs — so the brief overlap cannot double-fire. Unhooking first
        would leave a window where a keystroke falls through to
        RegisterHotKey and re-fires on the next auto-repeat.

        If the re-install fails, KEEP the old handle: a possibly-removed
        hook beats none at all, is_running() stays true, and the next
        watchdog tick retries.
        """
        new = self._install_handle()
        if new is None:
            return old
        if old:
            _user32.UnhookWindowsHookEx(old)
        # If Windows had silently removed the old hook, we missed keyups —
        # realign the auto-repeat guard with the physical keyboard so held
        # combos don't re-fire and released ones aren't swallowed.
        self._state.sync_physical(_vk_physically_down, time.monotonic())
        return new

    def _install_handle(self) -> int | None:
        # For WH_KEYBOARD_LL the hMod parameter is ignored on modern Windows
        # (the callback runs in the installing process, no DLL injection);
        # passing our own module handle keeps older kernels happy.
        hmod = _kernel32.GetModuleHandleW(None)
        hook = _user32.SetWindowsHookExW(_WH_KEYBOARD_LL, self._callback, hmod, 0)
        if not hook:
            log.error("SetWindowsHookEx(WH_KEYBOARD_LL) failed (winerror=%d)",
                      ctypes.get_last_error())
            return None
        return hook

    def _proc(self, n_code: int, w_param: int, l_param: int) -> int:
        # Runs for EVERY keystroke system-wide with a ~300ms deadline — keep it
        # tiny, and never let an exception escape into the ctypes boundary.
        try:
            if n_code == _HC_ACTION and self._handle_event(w_param, l_param):
                return 1  # swallow: the game and other hotkey owners never see it
        except Exception:  # noqa: BLE001
            log.exception("LL hook callback failed")
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _handle_event(self, w_param: int, l_param: int) -> bool:
        if w_param not in (_WM_KEYDOWN, _WM_SYSKEYDOWN, _WM_KEYUP, _WM_SYSKEYUP):
            return False
        kb = _KBDLLHOOKSTRUCT.from_address(l_param)
        is_down = w_param in (_WM_KEYDOWN, _WM_SYSKEYDOWN)
        action, swallow = self._state.on_key(
            int(kb.vkCode), is_down, _current_mods, time.monotonic()
        )
        if action is not None:
            self._on_trigger(action)
        return swallow
