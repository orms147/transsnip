"""SettingsWindow — Cobalt redesign.

Frameless QWidget with custom titlebar, horizontal tab strip, and 5 tabs:
Translation · Context · Hotkeys · Display · Voice. Backend save/load logic
identical to the previous implementation — only the chrome and tab layout
follow the new design.

Tab visibility and active tracking lives in this module; per-tab build
functions return self-contained QWidget panels. Each tab caches the widgets
it cares about on `self` so `_load_from_model` / `_on_save` can shuttle
data between widgets and the Pydantic Settings model.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transsnip.config.keyring_store import get_api_key, set_api_key
from transsnip.config.settings import (
    DisplaySettings,
    HotkeySettings,
    PresetSettings,
    VoiceSettings,
    load_settings,
    save_settings,
)
from transsnip.hotkeys.manager import DEFAULT_BINDINGS
from transsnip.translate.openrouter import OPENROUTER_MODELS
from transsnip.translate.registry import PROVIDER_REGISTRY
from transsnip.ui import icons
from transsnip.ui.atoms import (
    CustomTitlebar,
    IconButton,
    SectionHead,
    Slider,
    ThemeCard,
    ToggleRow,
)
from transsnip.ui.theme import get_theme
from transsnip.ui.tokens import ThemeMode

log = logging.getLogger(__name__)


# ── Language tables (BCP-47 codes + display labels) ───────────────────────
# Same data as the previous implementation — kept verbatim so the source/
# target combos behave identically across redesigns.
_LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("Afrikaans", "af"), ("Albanian (Shqip)", "sq"), ("Amharic (አማርኛ)", "am"),
    ("Arabic (العربية)", "ar"), ("Armenian (Հայերեն)", "hy"), ("Azerbaijani (Azərbaycan)", "az"),
    ("Basque (Euskara)", "eu"), ("Belarusian (Беларуская)", "be"), ("Bengali (বাংলা)", "bn"),
    ("Bosnian (Bosanski)", "bs"), ("Bulgarian (Български)", "bg"), ("Burmese (မြန်မာ)", "my"),
    ("Catalan (Català)", "ca"), ("Cebuano", "ceb"), ("Chichewa (Nyanja)", "ny"),
    ("Chinese, Simplified (中文 简体)", "zh-Hans"), ("Chinese, Traditional (中文 繁體)", "zh-Hant"),
    ("Corsican (Corsu)", "co"), ("Croatian (Hrvatski)", "hr"), ("Czech (Čeština)", "cs"),
    ("Danish (Dansk)", "da"), ("Dutch (Nederlands)", "nl"), ("English", "en"),
    ("Esperanto", "eo"), ("Estonian (Eesti)", "et"), ("Filipino (Tagalog)", "tl"),
    ("Finnish (Suomi)", "fi"), ("French (Français)", "fr"), ("Frisian (Frysk)", "fy"),
    ("Galician (Galego)", "gl"), ("Georgian (ქართული)", "ka"), ("German (Deutsch)", "de"),
    ("Greek (Ελληνικά)", "el"), ("Gujarati (ગુજરાતી)", "gu"), ("Haitian Creole", "ht"),
    ("Hausa", "ha"), ("Hawaiian", "haw"), ("Hebrew (עברית)", "he"),
    ("Hindi (हिन्दी)", "hi"), ("Hmong", "hmn"), ("Hungarian (Magyar)", "hu"),
    ("Icelandic (Íslenska)", "is"), ("Igbo", "ig"), ("Indonesian (Bahasa Indonesia)", "id"),
    ("Irish (Gaeilge)", "ga"), ("Italian (Italiano)", "it"), ("Japanese (日本語)", "ja"),
    ("Javanese", "jv"), ("Kannada (ಕನ್ನಡ)", "kn"), ("Kazakh (Қазақ)", "kk"),
    ("Khmer (ភាសាខ្មែរ)", "km"), ("Kinyarwanda", "rw"), ("Korean (한국어)", "ko"),
    ("Kurdish (Kurdî)", "ku"), ("Kyrgyz (Кыргызча)", "ky"), ("Lao (ລາວ)", "lo"),
    ("Latin", "la"), ("Latvian (Latviešu)", "lv"), ("Lithuanian (Lietuvių)", "lt"),
    ("Luxembourgish (Lëtzebuergesch)", "lb"), ("Macedonian (Македонски)", "mk"),
    ("Malagasy", "mg"), ("Malay (Bahasa Melayu)", "ms"), ("Malayalam (മലയാളം)", "ml"),
    ("Maltese (Malti)", "mt"), ("Maori (Māori)", "mi"), ("Marathi (मराठी)", "mr"),
    ("Mongolian (Монгол)", "mn"), ("Nepali (नेपाली)", "ne"), ("Norwegian (Norsk)", "no"),
    ("Odia (Oriya)", "or"), ("Pashto (پښتو)", "ps"), ("Persian (فارسی)", "fa"),
    ("Polish (Polski)", "pl"), ("Portuguese (Português)", "pt"), ("Punjabi (ਪੰਜਾਬੀ)", "pa"),
    ("Romanian (Română)", "ro"), ("Russian (Русский)", "ru"), ("Samoan", "sm"),
    ("Scots Gaelic", "gd"), ("Serbian (Српски)", "sr"), ("Sesotho", "st"), ("Shona", "sn"),
    ("Sindhi (سنڌي)", "sd"), ("Sinhala (සිංහල)", "si"), ("Slovak (Slovenčina)", "sk"),
    ("Slovenian (Slovenščina)", "sl"), ("Somali (Soomaali)", "so"),
    ("Spanish (Español)", "es"), ("Sundanese", "su"), ("Swahili (Kiswahili)", "sw"),
    ("Swedish (Svenska)", "sv"), ("Tajik (Тоҷикӣ)", "tg"), ("Tamil (தமிழ்)", "ta"),
    ("Tatar (Татар)", "tt"), ("Telugu (తెలుగు)", "te"), ("Thai (ไทย)", "th"),
    ("Turkish (Türkçe)", "tr"), ("Turkmen (Türkmen)", "tk"), ("Ukrainian (Українська)", "uk"),
    ("Urdu (اردو)", "ur"), ("Uyghur (ئۇيغۇر)", "ug"), ("Uzbek (Oʻzbek)", "uz"),
    ("Vietnamese (Tiếng Việt)", "vi"), ("Welsh (Cymraeg)", "cy"), ("Xhosa", "xh"),
    ("Yiddish (ייִדיש)", "yi"), ("Yoruba", "yo"), ("Zulu", "zu"),
]

_SOURCE_LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("Auto-detect", ""),
    *_LANGUAGE_OPTIONS,
]


# Voice catalog for Edge TTS — grouped by accent so users can scan.
_VOICE_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("US English", [
        ("Aria", "en-US-AriaNeural"),
        ("Guy", "en-US-GuyNeural"),
        ("Jenny", "en-US-JennyNeural"),
    ]),
    ("UK English", [
        ("Sonia", "en-GB-SoniaNeural"),
        ("Ryan", "en-GB-RyanNeural"),
    ]),
    ("AU English", [
        ("Natasha", "en-AU-NatashaNeural"),
    ]),
]


# ── Helpers (kept from previous impl) ─────────────────────────────────────
class _ComboBox(QComboBox):
    """QComboBox that (1) doesn't change value on scroll-wheel and (2) paints
    its own down-chevron.

    Scroll: default Qt combos cycle their value when you scroll the wheel over
    them — easy to change a setting by accident while scrolling the page. We
    pass the wheel event up to the parent (so the panel scrolls), consuming it
    only when the dropdown popup is open.

    Arrow: Qt's QSS `::down-arrow { image: url(...) }` renders blank for these
    (esp. editable combos), so we draw the chevron ourselves in paintEvent —
    reliable in both themes. Typeahead (editable + completer) still works.
    """

    _ARROW_W = 26  # must match QComboBox::drop-down width in theme.py

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self.view().isVisible():
            super().wheelEvent(event)  # popup open → normal scroll inside it
        else:
            event.ignore()  # bubble up so the scroll area scrolls instead

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        from PySide6.QtGui import QColor, QPainter, QPen

        from transsnip.ui.theme import get_theme
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(p.text_1), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - self._ARROW_W / 2
        cy = self.height() / 2
        # Down chevron: ⌄
        painter.drawLine(int(cx - 4), int(cy - 2), int(cx), int(cy + 2))
        painter.drawLine(int(cx), int(cy + 2), int(cx + 4), int(cy - 2))
        painter.end()


def _make_searchable_lang_combo(options: list[tuple[str, str]]) -> QComboBox:
    combo = _ComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    for label, data in options:
        combo.addItem(label, data)
    completer = combo.completer()
    if completer is not None:
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    return combo


def _select_by_data(combo: QComboBox, data: str) -> None:
    idx = combo.findData(data)
    combo.setCurrentIndex(max(idx, 0))


def _hotkey_to_qt(value: str) -> str:
    """`alt+t` → `Alt+T` for QKeySequenceEdit."""
    return "+".join(p.capitalize() for p in value.split("+") if p)


def _qt_to_hotkey(seq: QKeySequence) -> str:
    """QKeySequence → `keyboard` lib's lowercase + format."""
    return seq.toString(QKeySequence.SequenceFormat.PortableText).lower().replace(" ", "")


