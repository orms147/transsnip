from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtWidgets import QApplication

from transsnip.app import AppController
from transsnip.config.settings import load_settings
from transsnip.hotkeys.manager import HotkeyManager
from transsnip.tray.tray_icon import TrayController
from transsnip.ui.theme import get_theme
from transsnip.ui.tokens import ThemeMode


def main() -> int:
    parser = argparse.ArgumentParser(prog="transsnip")
    parser.add_argument("--dev", action="store_true", help="Open settings window on launch and enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.dev else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("TransSnip")

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
    hotkeys.apply_from_settings(controller.settings.hotkeys)
    app.aboutToQuit.connect(hotkeys.unbind_all)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
