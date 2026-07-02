"""Force a Qt window to the Windows foreground, past the foreground lock.

Overlays opened from a *global hotkey* have a focus problem: the hotkey fires
while another application owns the foreground, and Windows refuses to let a
background process steal focus — `SetForegroundWindow` (what Qt's
`activateWindow()` maps to) fails silently. The overlay still shows topmost
and receives mouse events (those route by cursor position), but every
keystroke keeps going to the old app, so Esc/Enter handlers never fire.

The standard workaround: temporarily attach this thread's input queue to the
foreground window's thread with `AttachThreadInput` — attached threads share
focus state, which makes `SetForegroundWindow` permitted again.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.SetFocus.argtypes = [wintypes.HWND]
    _user32.SetFocus.restype = wintypes.HWND
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
else:
    _user32 = None
    _kernel32 = None


def force_foreground(widget) -> None:
    """Bring a shown Qt widget's window to the foreground and give it focus.

    Call right after `show()`/`showFullScreen()`. No-op off Windows or when
    the window is already foreground.
    """
    if _user32 is None:
        return
    hwnd = int(widget.winId())
    fg = _user32.GetForegroundWindow()
    if fg == hwnd:
        return
    cur_tid = _kernel32.GetCurrentThreadId()
    fg_tid = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(_user32.AttachThreadInput(fg_tid, cur_tid, True))
    try:
        if not _user32.SetForegroundWindow(hwnd):
            log.debug("SetForegroundWindow failed (winerror=%d)", ctypes.get_last_error())
        _user32.SetFocus(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(fg_tid, cur_tid, False)