# ── SettingsWindow ────────────────────────────────────────────────────────
class SettingsWindow(QWidget):
    """Frameless settings window with 5 tabs.

    Same external API as the old QDialog implementation:
    - `settings_saved` signal fires after successful save
    - public `show()` / `close()` work as expected
    """

    settings_saved = Signal()
    _models_fetched = Signal(list)
    _fetch_error = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(820, 640)
        self.setMinimumSize(720, 540)

        self._settings = load_settings()
        # OpenRouter models fetched this session (persisted on save so the
        # dropdown survives a restart). Seeded from the cached list if present.
        self._fetched_models: list[tuple[str, str]] = [
            (d, i) for d, i in self._settings.translate.openrouter_models if d and i
        ]
        self._models_fetched.connect(self._apply_fetched_models)
        self._fetch_error.connect(self._on_fetch_error)

        self._build_ui()
        self._load_from_model()
        # Re-skin chrome + recolor active tab indicator whenever the theme
        # switches (user picks a different ThemeCard in the Display tab).
        # Without this, the titlebar background, tab strip background, and
        # active tab pill keep their old colors after the global stylesheet
        # already flipped.
        get_theme().mode_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _palette) -> None:
        self._apply_chrome_style()
        # Find the currently active tab and re-style — `_switch_tab` rebuilds
        # the icon at the right color for both active and idle states.
        for tid, btn in zip(
            (m[0] for m in self._tabs_meta), self._tab_buttons
        ):
            if btn.isChecked():
                self._switch_tab(tid)
                break
        self.update()

    # ── Chrome ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self._titlebar = CustomTitlebar(
            "TransSnip · Settings",
            show_minimize=True,
            show_maximize=False,
        )
        self._titlebar.minimize_requested.connect(self.showMinimized)
        self._titlebar.close_requested.connect(self.reject)
        root.addWidget(self._titlebar)

        # Tab strip — horizontal pills with icon + label. QPushButton renders
        # its own setIcon() + setText() (it ignores child layouts), so we
        # set those directly here. Icon color is refreshed in `_switch_tab`
        # based on active state.
        tab_strip = QWidget()
        tab_strip.setObjectName("tabStrip")
        tab_strip.setFixedHeight(46)
        tab_layout = QHBoxLayout(tab_strip)
        tab_layout.setContentsMargins(12, 8, 12, 4)
        tab_layout.setSpacing(4)
        self._tab_buttons: list[QPushButton] = []
        self._tabs_meta = [
            ("translation", "globe", "Translation"),
            ("context", "brain", "Context"),
            ("hotkeys", "keyboard", "Hotkeys"),
            ("display", "eye", "Display"),
            ("voice", "volume", "Voice"),
        ]
        from PySide6.QtCore import QSize
        for tab_id, icon_name, label in self._tabs_meta:
            btn = QPushButton(f"  {label}")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(icons.get_icon(icon_name, color="#a4a9b3", size=13))
            btn.setIconSize(QSize(13, 13))
            btn.setProperty("tabIcon", icon_name)  # stored so _switch_tab can recolor
            btn.clicked.connect(lambda _checked=False, tid=tab_id: self._switch_tab(tid))
            tab_layout.addWidget(btn)
            self._tab_buttons.append(btn)
        tab_layout.addStretch(1)
        root.addWidget(tab_strip)

        # Body — stacked widget of all 5 tab panels.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_tab_translation())
        self._stack.addWidget(self._build_tab_context())
        self._stack.addWidget(self._build_tab_hotkeys())
        self._stack.addWidget(self._build_tab_display())
        self._stack.addWidget(self._build_tab_voice())
        root.addWidget(self._stack, stretch=1)

        # Footer.
        footer = QWidget()
        footer.setObjectName("footer")
        footer.setFixedHeight(52)
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(16, 8, 16, 8)
        self._footer_hint = QLabel("Settings được lưu vào %APPDATA%\\transsnip\\settings.json")
        self._footer_hint.setProperty("hint", True)
        footer_row.addWidget(self._footer_hint)
        footer_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("ghost", True)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._on_save)
        footer_row.addWidget(cancel_btn)
        footer_row.addWidget(save_btn)
        root.addWidget(footer)

        self._apply_chrome_style()
        # Default tab.
        self._switch_tab("translation")

    @staticmethod
    def _wrap_in_scroll(body: QWidget) -> QWidget:
        """Put `body` inside a transparent QScrollArea so long tab content
        scrolls instead of squishing/overlapping.

        Without this, tabs like Display (theme cards + sliders + multiple
        toggles + segmented + more toggles) overflow the window's body
        height — Qt's layout engine compresses the row spacing until
        widgets visually overlap.
        """
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(body)
        return scroll

    def _apply_chrome_style(self) -> None:
        # Local stylesheet for the chrome — body/tab/footer surfaces.
        p = get_theme().palette
        self.setStyleSheet(f"""
            SettingsWindow {{ background: {p.bg_0}; }}
            QWidget#tabStrip {{ background: {p.bg_0}; border-bottom: 1px solid {p.border_1}; }}
            QWidget#footer {{ background: {p.bg_1}; border-top: 1px solid {p.border_1}; }}
            QStackedWidget {{ background: {p.bg_0}; }}
        """)

    def _switch_tab(self, tab_id: str) -> None:
        p = get_theme().palette
        for i, (tid, icon_name, _label) in enumerate(self._tabs_meta):
            active = tid == tab_id
            btn = self._tab_buttons[i]
            btn.setChecked(active)
            # Recolor the icon to match active/idle state — QSS can't reach
            # into the QIcon, so we rebuild it with the right stroke color.
            icon_color = p.accent if active else p.text_2
            btn.setIcon(icons.get_icon(icon_name, color=icon_color, size=13))
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {p.accent_soft}; color: {p.accent}; "
                    f"border: none; border-radius: 7px; padding: 7px 14px 7px 10px; "
                    f"font-size: 12px; font-weight: 600; text-align: left; }}"
                )
                self._stack.setCurrentIndex(i)
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {p.text_2}; "
                    f"border: none; border-radius: 7px; padding: 7px 14px 7px 10px; "
                    f"font-size: 12px; text-align: left; }}"
                    f"QPushButton:hover {{ color: {p.text_1}; background: {p.bg_2}; }}"
                )

    def reject(self) -> None:
        """Close window without saving — mirrors QDialog.reject() name so
        AppController code that previously did `dialog.exec()` still works."""
        self.close()

    def paintEvent(self, event) -> None:
        # Paint frameless background — translucent root needs explicit fill.
        from PySide6.QtGui import QPainter, QBrush, QColor, QPen
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        from PySide6.QtCore import QRectF
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QBrush(QColor(p.bg_0)))
        painter.setPen(QPen(QColor(p.border_2), 1))
        painter.drawRoundedRect(rect, 10, 10)

    # ── Tab: Translation ──────────────────────────────────────────────────

    def _build_tab_translation(self) -> QWidget:
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)

        # Provider section
        layout.addWidget(SectionHead(
            "Provider",
            "Chọn LLM hoặc translation service. Mỗi provider giữ API key riêng "
            "trong Windows Credential Manager.",
        ))
        provider_form = QFormLayout()
        provider_form.setSpacing(12)
        self._provider_combo = _ComboBox()
        for info in PROVIDER_REGISTRY.values():
            self._provider_combo.addItem(info.display_name, info.key)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_form.addRow("Provider:", self._provider_combo)

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("Paste API key…")
        provider_form.addRow("API key:", self._api_key_input)

        self._api_key_hint = QLabel()
        self._api_key_hint.setProperty("hint", True)
        self._api_key_hint.setWordWrap(True)
        provider_form.addRow("", self._api_key_hint)

        self._model_combo = _ComboBox()
        # Prefer the user's previously-fetched catalog; fall back to the small
        # hardcoded starter list on a fresh install.
        for display, model_id in (self._fetched_models or OPENROUTER_MODELS):
            self._model_combo.addItem(display, model_id)
        self._model_row_label = QLabel("Model:")
        model_row = QHBoxLayout()
        model_row.addWidget(self._model_combo, stretch=1)
        self._fetch_models_button = QPushButton("Fetch")
        self._fetch_models_button.setProperty("soft", True)
        self._fetch_models_button.clicked.connect(self._on_fetch_models)
        model_row.addWidget(self._fetch_models_button)
        provider_form.addRow(self._model_row_label, model_row)

        self._test_button = QPushButton("Test connection")
        self._test_button.setProperty("soft", True)
        self._test_button.clicked.connect(self._on_test_clicked)
        provider_form.addRow("", self._test_button)
        layout.addLayout(provider_form)

        # Language section
        layout.addWidget(SectionHead(
            "Ngôn ngữ",
            "Để Auto-detect nếu nguồn thay đổi thường xuyên — providers sẽ tự nhận dạng.",
        ))
        lang_form = QFormLayout()
        lang_form.setSpacing(12)
        self._source_lang_combo = _make_searchable_lang_combo(_SOURCE_LANGUAGE_OPTIONS)
        lang_form.addRow("Nguồn (source):", self._source_lang_combo)
        self._target_lang_combo = _make_searchable_lang_combo(_LANGUAGE_OPTIONS)
        lang_form.addRow("Đích (target):", self._target_lang_combo)
        layout.addLayout(lang_form)

        # Behavior section
        layout.addWidget(SectionHead("Hành vi"))
        self._active_preset_combo = _ComboBox()
        self._active_preset_combo.setToolTip(
            "Preset đang dùng — chỉnh nội dung preset ở tab 'Context'."
        )
        preset_row = QFormLayout()
        preset_row.setSpacing(12)
        preset_row.addRow("Context preset:", self._active_preset_combo)

        # Display mode — how much detail the result popup shows.
        self._display_mode_combo = _ComboBox()
        self._display_mode_combo.addItem("Simple — chỉ bản dịch", "simple")
        self._display_mode_combo.addItem("Standard — bản dịch + phát âm", "standard")
        self._display_mode_combo.addItem("Learning — phân tích từng từ (IPA + nghĩa)", "learning")
        self._display_mode_combo.setToolTip(
            "Learning mode yêu cầu provider LLM (Gemini/Claude/OpenRouter) trả về "
            "phân tích từng từ; Google Free chỉ hiện IPA cho tiếng Anh."
        )
        preset_row.addRow("Chế độ hiển thị:", self._display_mode_combo)
        layout.addLayout(preset_row)

        self._phonetic_toggle = ToggleRow(
            "Học tiếng Anh",
            "Hiện phiên âm IPA + nút phát âm khi source là English.",
        )
        layout.addWidget(self._phonetic_toggle)

        layout.addStretch(1)
        scroll.setWidget(body)
        return scroll

    # ── Tab: Context ──────────────────────────────────────────────────────

    def _build_tab_context(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        layout.addWidget(SectionHead(
            "Presets",
            "Mỗi preset = 1 system prompt + glossary áp dụng cho provider LLM. "
            "Provider không-LLM (Google Free) chỉ dùng glossary.",
        ))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # Left: preset list
        left = QWidget()
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, 0, 0)
        self._preset_list = QListWidget()
        self._preset_working: list[PresetSettings] = []
        self._current_preset_index: int = -1
        self._preset_list.currentRowChanged.connect(self._on_preset_selected)
        left_col.addWidget(self._preset_list, stretch=1)
        list_btns = QHBoxLayout()
        add_btn = QPushButton("Add")
        add_btn.setProperty("soft", True)
        add_btn.clicked.connect(self._on_add_preset)
        del_btn = QPushButton("Delete")
        del_btn.setProperty("soft", True)
        del_btn.clicked.connect(self._on_delete_preset)
        list_btns.addWidget(add_btn)
        list_btns.addWidget(del_btn)
        left_col.addLayout(list_btns)
        splitter.addWidget(left)

        # Right: form
        right = QWidget()
        form = QFormLayout(right)
        form.setSpacing(10)
        self._preset_name_input = QLineEdit()
        self._preset_name_input.editingFinished.connect(self._on_preset_field_changed)
        form.addRow("Tên preset:", self._preset_name_input)
        self._preset_desc_input = QLineEdit()
        self._preset_desc_input.setPlaceholderText("Mô tả ngắn")
        self._preset_desc_input.editingFinished.connect(self._on_preset_field_changed)
        form.addRow("Mô tả:", self._preset_desc_input)
        self._preset_prompt_input = QPlainTextEdit()
        self._preset_prompt_input.setMinimumHeight(120)
        self._preset_prompt_input.setPlaceholderText(
            "System prompt cho LLM — vd: 'You are translating game dialogue. Keep skill names in English.'"
        )
        self._preset_prompt_input.textChanged.connect(self._on_preset_field_changed)
        form.addRow("System prompt:", self._preset_prompt_input)

        glossary_label = QLabel("Glossary:")
        self._preset_glossary_table = QTableWidget(0, 2)
        self._preset_glossary_table.setHorizontalHeaderLabels(["Nguồn", "Đích"])
        self._preset_glossary_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._preset_glossary_table.verticalHeader().setVisible(False)
        self._preset_glossary_table.itemChanged.connect(self._on_preset_field_changed)
        form.addRow(glossary_label, self._preset_glossary_table)
        glossary_btns = QHBoxLayout()
        glossary_btns.addStretch(1)
        add_row_btn = QPushButton("Thêm dòng")
        add_row_btn.setProperty("ghost", True)
        add_row_btn.clicked.connect(self._on_add_glossary_row)
        del_row_btn = QPushButton("Xoá dòng")
        del_row_btn.setProperty("ghost", True)
        del_row_btn.clicked.connect(self._on_delete_glossary_row)
        glossary_btns.addWidget(add_row_btn)
        glossary_btns.addWidget(del_row_btn)
        form.addRow("", glossary_btns)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, stretch=1)
        return body

    # ── Tab: Hotkeys ──────────────────────────────────────────────────────

    def _build_tab_hotkeys(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        layout.addWidget(SectionHead(
            "Global hotkeys",
            "Click vào tổ hợp để gán phím mới. Để trống = tắt action đó. "
            "Hotkey hoạt động kể cả khi TransSnip ẩn dưới tray.",
        ))

        self._hotkey_editors: dict[str, QKeySequenceEdit] = {}
        rows = [
            ("region_translate", "crop", "Region translate", "Snipping-tool style"),
            ("fullscreen_translate", "fullscreen", "Fullscreen translate", "Dịch toàn màn hình hiện tại"),
            ("video_subtitle_translate", "subtitles", "Video subtitle", "Auto-translate phụ đề real-time"),
            ("open_settings", "settings", "Mở Settings", "Mở cửa sổ cài đặt từ bàn phím"),
        ]
        for action_id, icon_name, label, desc in rows:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 12, 8)
            row_layout.setSpacing(12)
            row_layout.addWidget(_HotkeyIcon(icon_name))
            text_col = QVBoxLayout()
            t_lbl = QLabel(label)
            d_lbl = QLabel(desc)
            d_lbl.setProperty("hint", True)
            text_col.addWidget(t_lbl)
            text_col.addWidget(d_lbl)
            row_layout.addLayout(text_col, stretch=1)
            editor = QKeySequenceEdit()
            editor.setMaximumWidth(180)
            self._hotkey_editors[action_id] = editor
            row_layout.addWidget(editor)
            reset_btn = IconButton("refresh", size=24, icon_size=11, tooltip="Reset")
            reset_btn.clicked.connect(lambda _checked=False, aid=action_id: self._on_reset_hotkey(aid))
            row_layout.addWidget(reset_btn)
            layout.addWidget(row)

        # Popup-behaviour toggles ("Click outside để đóng", "Esc đóng overlay")
        # live in the Display tab so all popup/overlay settings are in one place.
        layout.addStretch(1)
        return self._wrap_in_scroll(body)

    def _on_reset_hotkey(self, action_id: str) -> None:
        default = DEFAULT_BINDINGS.get(action_id, "")
        self._hotkey_editors[action_id].setKeySequence(
            QKeySequence(_hotkey_to_qt(default))
        )

    # ── Tab: Display ──────────────────────────────────────────────────────

    def _build_tab_display(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)

        layout.addWidget(SectionHead(
            "Theme",
            "Tự động dùng Windows ColorPrevalence + WallpaperLightTheme.",
        ))
        theme_row = QHBoxLayout()
        theme_row.setSpacing(10)
        self._theme_cards: dict[str, ThemeCard] = {}
        for mode, label in [("dark", "Cobalt Dark"), ("light", "Cobalt Light"), ("auto", "Tự động")]:
            card = ThemeCard(mode, label)
            card.selected.connect(self._on_theme_picked)
            self._theme_cards[mode] = card
            theme_row.addWidget(card)
        theme_row.addStretch(1)
        layout.addLayout(theme_row)

        layout.addWidget(SectionHead("Popup"))
        self._popup_width_slider = Slider(
            minimum=380, maximum=720, value=460,
            min_label="380px", max_label="720px",
            format_readout=lambda v: f"{int(v)} px",
        )
        self._font_scale_slider = Slider(
            minimum=1.0, maximum=3.0, value=2.0,
            min_label="1.0×", max_label="3.0×",
            format_readout=lambda v: f"{v:.1f}×",
        )
        self._subtitle_opacity_slider = Slider(
            minimum=0.2, maximum=1.0, value=0.92,
            min_label="20%", max_label="100%",
            format_readout=lambda v: f"{int(v*100)}%",
        )
        self._subtitle_font_slider = Slider(
            minimum=10, maximum=32, value=15,
            min_label="10pt", max_label="32pt",
            format_readout=lambda v: f"{int(v)}pt",
        )
        form = QFormLayout()
        form.addRow("Kích thước mặc định:", self._popup_width_slider)
        form.addRow("Font scale tối đa:", self._font_scale_slider)
        form.addRow("Độ mờ nền phụ đề video:", self._subtitle_opacity_slider)
        form.addRow("Cỡ chữ phụ đề video:", self._subtitle_font_slider)
        layout.addLayout(form)

        self._click_outside_display = ToggleRow(
            "Click outside để đóng popup",
            "Tắt nếu bạn hay click ra ngoài để copy text từ app khác.",
        )
        self._esc_overlay_toggle = ToggleRow(
            "Esc đóng overlay fullscreen",
            "Bất kỳ click nào trên overlay cũng đóng — phím Esc là tuỳ chọn.",
        )
        self._pin_persist_toggle = ToggleRow("Pin popup mở lại lần dịch sau")
        self._footer_hint_toggle = ToggleRow(
            "Hiện footer hint trong popup",
            "Ẩn dòng 'Esc · Ctrl+C · click vào từ' để gọn hơn.",
        )
        layout.addWidget(self._click_outside_display)
        layout.addWidget(self._esc_overlay_toggle)
        layout.addWidget(self._pin_persist_toggle)
        layout.addWidget(self._footer_hint_toggle)

        # Fullscreen overlay has only one rendering style now (opaque box
        # with white text) — the Subtle / Opaque / Side options have been
        # removed along with the toolbar redesign per user feedback. The
        # corresponding fields are still on `DisplaySettings` for forward
        # compatibility but they aren't surfaced in the UI anymore.
        layout.addStretch(1)
        # Wrap in a scroll area — the theme cards + sliders + toggles are
        # taller than the body height, and without scrolling Qt compresses
        # the inter-widget spacing until the "Popup" section head collides
        # with the theme cards above it.
        return self._wrap_in_scroll(body)

    def _on_theme_picked(self, mode: str) -> None:
        for m, card in self._theme_cards.items():
            card.setActive(m == mode)
        # Live preview — apply immediately so the user sees the change.
        get_theme().set_mode(ThemeMode(mode))

    # ── Tab: Voice ────────────────────────────────────────────────────────

    def _build_tab_voice(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)

        layout.addWidget(SectionHead(
            "Edge TTS",
            "Giọng đọc Microsoft Edge — stream trực tiếp, không cần cài đặt thêm.",
        ))

        self._voice_combo = _ComboBox()
        for group_name, voices in _VOICE_GROUPS:
            for name, voice_id in voices:
                self._voice_combo.addItem(f"{group_name} · {name}", voice_id)
        voice_form = QFormLayout()
        voice_form.addRow("Voice:", self._voice_combo)
        layout.addLayout(voice_form)

        self._rate_slider = Slider(
            minimum=0.5, maximum=2.0, value=1.0,
            min_label="0.5×", max_label="2.0×",
            format_readout=lambda v: f"{v:.1f}×",
        )
        self._volume_slider = Slider(
            minimum=0.0, maximum=1.0, value=0.8,
            min_label="0%", max_label="100%",
            format_readout=lambda v: f"{int(v*100)}%",
        )
        sliders_form = QFormLayout()
        sliders_form.addRow("Tốc độ:", self._rate_slider)
        sliders_form.addRow("Volume:", self._volume_slider)
        layout.addLayout(sliders_form)

        layout.addWidget(SectionHead("Tự động phát âm"))
        self._autoplay_toggle = ToggleRow(
            "Phát âm tự động khi source = English",
            "Nguồn được đọc to ngay khi popup hiển thị bản dịch.",
        )
        self._cache_audio_toggle = ToggleRow(
            "Lưu audio đã đọc vào cache (max 100MB)",
            "Tránh gọi Edge TTS lại cho cùng câu — phát instant lần sau.",
        )
        layout.addWidget(self._autoplay_toggle)
        layout.addWidget(self._cache_audio_toggle)

        layout.addStretch(1)
        return self._wrap_in_scroll(body)

    # ── Load / Save ───────────────────────────────────────────────────────

    def _load_from_model(self) -> None:
        s = self._settings
        # Translation
        _select_by_data(self._provider_combo, s.translate.provider)
        self._refresh_provider_fields(s.translate.provider)
        # Make sure the saved model is selectable even if it isn't in the current
        # list (e.g. picked from a fetched catalog that wasn't re-fetched yet).
        saved_model = s.translate.openrouter_model
        if saved_model and self._model_combo.findData(saved_model) < 0:
            self._model_combo.addItem(saved_model, saved_model)
        _select_by_data(self._model_combo, saved_model)
        _select_by_data(self._source_lang_combo, s.translate.source_lang or "")
        _select_by_data(self._target_lang_combo, s.translate.target_lang)
        _select_by_data(self._display_mode_combo, s.translate.display_mode)
        self._phonetic_toggle.setChecked(s.translate.phonetic_audio_en)

        # Presets
        self._preset_working = [p.model_copy() for p in s.presets]
        if not self._preset_working:
            self._preset_working.append(PresetSettings(name="default"))
        self._refresh_preset_list()
        self._refresh_active_preset_combo()
        active_idx = self._find_preset_index(s.translate.preset_name)
        self._preset_list.setCurrentRow(active_idx)
        ap_idx = self._active_preset_combo.findData(s.translate.preset_name)
        if ap_idx >= 0:
            self._active_preset_combo.setCurrentIndex(ap_idx)

        # Hotkeys
        self._hotkey_editors["region_translate"].setKeySequence(
            QKeySequence(_hotkey_to_qt(s.hotkeys.region_translate))
        )
        self._hotkey_editors["fullscreen_translate"].setKeySequence(
            QKeySequence(_hotkey_to_qt(s.hotkeys.fullscreen_translate))
        )
        self._hotkey_editors["video_subtitle_translate"].setKeySequence(
            QKeySequence(_hotkey_to_qt(s.hotkeys.video_subtitle_translate))
        )
        self._hotkey_editors["open_settings"].setKeySequence(
            QKeySequence(_hotkey_to_qt(s.hotkeys.open_settings))
        )

        # Display
        self._on_theme_picked(s.display.theme_mode)
        self._popup_width_slider.setValue(s.display.popup_default_width)
        self._font_scale_slider.setValue(s.display.popup_font_scale_max)
        self._subtitle_opacity_slider.setValue(s.display.subtitle_bg_opacity)
        self._subtitle_font_slider.setValue(s.display.subtitle_font_pt)
        self._click_outside_display.setChecked(s.display.click_outside_close)
        self._pin_persist_toggle.setChecked(s.display.pin_persist)
        self._footer_hint_toggle.setChecked(s.display.show_footer_hint)
        self._esc_overlay_toggle.setChecked(True)

        # Voice
        _select_by_data(self._voice_combo, s.voice.voice)
        self._rate_slider.setValue(s.voice.rate)
        self._volume_slider.setValue(s.voice.volume)
        self._autoplay_toggle.setChecked(s.voice.autoplay_en)
        self._cache_audio_toggle.setChecked(s.voice.cache_audio)

    def _on_save(self) -> None:
        s = self._settings
        # Translation
        provider_key = self._provider_combo.currentData()
        info = PROVIDER_REGISTRY.get(provider_key)
        if info is not None and info.needs_api_key:
            entered = self._api_key_input.text().strip()
            if entered:
                if not set_api_key(provider_key, entered):
                    QMessageBox.warning(self, "TransSnip", "Không lưu được API key.")
                    return
        s.translate.provider = provider_key
        s.translate.target_lang = self._target_lang_combo.currentData() or "vi"
        src_data = self._source_lang_combo.currentData()
        s.translate.source_lang = src_data if src_data else None
        s.translate.phonetic_audio_en = self._phonetic_toggle.isChecked()
        s.translate.display_mode = self._display_mode_combo.currentData() or "simple"
        if provider_key == "openrouter":
            s.translate.openrouter_model = self._model_combo.currentData()
        # Persist the fetched catalog so the dropdown repopulates next launch.
        if self._fetched_models:
            s.translate.openrouter_models = [[d, i] for d, i in self._fetched_models]
        # Active preset
        active_preset_key = self._active_preset_combo.currentData()
        if active_preset_key:
            s.translate.preset_name = active_preset_key
        # Presets
        self._commit_form_to_current_preset()
        s.presets = self._preset_working

        # Hotkeys
        s.hotkeys = HotkeySettings(
            region_translate=_qt_to_hotkey(self._hotkey_editors["region_translate"].keySequence()),
            fullscreen_translate=_qt_to_hotkey(self._hotkey_editors["fullscreen_translate"].keySequence()),
            video_subtitle_translate=_qt_to_hotkey(self._hotkey_editors["video_subtitle_translate"].keySequence()),
            open_settings=_qt_to_hotkey(self._hotkey_editors["open_settings"].keySequence()),
        )

        # Display
        active_mode = next(
            (m for m, c in self._theme_cards.items() if c._active),
            "dark",
        )
        s.display = DisplaySettings(
            theme_mode=active_mode,
            popup_default_width=int(self._popup_width_slider.value()),
            popup_font_scale_max=self._font_scale_slider.value(),
            click_outside_close=self._click_outside_display.isChecked(),
            pin_persist=self._pin_persist_toggle.isChecked(),
            show_footer_hint=self._footer_hint_toggle.isChecked(),
            subtitle_bg_opacity=self._subtitle_opacity_slider.value(),
            subtitle_font_pt=int(self._subtitle_font_slider.value()),
        )

        # Voice
        s.voice = VoiceSettings(
            voice=self._voice_combo.currentData() or "en-US-AriaNeural",
            rate=self._rate_slider.value(),
            volume=self._volume_slider.value(),
            autoplay_en=self._autoplay_toggle.isChecked(),
            cache_audio=self._cache_audio_toggle.isChecked(),
        )

        save_settings(s)
        self.settings_saved.emit()
        self.close()

    # ── Provider handlers ─────────────────────────────────────────────────

    def _on_provider_changed(self) -> None:
        self._refresh_provider_fields(self._provider_combo.currentData())

    def _refresh_provider_fields(self, provider_key: str) -> None:
        info = PROVIDER_REGISTRY.get(provider_key)
        if info is None:
            return
        is_openrouter = provider_key == "openrouter"
        self._model_combo.setVisible(is_openrouter)
        self._model_row_label.setVisible(is_openrouter)
        self._fetch_models_button.setVisible(is_openrouter)
        if info.needs_api_key:
            self._api_key_input.setEnabled(True)
            has_stored = bool(get_api_key(provider_key))
            placeholder = "(đã lưu — paste key mới để thay)" if has_stored else "Paste API key…"
            self._api_key_input.setPlaceholderText(placeholder)
            self._api_key_input.clear()
            self._api_key_hint.setText(info.api_key_hint)
            self._api_key_hint.show()
        else:
            self._api_key_input.setEnabled(False)
            self._api_key_input.clear()
            self._api_key_input.setPlaceholderText("(provider này không cần API key)")
            self._api_key_hint.hide()

    def _on_test_clicked(self) -> None:
        provider_key = self._provider_combo.currentData()
        info = PROVIDER_REGISTRY.get(provider_key)
        if info is None:
            return
        candidate_key = self._api_key_input.text().strip()
        candidate_model = self._model_combo.currentData() if provider_key == "openrouter" else None
        try:
            kwargs: dict = {}
            if info.needs_api_key and candidate_key:
                kwargs["api_key"] = candidate_key
            if candidate_model:
                kwargs["model"] = candidate_model
            translator = info.factory(**kwargs)  # type: ignore[call-arg]
        except TypeError:
            translator = info.factory()
        try:
            from transsnip.translate.base import TranslationContext
            result = translator.translate(
                "Hello, this is a connection test.",
                TranslationContext(target_lang="vi"),
            )
            QMessageBox.information(
                self, "TransSnip",
                f"OK — {info.display_name}\n\nKết quả:\n{result.translated_text}",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "TransSnip", f"Test thất bại:\n{exc}")

    def _on_fetch_models(self) -> None:
        self._fetch_models_button.setEnabled(False)
        self._fetch_models_button.setText("Đang tải…")
        import threading
        threading.Thread(target=self._fetch_models_worker, daemon=True).start()

    def _fetch_models_worker(self) -> None:
        import json as _json
        import urllib.request
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"User-Agent": "TransSnip/0.2"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            models: list[tuple[str, str]] = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                name = m.get("name") or mid
                pricing = m.get("pricing", {})
                is_free = (
                    str(pricing.get("prompt", "1")) == "0"
                    and str(pricing.get("completion", "1")) == "0"
                )
                tag = " (free)" if is_free else ""
                models.append((f"{name}{tag}", mid))
            models.sort(key=lambda x: (not x[0].endswith("(free)"), x[0].lower()))
            self._models_fetched.emit(models)
        except Exception as exc:  # noqa: BLE001
            self._fetch_error.emit(str(exc))

    @Slot(list)
    def _apply_fetched_models(self, models: list) -> None:
        self._fetch_models_button.setEnabled(True)
        self._fetch_models_button.setText("Fetch")
        # Remember the catalog so _on_save can persist it (survives restart).
        self._fetched_models = [(d, i) for d, i in models]
        current = self._model_combo.currentData()
        self._model_combo.clear()
        for display, model_id in models:
            self._model_combo.addItem(display, model_id)
        idx = self._model_combo.findData(current)
        self._model_combo.setCurrentIndex(max(idx, 0))
        QMessageBox.information(self, "TransSnip", f"Đã tải {len(models)} model.")

    @Slot(str)
    def _on_fetch_error(self, error: str) -> None:
        self._fetch_models_button.setEnabled(True)
        self._fetch_models_button.setText("Fetch")
        QMessageBox.warning(self, "TransSnip", f"Không tải được:\n{error}")

    # ── Preset handlers (Context tab) ─────────────────────────────────────

    def _refresh_preset_list(self) -> None:
        self._preset_list.blockSignals(True)
        self._preset_list.clear()
        for preset in self._preset_working:
            self._preset_list.addItem(preset.name)
        self._preset_list.blockSignals(False)

    def _refresh_active_preset_combo(self) -> None:
        previous = self._active_preset_combo.currentData()
        self._active_preset_combo.blockSignals(True)
        self._active_preset_combo.clear()
        for preset in self._preset_working:
            label = f"{preset.name} — {preset.description}" if preset.description else preset.name
            self._active_preset_combo.addItem(label, preset.name)
        if previous:
            idx = self._active_preset_combo.findData(previous)
            if idx >= 0:
                self._active_preset_combo.setCurrentIndex(idx)
        self._active_preset_combo.blockSignals(False)

    def _find_preset_index(self, name: str) -> int:
        for i, preset in enumerate(self._preset_working):
            if preset.name == name:
                return i
        return 0

    def _on_preset_selected(self, row: int) -> None:
        self._commit_form_to_current_preset()
        self._current_preset_index = row
        if not (0 <= row < len(self._preset_working)):
            return
        self._populate_form(self._preset_working[row])

    def _populate_form(self, preset: PresetSettings) -> None:
        widgets = [self._preset_name_input, self._preset_desc_input,
                   self._preset_prompt_input, self._preset_glossary_table]
        for w in widgets:
            w.blockSignals(True)
        self._preset_name_input.setText(preset.name)
        self._preset_desc_input.setText(preset.description)
        self._preset_prompt_input.setPlainText(preset.system_prompt)
        self._preset_glossary_table.setRowCount(0)
        for src, tgt in preset.glossary.items():
            row = self._preset_glossary_table.rowCount()
            self._preset_glossary_table.insertRow(row)
            self._preset_glossary_table.setItem(row, 0, QTableWidgetItem(src))
            self._preset_glossary_table.setItem(row, 1, QTableWidgetItem(tgt))
        for w in widgets:
            w.blockSignals(False)

    def _commit_form_to_current_preset(self) -> None:
        idx = self._current_preset_index
        if not (0 <= idx < len(self._preset_working)):
            return
        current = self._preset_working[idx]
        new_name = self._preset_name_input.text().strip() or current.name
        for j, other in enumerate(self._preset_working):
            if j != idx and other.name == new_name:
                new_name = current.name
                break
        glossary: dict[str, str] = {}
        for row in range(self._preset_glossary_table.rowCount()):
            src_item = self._preset_glossary_table.item(row, 0)
            tgt_item = self._preset_glossary_table.item(row, 1)
            src = (src_item.text() if src_item else "").strip()
            tgt = (tgt_item.text() if tgt_item else "").strip()
            if src:
                glossary[src] = tgt
        self._preset_working[idx] = PresetSettings(
            name=new_name,
            description=self._preset_desc_input.text().strip(),
            system_prompt=self._preset_prompt_input.toPlainText(),
            glossary=glossary,
        )

    def _on_preset_field_changed(self) -> None:
        self._commit_form_to_current_preset()
        idx = self._current_preset_index
        if 0 <= idx < len(self._preset_working):
            self._preset_list.blockSignals(True)
            item = self._preset_list.item(idx)
            if item is not None:
                item.setText(self._preset_working[idx].name)
            self._preset_list.blockSignals(False)
            self._refresh_active_preset_combo()

    def _on_add_preset(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Preset mới", "Tên preset:", QLineEdit.EchoMode.Normal,
        )
        name = name.strip()
        if not ok or not name:
            return
        if any(p.name == name for p in self._preset_working):
            QMessageBox.warning(self, "TransSnip", f"Đã có preset tên '{name}'.")
            return
        self._commit_form_to_current_preset()
        self._preset_working.append(PresetSettings(name=name))
        self._refresh_preset_list()
        self._refresh_active_preset_combo()
        self._preset_list.setCurrentRow(len(self._preset_working) - 1)

    def _on_delete_preset(self) -> None:
        idx = self._preset_list.currentRow()
        if not (0 <= idx < len(self._preset_working)):
            return
        if len(self._preset_working) == 1:
            QMessageBox.warning(self, "TransSnip", "Phải giữ ít nhất 1 preset.")
            return
        target = self._preset_working[idx]
        reply = QMessageBox.question(
            self, "Xoá preset",
            f"Xoá preset '{target.name}'?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self._preset_working[idx]
        self._current_preset_index = -1
        self._refresh_preset_list()
        self._refresh_active_preset_combo()
        new_idx = min(idx, len(self._preset_working) - 1)
        self._preset_list.setCurrentRow(new_idx)

    def _on_add_glossary_row(self) -> None:
        table = self._preset_glossary_table
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(""))
        table.setItem(row, 1, QTableWidgetItem(""))
        new_item = table.item(row, 0)
        if new_item is not None:
            table.editItem(new_item)

    def _on_delete_glossary_row(self) -> None:
        row = self._preset_glossary_table.currentRow()
        if row >= 0:
            self._preset_glossary_table.removeRow(row)
            self._on_preset_field_changed()


# Helper widget — hotkey row icon
class _HotkeyIcon(QLabel):
    def __init__(self, icon_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self.setFixedSize(32, 32)
        self._refresh()
        get_theme().mode_changed.connect(self._refresh)

    def _refresh(self) -> None:
        p = get_theme().palette
        self.setPixmap(icons.get_pixmap(self._icon_name, color=p.text_2, size=14))
        self.setStyleSheet(
            f"background: {p.bg_2}; border-radius: 6px; padding: 0;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
