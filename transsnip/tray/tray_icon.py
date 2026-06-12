"""TrayController — system tray icon + rich context menu (Cobalt design).

The tray menu now includes:
- Header strip with TransSnip glyph + active provider/preset summary
- Region/Fullscreen/Video shortcut rows with kbd hints (mirrors
  surface-system.jsx TrayMenu)
- Provider + Preset quick-pick items showing current selection
- Settings · About · Quit

About is its own widget (`AboutDialog`) instead of a QMessageBox so it
matches the Cobalt theme. Tray icon itself is a small SVG monogram painted
via the icon system so the color follows the theme palette.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

log = logging.getLogger(__name__)


class TrayController(QSystemTrayIcon):
    """Owns the system tray icon and its context menu."""

    settings_requested = Signal()
    about_requested = Signal()
    history_requested = Signal()
    region_translate_triggered = Signal()
    fullscreen_translate_triggered = Signal()

    def __init__(self, app: QApplication, *, dev_mode: bool = False) -> None:
        super().__init__(_build_tray_pixmap(dev_mode=dev_mode), parent=app)
        self._app = app
        self._dev_mode = dev_mode
        self.setToolTip("TransSnip — Alt+T region · Alt+F fullscreen")
        # AppController can set this later to show "claude · sonnet-4" etc.
        self._provider_label = ""
        self._preset_label = ""
        self.setContextMenu(self._build_menu())
        self.activated.connect(self._on_activated)

    def start(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.critical(
                None,
                "TransSnip",
                "System tray không khả dụng. App cần system tray để chạy.",
            )
            self._app.quit()
            return
        self.show()
        print(
            "[transsnip] Tray icon đã start.\n"
            "  → Trên Windows 11: icon có thể bị giấu — click '^' gần đồng hồ để xem overflow.\n"
            "  → Để pin icon ra ngoài: Settings → Personalization → Taskbar → Other system tray icons.\n"
            "  → Thoát app: right-click icon → Quit."
        )

    def set_provider_summary(self, label: str) -> None:
        """Called by AppController after settings save so the menu reflects
        the current provider (`claude · sonnet-4` etc.)."""
        self._provider_label = label
        self.setContextMenu(self._build_menu())

    def set_preset_summary(self, label: str) -> None:
        self._preset_label = label
        self.setContextMenu(self._build_menu())

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.settings_requested.emit()

    def _build_menu(self) -> QMenu:
        # Minimal menu — admin actions only. Mode shortcuts are already
        # available via global hotkeys (Alt+T / Alt+F); duplicating them
        # in the tray menu just made the panel taller without adding value.
        menu = QMenu()

        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self.settings_requested.emit)
        menu.addAction(settings_action)

        history_action = QAction("Lịch sử dịch", self)
        history_action.triggered.connect(self.history_requested.emit)
        menu.addAction(history_action)

        about_action = QAction("About TransSnip", self)
        about_action.triggered.connect(self.about_requested.emit)
        menu.addAction(about_action)

        menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)

        return menu

    def _trigger_region(self) -> None:
        self.region_translate_triggered.emit()

    def _trigger_fullscreen(self) -> None:
        self.fullscreen_translate_triggered.emit()


def _build_tray_pixmap(*, dev_mode: bool, size: int = 64) -> QIcon:
    """Build the tray monogram — crop brackets + chevron, themed by accent.

    Dev mode tints the bracket color red so a developer running both
    dev and prod sees which is which at a glance.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Scale 16-viewbox glyph into the requested size.
        scale = size / 16
        painter.scale(scale, scale)

        accent = QColor(229, 57, 53) if dev_mode else QColor(129, 140, 248)  # cobalt accent
        text_color = QColor(236, 237, 239)

        # Crop brackets
        pen = QPen(accent, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        paths_d = [
            ((2.5, 4.5), (2.5, 3), (3.2, 2.3), (4.5, 2.3)),
            ((11.5, 2.3), (13, 2.3), (13.7, 3), (13.7, 4.5)),
            ((13.7, 11.5), (13.7, 13), (13, 13.7), (11.5, 13.7)),
            ((4.5, 13.7), (3, 13.7), (2.3, 13), (2.3, 11.5)),
        ]
        for pts in paths_d:
            path = QPainterPath()
            path.moveTo(*pts[0])
            for pt in pts[1:]:
                path.lineTo(*pt)
            painter.drawPath(path)

        # Inner chevron
        pen2 = QPen(text_color, 1.6)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen2)
        bar = QPainterPath()
        bar.moveTo(6, 8)
        bar.lineTo(10, 8)
        painter.drawPath(bar)
        chev = QPainterPath()
        chev.moveTo(8.5, 6.5)
        chev.lineTo(10, 8)
        chev.lineTo(8.5, 9.5)
        painter.drawPath(chev)
    finally:
        painter.end()
    return QIcon(pixmap)
