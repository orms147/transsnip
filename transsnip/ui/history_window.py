"""HistoryWindow — browse / copy / replay recent translations.

A frameless Cobalt-themed window (CustomTitlebar chrome) listing the most recent
translations newest-first. Each card shows source → translation + meta, with
Copy and (for English source) a speak button that reuses the Edge/SAPI player.

Opened from the tray "History" item. Reads from `HistoryStore`; "Clear all"
empties both the list and the on-disk file.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transsnip.config.history import HistoryEntry, HistoryStore
from transsnip.tts.edge_tts_player import EdgeTTSPlayer
from transsnip.ui.atoms import CustomTitlebar, IconButton
from transsnip.ui.theme import get_theme

_MAX_SRC_CHARS = 160


class HistoryWindow(QWidget):
    def __init__(self, store: HistoryStore, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(440, 560)
        self._store = store
        self._tts = EdgeTTSPlayer(self)

        # Root container (painted via stylesheet so the rounded corners show).
        self._root = QWidget(self)
        self._root.setObjectName("histRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._root)

        root_layout = QVBoxLayout(self._root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._titlebar = CustomTitlebar("Lịch sử dịch", show_minimize=False, show_maximize=False)
        self._titlebar.close_requested.connect(self.hide)
        root_layout.addWidget(self._titlebar)

        # Toolbar: count + Clear all
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(16, 8, 12, 8)
        self._count_label = QLabel("")
        toolbar.addWidget(self._count_label)
        toolbar.addStretch(1)
        self._clear_btn = IconButton("trash", size=30, icon_size=14, tooltip="Xoá tất cả")
        self._clear_btn.clicked.connect(self._on_clear)
        toolbar.addWidget(self._clear_btn)
        root_layout.addLayout(toolbar)

        # Scrollable list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(12, 4, 12, 12)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list)
        root_layout.addWidget(self._scroll, stretch=1)

        get_theme().mode_changed.connect(lambda _p: self._apply_style())
        self._apply_style()

    # ── Public ───────────────────────────────────────────────────────────────

    def open(self) -> None:
        self.refresh()
        self._center()
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self) -> None:
        # Clear existing cards (keep the trailing stretch).
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        entries = self._store.recent()
        self._count_label.setText(f"{len(entries)} bản dịch gần đây")
        if not entries:
            empty = QLabel("Chưa có bản dịch nào.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            p = get_theme().palette
            empty.setStyleSheet(f"color: {p.text_3}; padding: 40px;")
            self._list_layout.insertWidget(0, empty)
            return
        for i, entry in enumerate(entries):
            self._list_layout.insertWidget(i, self._make_card(entry))

    # ── Card ─────────────────────────────────────────────────────────────────

    def _make_card(self, entry: HistoryEntry) -> QWidget:
        p = get_theme().palette
        card = QFrame()
        card.setObjectName("histCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(5)

        src = entry.source_text.strip()
        if len(src) > _MAX_SRC_CHARS:
            src = src[:_MAX_SRC_CHARS] + "…"
        src_lbl = QLabel(src)
        src_lbl.setWordWrap(True)
        src_lbl.setStyleSheet(f"color: {p.text_3}; font-size: 12px;")
        lay.addWidget(src_lbl)

        tr_lbl = QLabel(entry.translated_text.strip())
        tr_lbl.setWordWrap(True)
        tr_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tr_lbl.setStyleSheet(f"color: {p.text_1}; font-size: 14px; font-weight: 500;")
        lay.addWidget(tr_lbl)

        # Meta + actions row
        row = QHBoxLayout()
        row.setSpacing(6)
        when = entry.timestamp.replace("T", " ")[:16] if entry.timestamp else ""
        meta = QLabel(
            f"{entry.source_lang} → {entry.target_lang} · {entry.provider}"
            + (f" · {when}" if when else "")
        )
        meta.setStyleSheet(f"color: {p.text_mute}; font-size: 10.5px;")
        row.addWidget(meta)
        row.addStretch(1)

        if (entry.source_lang or "").lower().startswith("en"):
            speak_btn = IconButton("volume", size=26, icon_size=13, tooltip="Phát âm (English)")
            speak_btn.clicked.connect(lambda _=False, t=entry.source_text: self._tts.speak(t))
            row.addWidget(speak_btn)
        copy_btn = IconButton("copy", size=26, icon_size=13, tooltip="Copy bản dịch")
        copy_btn.clicked.connect(lambda _=False, t=entry.translated_text: self._copy(t))
        row.addWidget(copy_btn)
        lay.addLayout(row)

        card.setStyleSheet(
            f"QFrame#histCard {{ background: {p.bg_2}; border: 1px solid {p.border_1}; "
            f"border-radius: 10px; }}"
        )
        return card

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _copy(self, text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)

    def _on_clear(self) -> None:
        self._store.clear()
        self.refresh()

    def _center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._root.setStyleSheet(
            f"QWidget#histRoot {{ background: {p.bg_1}; border: 1px solid {p.border_2}; "
            f"border-radius: 12px; }}"
        )
        self._count_label.setStyleSheet(f"color: {p.text_2}; font-size: 12px;")
        self.refresh()
