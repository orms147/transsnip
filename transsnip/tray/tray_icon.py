from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

log = logging.getLogger(__name__)


class TrayController(QSystemTrayIcon):
    """Owns the system tray icon and its context menu.

    Emits `settings_requested` when the user clicks the Settings menu item so the
    AppController can open the dialog without the tray having to know about the UI.
    """

    settings_requested = Signal()

    def __init__(self, app: QApplication, *, dev_mode: bool = False) -> None:
        super().__init__(self._build_icon(dev_mode=dev_mode), parent=app)
        self._app = app
        self._dev_mode = dev_mode
        self.setToolTip("TransSnip — Bấm Alt+T để dịch vùng, Alt+F dịch full màn hình")
        self.setContextMenu(self._build_menu())
        self.activated.connect(self._on_activated)

    def start(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.critical(
                None,
                "TransSnip",
                "System tray không khả dụng trên hệ thống này. App cần system tray để chạy.",
            )
            self._app.quit()
            return
        self.show()
        print(
            "[transsnip] Tray icon đã start.\n"
            "  → Trên Windows 11: icon có thể bị giấu — click mũi tên '^' gần đồng hồ để xem overflow.\n"
            "  → Để pin icon ra ngoài: Settings → Personalization → Taskbar → Other system tray icons → bật TransSnip.\n"
            "  → Thoát app: right-click icon → Quit, hoặc bấm Ctrl+C trong terminal này."
        )
        if self._dev_mode:
            self.showMessage(
                "TransSnip",
                "Dev mode đang chạy — tray icon đã active",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_about()

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        settings_action = QAction("Settings...", self)
        settings_action.triggered.connect(self.settings_requested.emit)
        menu.addAction(settings_action)

        menu.addSeparator()

        about_action = QAction("About TransSnip", self)
        about_action.triggered.connect(self._show_about)
        menu.addAction(about_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)

        return menu

    def _show_about(self) -> None:
        QMessageBox.information(
            None,
            "About TransSnip",
            "TransSnip v0.1.0\n\nHotkey-driven screen translation for Windows.\nEarly development — xem docs/mentor/ cho roadmap.",
        )

    @staticmethod
    def _build_icon(*, dev_mode: bool) -> QIcon:
        # Placeholder: 64x64 square với chữ "T". Dev mode = đỏ để dễ phân biệt với prod.
        size = 64
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            bg_color = QColor(229, 57, 53) if dev_mode else QColor(30, 136, 229)
            painter.fillRect(pix.rect(), bg_color)
            painter.setPen(QColor(255, 255, 255))
            font = QFont()
            font.setBold(True)
            font.setPointSize(32)
            painter.setFont(font)
            painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "T")
        finally:
            painter.end()
        return QIcon(pix)
