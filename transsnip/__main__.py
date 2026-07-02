from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import threading

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from transsnip.app import AppController
from transsnip.config.settings import config_dir, load_settings
from transsnip.hotkeys.manager import HotkeyManager
from transsnip.tray.tray_icon import TrayController
from transsnip.ui.theme import get_theme
from transsnip.ui.tokens import ThemeMode


def _make_streams_safe() -> None:
    """Force stdout/stderr to UTF-8 so Vietnamese log/print text doesn't crash.

    Two failure modes this guards against, both only surfacing in a packaged
    (PyInstaller) build, never under a normal `python -m transsnip` run:
    - Console attached but using the legacy cp1252 code page → writing 'đ',
      'ư', etc. raises UnicodeEncodeError (this killed the frozen app at the
      tray-icon startup print).
    - `--windowed` build launched by double-click → no console at all, so
      `sys.stdout`/`sys.stderr` are None and any print()/log emit blows up.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # Non-reconfigurable stream (e.g. already wrapped) — best effort.
            pass


def _setup_logging(dev: bool) -> None:
    """Console logging + a rotating file in %APPDATA%\\transsnip\\logs.

    The packaged build runs windowed (console=False) with stderr redirected to
    devnull, so without the file handler a user's machine keeps zero logs and
    field issues (dead hotkeys, provider errors) are undiagnosable.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir = config_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_dir / "transsnip.log",
                maxBytes=2 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
        )
    except OSError:
        pass  # unwritable profile — console-only is still better than crashing
    logging.basicConfig(
        level=logging.DEBUG if dev else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    # Uncaught exceptions (main thread, worker threads, Qt slots) end up in the
    # log file instead of vanishing into the devnull-redirected stderr.
    def _log_uncaught(exc_type, exc, tb) -> None:
        logging.getLogger("transsnip").critical(
            "Uncaught exception", exc_info=(exc_type, exc, tb)
        )

    sys.excepthook = _log_uncaught
    threading.excepthook = lambda a: _log_uncaught(a.exc_type, a.exc_value, a.exc_traceback)


def main() -> int:
    _make_streams_safe()

    parser = argparse.ArgumentParser(prog="transsnip")
    parser.add_argument("--dev", action="store_true", help="Open settings window on launch and enable debug logging")
    args = parser.parse_args()

    _setup_logging(args.dev)

    # Default timeout for blocking sockets that never set one themselves —
    # notably deep_translator (Google free), which exposes no timeout param.
    # Without this, a black-holed connection (captive portal, dropped VPN)
    # pins a QThreadPool slot forever and the popup hangs at "Đang dịch…".
    # Per-op (connect/recv), so healthy long downloads are unaffected; asyncio
    # (edge-tts) uses non-blocking sockets and ignores this entirely.
    import socket
    socket.setdefaulttimeout(20)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("TransSnip")

    # Single-instance guard. Auto-start (HKCU Run key) + a manual launch used
    # to yield two processes: duplicated tray icons, hotkeys firing twice, and
    # RegisterHotKey failing in the second process. QLockFile detects stale
    # locks from crashed processes by PID, so a crash never wedges the app.
    lock = QLockFile(str(config_dir() / "transsnip.lock"))
    if not lock.tryLock(0):
        logging.getLogger("transsnip").info("Another instance is running — exiting")
        QMessageBox.information(
            None,
            "TransSnip",
            "TransSnip đang chạy sẵn ở khay hệ thống (system tray).",
        )
        return 0
    # Brand every Qt window (popup / settings / about / history) on the taskbar
    # and alt-tab. Loaded frozen-aware from assets/TransSnip.ico (no-op if absent).
    from transsnip.ui.branding import app_qicon
    app.setWindowIcon(app_qicon())

    # Install the global Cobalt stylesheet before any widget is built.
    # Restore the user's saved theme choice (dark / light / auto) so the
    # preference survives an app restart — falling back to AUTO if the
    # stored value is missing or invalid.
    theme = get_theme()
    try:
        saved_mode = ThemeMode(load_settings().display.theme_mode)
    except ValueError:
        saved_mode = ThemeMode.AUTO
    theme.set_mode(saved_mode)
    theme.apply(app)

    tray = TrayController(app, dev_mode=args.dev)
    tray.start()

    controller = AppController(app, tray)

    hotkeys = HotkeyManager(parent=app)
    hotkeys.triggered.connect(controller.handle_hotkey)
    # Hand the manager to the controller so it can rebind on settings-save.
    controller.set_hotkey_manager(hotkeys)
    # RegisterHotKey fails with a real error code when a combo is owned by
    # another app (or, at login, when the session isn't ready yet) — retry the
    # whole set with backoff while anything is still failing. apply_from_settings
    # is idempotent (unbind_all + rebind), so re-applying is always safe.
    _retry_delays_ms = [1_500, 5_000, 15_000]

    def _apply_hotkeys(attempt: int = 0) -> None:
        failed = hotkeys.apply_from_settings(controller.settings.hotkeys)
        if failed and attempt < len(_retry_delays_ms):
            logging.getLogger("transsnip").warning(
                "Hotkeys failed to bind: %s — retrying in %dms", failed, _retry_delays_ms[attempt]
            )
            QTimer.singleShot(_retry_delays_ms[attempt], lambda: _apply_hotkeys(attempt + 1))

    _apply_hotkeys()
    app.aboutToQuit.connect(hotkeys.unbind_all)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
