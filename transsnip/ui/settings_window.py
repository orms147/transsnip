from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transsnip.config.keyring_store import get_api_key, set_api_key
from transsnip.config.settings import (
    HotkeySettings,
    PresetSettings,
    load_settings,
    save_settings,
)
from transsnip.hotkeys.manager import DEFAULT_BINDINGS
from transsnip.translate.openrouter import OPENROUTER_MODELS
from transsnip.translate.registry import PROVIDER_REGISTRY

log = logging.getLogger(__name__)

# Comprehensive language list (BCP-47 tags). Sorted alphabetically by the English
# name so the combo's built-in typeahead (press "V" → jump to Vietnamese) and the
# QCompleter contains-match both work intuitively. Covers what Google Translate,
# Gemini, DeepL, and Claude understand — providers will degrade gracefully on tags
# they don't speak.
_LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("Afrikaans", "af"),
    ("Albanian (Shqip)", "sq"),
    ("Amharic (አማርኛ)", "am"),
    ("Arabic (العربية)", "ar"),
    ("Armenian (Հայերեն)", "hy"),
    ("Azerbaijani (Azərbaycan)", "az"),
    ("Basque (Euskara)", "eu"),
    ("Belarusian (Беларуская)", "be"),
    ("Bengali (বাংলা)", "bn"),
    ("Bosnian (Bosanski)", "bs"),
    ("Bulgarian (Български)", "bg"),
    ("Burmese (မြန်မာ)", "my"),
    ("Catalan (Català)", "ca"),
    ("Cebuano", "ceb"),
    ("Chichewa (Nyanja)", "ny"),
    ("Chinese, Simplified (中文 简体)", "zh-Hans"),
    ("Chinese, Traditional (中文 繁體)", "zh-Hant"),
    ("Corsican (Corsu)", "co"),
    ("Croatian (Hrvatski)", "hr"),
    ("Czech (Čeština)", "cs"),
    ("Danish (Dansk)", "da"),
    ("Dutch (Nederlands)", "nl"),
    ("English", "en"),
    ("Esperanto", "eo"),
    ("Estonian (Eesti)", "et"),
    ("Filipino (Tagalog)", "tl"),
    ("Finnish (Suomi)", "fi"),
    ("French (Français)", "fr"),
    ("Frisian (Frysk)", "fy"),
    ("Galician (Galego)", "gl"),
    ("Georgian (ქართული)", "ka"),
    ("German (Deutsch)", "de"),
    ("Greek (Ελληνικά)", "el"),
    ("Gujarati (ગુજરાતી)", "gu"),
    ("Haitian Creole", "ht"),
    ("Hausa", "ha"),
    ("Hawaiian", "haw"),
    ("Hebrew (עברית)", "he"),
    ("Hindi (हिन्दी)", "hi"),
    ("Hmong", "hmn"),
    ("Hungarian (Magyar)", "hu"),
    ("Icelandic (Íslenska)", "is"),
    ("Igbo", "ig"),
    ("Indonesian (Bahasa Indonesia)", "id"),
    ("Irish (Gaeilge)", "ga"),
    ("Italian (Italiano)", "it"),
    ("Japanese (日本語)", "ja"),
    ("Javanese", "jv"),
    ("Kannada (ಕನ್ನಡ)", "kn"),
    ("Kazakh (Қазақ)", "kk"),
    ("Khmer (ភាសាខ្មែរ)", "km"),
    ("Kinyarwanda", "rw"),
    ("Korean (한국어)", "ko"),
    ("Kurdish (Kurdî)", "ku"),
    ("Kyrgyz (Кыргызча)", "ky"),
    ("Lao (ລາວ)", "lo"),
    ("Latin", "la"),
    ("Latvian (Latviešu)", "lv"),
    ("Lithuanian (Lietuvių)", "lt"),
    ("Luxembourgish (Lëtzebuergesch)", "lb"),
    ("Macedonian (Македонски)", "mk"),
    ("Malagasy", "mg"),
    ("Malay (Bahasa Melayu)", "ms"),
    ("Malayalam (മലയാളം)", "ml"),
    ("Maltese (Malti)", "mt"),
    ("Maori (Māori)", "mi"),
    ("Marathi (मराठी)", "mr"),
    ("Mongolian (Монгол)", "mn"),
    ("Nepali (नेपाली)", "ne"),
    ("Norwegian (Norsk)", "no"),
    ("Odia (Oriya)", "or"),
    ("Pashto (پښتو)", "ps"),
    ("Persian (فارسی)", "fa"),
    ("Polish (Polski)", "pl"),
    ("Portuguese (Português)", "pt"),
    ("Punjabi (ਪੰਜਾਬੀ)", "pa"),
    ("Romanian (Română)", "ro"),
    ("Russian (Русский)", "ru"),
    ("Samoan", "sm"),
    ("Scots Gaelic", "gd"),
    ("Serbian (Српски)", "sr"),
    ("Sesotho", "st"),
    ("Shona", "sn"),
    ("Sindhi (سنڌي)", "sd"),
    ("Sinhala (සිංහල)", "si"),
    ("Slovak (Slovenčina)", "sk"),
    ("Slovenian (Slovenščina)", "sl"),
    ("Somali (Soomaali)", "so"),
    ("Spanish (Español)", "es"),
    ("Sundanese", "su"),
    ("Swahili (Kiswahili)", "sw"),
    ("Swedish (Svenska)", "sv"),
    ("Tajik (Тоҷикӣ)", "tg"),
    ("Tamil (தமிழ்)", "ta"),
    ("Tatar (Татар)", "tt"),
    ("Telugu (తెలుగు)", "te"),
    ("Thai (ไทย)", "th"),
    ("Turkish (Türkçe)", "tr"),
    ("Turkmen (Türkmen)", "tk"),
    ("Ukrainian (Українська)", "uk"),
    ("Urdu (اردو)", "ur"),
    ("Uyghur (ئۇيغۇر)", "ug"),
    ("Uzbek (Oʻzbek)", "uz"),
    ("Vietnamese (Tiếng Việt)", "vi"),
    ("Welsh (Cymraeg)", "cy"),
    ("Xhosa", "xh"),
    ("Yiddish (ייִדיש)", "yi"),
    ("Yoruba", "yo"),
    ("Zulu", "zu"),
]

# Source language options — same list as targets, prefixed with "Auto-detect".
# Auto means: Windows OCR uses user profile languages, LLM providers auto-detect
# from the source text.
_SOURCE_LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("Auto-detect", ""),
    *_LANGUAGE_OPTIONS,
]


def _make_searchable_lang_combo(options: list[tuple[str, str]]) -> QComboBox:
    """Build a language combo with both keyboard typeahead AND substring search.

    The combo is editable so the user can type to filter, but `NoInsert` policy
    keeps them inside the predefined list. The completer matches anywhere in the
    label, so typing "viet" finds "Vietnamese (Tiếng Việt)" even though the label
    doesn't start with "Viet" — useful for searching by the native-script name too.
    """
    combo = QComboBox()
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
    """Convert the `keyboard` library's format ("ctrl+shift+t") to Qt's
    ("Ctrl+Shift+T") so we can hand it to `QKeySequence(...)`.

    Qt uses Title-Case modifier names. `keyboard` uses lowercase. The actual
    key letter (last token) is upcased by Qt itself, but we title-case the
    whole thing to be safe.
    """
    if not value:
        return ""
    parts = [p.strip() for p in value.split("+") if p.strip()]
    # Map keyboard-lib aliases to Qt-friendly names. Most modifiers match
    # after capitalize(); a few common single-keys (esc, space) too.
    aliases = {
        "esc": "Escape",
        "space": "Space",
        "return": "Return",
        "enter": "Return",
        "tab": "Tab",
        "backspace": "Backspace",
    }
    return "+".join(aliases.get(p.lower(), p.capitalize()) for p in parts)


def _qt_to_hotkey(seq: "QKeySequence") -> str:
    """Inverse of `_hotkey_to_qt`. Returns "" if the sequence is empty (user
    cleared the editor → action disabled)."""
    text = seq.toString(QKeySequence.SequenceFormat.PortableText).strip()
    if not text:
        return ""
    # Qt may give us "Ctrl+Shift+T"; the `keyboard` library wants
    # "ctrl+shift+t". Lowercasing the whole string is enough — modifier
    # aliases coincide and the key letter is case-insensitive there.
    return text.lower()


class SettingsWindow(QDialog):
    """Modal settings dialog. Emits `settings_saved` after a successful save so
    the AppController can rebuild its pipeline.
    """

    settings_saved = Signal()
    _models_fetched = Signal(list)   # emitted from fetch thread with model list
    _fetch_error = Signal(str)       # emitted from fetch thread on failure

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TransSnip — Settings")
        self.setMinimumWidth(480)
        # Behave like a normal window in the taskbar so users can find it again
        # if they alt-tab away mid-edit.
        self.setWindowFlag(Qt.WindowType.Tool, False)

        self._settings = load_settings()
        self._models_fetched.connect(self._apply_fetched_models)
        self._fetch_error.connect(self._on_fetch_error)
        self._build_ui()
        self._load_from_model()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_translation_tab(), "Translation")
        tabs.addTab(self._build_context_tab(), "Context preset")
        tabs.addTab(self._build_hotkeys_tab(), "Hotkeys")
        # Future tabs: Display, Voice. Add via tabs.addTab(...).
        root.addWidget(tabs)

        # --- Footer ---------------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_translation_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)

        translate_group = QGroupBox("Translation")
        form = QFormLayout(translate_group)

        self._provider_combo = QComboBox()
        for info in PROVIDER_REGISTRY.values():
            self._provider_combo.addItem(info.display_name, info.key)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider:", self._provider_combo)

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("Paste API key…")
        form.addRow("API key:", self._api_key_input)

        self._api_key_hint = QLabel()
        self._api_key_hint.setWordWrap(True)
        self._api_key_hint.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", self._api_key_hint)

        self._model_combo = QComboBox()
        self._model_combo.setSizePolicy(
            self._model_combo.sizePolicy().horizontalPolicy(),
            self._model_combo.sizePolicy().verticalPolicy(),
        )
        for display, model_id in OPENROUTER_MODELS:
            self._model_combo.addItem(display, model_id)
        self._model_row_label = QLabel("Model:")

        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        model_row.addWidget(self._model_combo, stretch=1)
        self._fetch_models_button = QPushButton("↻ Fetch models")
        self._fetch_models_button.setToolTip("Tải danh sách model mới nhất từ openrouter.ai")
        self._fetch_models_button.clicked.connect(self._on_fetch_models)
        model_row.addWidget(self._fetch_models_button)
        form.addRow(self._model_row_label, model_row)

        self._test_button = QPushButton("Test connection")
        self._test_button.clicked.connect(self._on_test_clicked)
        form.addRow("", self._test_button)

        self._source_lang_combo = _make_searchable_lang_combo(_SOURCE_LANGUAGE_OPTIONS)
        form.addRow("Ngôn ngữ nguồn:", self._source_lang_combo)

        self._target_lang_combo = _make_searchable_lang_combo(_LANGUAGE_OPTIONS)
        form.addRow("Dịch sang:", self._target_lang_combo)

        # Active context preset — populated from settings.presets in
        # `_reload_active_preset_combo`. Editing the preset's content happens
        # in the Context tab; this combo just picks which one to apply.
        self._active_preset_combo = QComboBox()
        self._active_preset_combo.setToolTip(
            "Preset đang dùng — chỉnh nội dung preset ở tab 'Context preset'."
        )
        form.addRow("Context preset:", self._active_preset_combo)

        layout.addWidget(translate_group)
        layout.addStretch(1)
        return tab

    def _build_context_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "Mỗi preset là một bộ chỉ thị (system prompt) + glossary áp dụng cho "
            "provider LLM. Provider không-LLM (Google Free) chỉ dùng glossary "
            "qua post-process replace, bỏ qua system prompt."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: gray; font-size: 11px;")
        outer.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left: list of presets + add/delete buttons ------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._preset_list = QListWidget()
        # Working copy of settings.presets — committed to settings on Save.
        # Editing here without a working copy would lose changes on Cancel.
        self._preset_working: list[PresetSettings] = []
        self._current_preset_index: int = -1
        self._preset_list.currentRowChanged.connect(self._on_preset_selected)
        left_layout.addWidget(self._preset_list, stretch=1)

        list_btns = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._on_add_preset)
        del_btn = QPushButton("− Delete")
        del_btn.clicked.connect(self._on_delete_preset)
        list_btns.addWidget(add_btn)
        list_btns.addWidget(del_btn)
        left_layout.addLayout(list_btns)
        splitter.addWidget(left)

        # --- Right: edit form for the selected preset --------------------------
        right = QWidget()
        right_layout = QFormLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._preset_name_input = QLineEdit()
        self._preset_name_input.editingFinished.connect(self._on_preset_field_changed)
        right_layout.addRow("Tên preset:", self._preset_name_input)

        self._preset_desc_input = QLineEdit()
        self._preset_desc_input.setPlaceholderText("Mô tả ngắn (hiển thị trong combo)")
        self._preset_desc_input.editingFinished.connect(self._on_preset_field_changed)
        right_layout.addRow("Mô tả:", self._preset_desc_input)

        self._preset_prompt_input = QPlainTextEdit()
        self._preset_prompt_input.setPlaceholderText(
            "System prompt cho LLM provider — vd: 'You are translating game "
            "dialogue. Keep skill names in English.'"
        )
        self._preset_prompt_input.setMinimumHeight(120)
        self._preset_prompt_input.textChanged.connect(self._on_preset_field_changed)
        right_layout.addRow("System prompt:", self._preset_prompt_input)

        # Glossary table: 2 columns (source → target). Adding/removing rows via
        # explicit buttons keeps editing predictable — QTableWidget has tricky
        # edit-on-tab semantics that confuse novice users otherwise.
        glossary_label = QLabel("Glossary:")
        self._preset_glossary_table = QTableWidget(0, 2)
        self._preset_glossary_table.setHorizontalHeaderLabels(["Nguồn", "Đích"])
        self._preset_glossary_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._preset_glossary_table.verticalHeader().setVisible(False)
        self._preset_glossary_table.itemChanged.connect(self._on_preset_field_changed)
        right_layout.addRow(glossary_label, self._preset_glossary_table)

        glossary_btns = QHBoxLayout()
        add_row_btn = QPushButton("+ Thêm dòng")
        add_row_btn.clicked.connect(self._on_add_glossary_row)
        del_row_btn = QPushButton("− Xoá dòng đã chọn")
        del_row_btn.clicked.connect(self._on_delete_glossary_row)
        glossary_btns.addStretch(1)
        glossary_btns.addWidget(add_row_btn)
        glossary_btns.addWidget(del_row_btn)
        right_layout.addRow("", glossary_btns)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, stretch=1)
        return tab

    def _build_hotkeys_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "Click vào ô bên cạnh action rồi bấm tổ hợp phím mới (vd Ctrl+Shift+T). "
            "Để Reset về mặc định, bấm nút Reset. Để trống = tắt hotkey đó."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: gray; font-size: 11px;")
        outer.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)

        # action_id → (QKeySequenceEdit, reset_button) so save/reset/load can
        # iterate without 3 separate attributes per action.
        self._hotkey_editors: dict[str, QKeySequenceEdit] = {}

        # Display labels for each action. The action_ids must match
        # DEFAULT_BINDINGS keys exactly so apply_from_settings can find them.
        action_labels = [
            ("region_translate", "Region translate (snipping):"),
            ("fullscreen_translate", "Full-screen translate:"),
            ("video_subtitle_translate", "Video subtitle (Phase 2):"),
        ]

        for action_id, label in action_labels:
            editor = QKeySequenceEdit()
            # Limit to a single key combo — the `keyboard` library doesn't
            # support multi-step chord sequences (vim-style), and accidentally
            # allowing them would silently fail at bind time.
            editor.setMaximumSequenceLength(1)
            self._hotkey_editors[action_id] = editor

            reset_btn = QPushButton("Reset")
            reset_btn.setToolTip(f"Reset về mặc định ({DEFAULT_BINDINGS[action_id]})")
            reset_btn.clicked.connect(
                lambda _checked=False, aid=action_id: self._reset_hotkey(aid)
            )

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(editor, stretch=1)
            row.addWidget(reset_btn)
            form.addRow(label, row)

        outer.addLayout(form)
        outer.addStretch(1)
        return tab

    def _reset_hotkey(self, action_id: str) -> None:
        editor = self._hotkey_editors.get(action_id)
        if editor is None:
            return
        default = DEFAULT_BINDINGS[action_id]
        editor.setKeySequence(QKeySequence(_hotkey_to_qt(default)))

    def _load_hotkeys_from_settings(self) -> None:
        for action_id, editor in self._hotkey_editors.items():
            value = getattr(self._settings.hotkeys, action_id, "") or ""
            editor.setKeySequence(QKeySequence(_hotkey_to_qt(value)) if value else QKeySequence())

    def _load_from_model(self) -> None:
        provider_key = self._settings.translate.provider
        idx = self._provider_combo.findData(provider_key)
        self._provider_combo.setCurrentIndex(max(idx, 0))
        self._refresh_provider_fields(provider_key)

        saved_model = getattr(self._settings.translate, "openrouter_model", None) or ""
        idx = self._model_combo.findData(saved_model)
        self._model_combo.setCurrentIndex(max(idx, 0))

        # Empty string represents "Auto-detect" in the combo box but is stored
        # as None in the settings model.
        _select_by_data(self._source_lang_combo, self._settings.translate.source_lang or "")
        _select_by_data(self._target_lang_combo, self._settings.translate.target_lang)

        # Load presets into the working copy and refresh both the list and
        # the active-preset combo.
        self._preset_working = [p.model_copy() for p in self._settings.presets]
        if not self._preset_working:
            # Defensive: a corrupted settings.json with empty presets gets a
            # blank "default" so the user has something to start from.
            self._preset_working.append(PresetSettings(name="default"))
        self._refresh_preset_list()
        self._refresh_active_preset_combo()
        # Initial selection on the Context tab + sync active combo.
        active_name = self._settings.translate.preset_name
        active_idx = self._find_preset_index(active_name)
        self._preset_list.setCurrentRow(active_idx)
        active_combo_idx = self._active_preset_combo.findData(active_name)
        if active_combo_idx >= 0:
            self._active_preset_combo.setCurrentIndex(active_combo_idx)

        # Load hotkey editors from current settings.
        self._load_hotkeys_from_settings()

    # ── Context preset handlers ─────────────────────────────────────────────

    def _refresh_preset_list(self) -> None:
        """Rebuild the QListWidget from `_preset_working`. Caller is responsible
        for any selection restoration afterwards."""
        self._preset_list.blockSignals(True)
        self._preset_list.clear()
        for preset in self._preset_working:
            self._preset_list.addItem(preset.name)
        self._preset_list.blockSignals(False)

    def _refresh_active_preset_combo(self) -> None:
        """Sync the Translation-tab combo with `_preset_working` while keeping
        the user's current pick (by name) if it still exists."""
        previous = self._active_preset_combo.currentData()
        self._active_preset_combo.blockSignals(True)
        self._active_preset_combo.clear()
        for preset in self._preset_working:
            label = preset.name
            if preset.description:
                label = f"{preset.name} — {preset.description}"
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
        return 0  # fall back to first preset if name not found

    def _on_preset_selected(self, row: int) -> None:
        # Commit the currently-edited form back to the model before switching,
        # otherwise edits are lost. This mirrors the "edit one row at a time"
        # idiom common in master-detail UIs.
        self._commit_form_to_current_preset()
        self._current_preset_index = row
        if not (0 <= row < len(self._preset_working)):
            self._clear_form()
            return
        preset = self._preset_working[row]
        self._populate_form(preset)

    def _populate_form(self, preset: PresetSettings) -> None:
        # Block signals so populating the form doesn't fire field-changed →
        # _on_preset_field_changed → mutate working copy with stale data.
        widgets = [
            self._preset_name_input, self._preset_desc_input,
            self._preset_prompt_input, self._preset_glossary_table,
        ]
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

    def _clear_form(self) -> None:
        self._preset_name_input.clear()
        self._preset_desc_input.clear()
        self._preset_prompt_input.clear()
        self._preset_glossary_table.setRowCount(0)

    def _commit_form_to_current_preset(self) -> None:
        idx = self._current_preset_index
        if not (0 <= idx < len(self._preset_working)):
            return
        preset = self._preset_working[idx]
        new_name = self._preset_name_input.text().strip() or preset.name
        # Reject duplicate names against OTHER presets (keep current as-is).
        for j, other in enumerate(self._preset_working):
            if j != idx and other.name == new_name:
                # Silently keep the old name — the user will see the form
                # still shows the original. Showing a dialog on every focus-out
                # would be obnoxious; we'll catch the conflict again at Save.
                new_name = preset.name
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
        # Cheap: just re-commit form to working copy and refresh the visible
        # name in the list + combo. We don't write to settings.json until Save.
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
            f"Xoá preset '{target.name}'? (chưa được lưu xuống disk cho tới khi bấm Save)",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self._preset_working[idx]
        self._current_preset_index = -1  # avoid stale commits
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
        table = self._preset_glossary_table
        row = table.currentRow()
        if row < 0:
            return
        table.removeRow(row)
        self._on_preset_field_changed()

    def _on_provider_changed(self) -> None:
        provider_key = self._provider_combo.currentData()
        self._refresh_provider_fields(provider_key)

    def _refresh_provider_fields(self, provider_key: str) -> None:
        info = PROVIDER_REGISTRY.get(provider_key)
        if info is None:
            return

        is_openrouter = provider_key == "openrouter"
        self._model_combo.setVisible(is_openrouter)
        self._model_row_label.setVisible(is_openrouter)

        if info.needs_api_key:
            self._api_key_input.setEnabled(True)
            has_stored = bool(get_api_key(provider_key))
            if has_stored:
                # Key already saved — show masked placeholder, don't expose plaintext.
                # User only needs to type here if they want to replace the key.
                self._api_key_input.clear()
                self._api_key_input.setPlaceholderText("(đã lưu — paste key mới để thay)")
            else:
                self._api_key_input.clear()
                self._api_key_input.setPlaceholderText("Paste API key…")
            self._api_key_hint.setText(info.api_key_hint)
            self._api_key_hint.show()
            self._test_button.show()
        else:
            self._api_key_input.setEnabled(False)
            self._api_key_input.clear()
            self._api_key_input.setPlaceholderText("(provider này không cần API key)")
            self._api_key_hint.hide()
            self._test_button.show()

    def _on_test_clicked(self) -> None:
        provider_key = self._provider_combo.currentData()
        info = PROVIDER_REGISTRY.get(provider_key)
        if info is None:
            return
        # Honor key and model currently shown in UI, not what's saved to disk.
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
            # Factory doesn't accept kwargs (e.g. GoogleTranslateFree)
            translator = info.factory()

        try:
            from transsnip.translate.base import TranslationContext
            result = translator.translate(
                "Hello, this is a connection test.",
                TranslationContext(target_lang="vi"),
            )
            QMessageBox.information(
                self,
                "TransSnip",
                f"OK — {info.display_name} hoạt động.\n\nKết quả:\n{result.translated_text}",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "TransSnip",
                f"Test thất bại với {info.display_name}:\n\n{exc}",
            )

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
                headers={"User-Agent": "TransSnip/0.1"},
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

            # Sort: free first, then alphabetical by name
            models.sort(key=lambda x: (not x[0].endswith("(free)"), x[0].lower()))
            self._models_fetched.emit(models)
        except Exception as exc:
            self._fetch_error.emit(str(exc))

    @Slot(list)
    def _apply_fetched_models(self, models: list) -> None:
        self._fetch_models_button.setEnabled(True)
        self._fetch_models_button.setText("↻ Fetch models")

        current = self._model_combo.currentData()
        self._model_combo.clear()
        for display, model_id in models:
            self._model_combo.addItem(display, model_id)

        idx = self._model_combo.findData(current)
        self._model_combo.setCurrentIndex(max(idx, 0))

        QMessageBox.information(
            self, "TransSnip",
            f"Đã tải {len(models)} model từ OpenRouter.",
        )

    @Slot(str)
    def _on_fetch_error(self, error: str) -> None:
        self._fetch_models_button.setEnabled(True)
        self._fetch_models_button.setText("↻ Fetch models")
        QMessageBox.warning(self, "TransSnip", f"Không tải được model list:\n{error}")

    def _on_save(self) -> None:
        provider_key = self._provider_combo.currentData()
        target_lang = self._target_lang_combo.currentData()
        source_data = self._source_lang_combo.currentData()
        # Combo carries "" for "Auto-detect" — store as None so downstream code
        # branches on truthiness rather than empty-string equality.
        source_lang = source_data if source_data else None
        info = PROVIDER_REGISTRY.get(provider_key)

        # Persist the API key first (keyring), then the rest of settings (JSON).
        if info is not None and info.needs_api_key:
            entered = self._api_key_input.text().strip()
            if entered:
                if not set_api_key(provider_key, entered):
                    QMessageBox.warning(
                        self,
                        "TransSnip",
                        "Không lưu được API key vào Windows Credential Manager.",
                    )
                    return

        self._settings.translate.provider = provider_key
        self._settings.translate.target_lang = target_lang
        self._settings.translate.source_lang = source_lang
        if provider_key == "openrouter":
            self._settings.translate.openrouter_model = self._model_combo.currentData()

        # Flush any in-progress preset edits to the working copy before save —
        # the focus-out commits only fire when the user moves focus, and they
        # might press Save while still inside a field.
        self._commit_form_to_current_preset()

        # Final duplicate-name check on Save (we silently rejected duplicates
        # while editing — surface them here so the user can fix them).
        seen: set[str] = set()
        for preset in self._preset_working:
            if preset.name in seen:
                QMessageBox.warning(
                    self, "TransSnip",
                    f"Preset trùng tên '{preset.name}'. Đổi tên trước khi lưu.",
                )
                return
            seen.add(preset.name)

        self._settings.presets = self._preset_working
        active_preset_name = self._active_preset_combo.currentData() or "default"
        # If the active preset got deleted/renamed, fall back to the first.
        if active_preset_name not in seen and self._preset_working:
            active_preset_name = self._preset_working[0].name
        self._settings.translate.preset_name = active_preset_name

        # Hotkeys: read each editor + validate no two actions share the same
        # combo. Two hotkeys bound to the same combo would have undefined
        # behavior in the `keyboard` library (last bind wins, silently).
        new_hotkeys: dict[str, str] = {}
        seen_combos: dict[str, str] = {}
        for action_id, editor in self._hotkey_editors.items():
            combo = _qt_to_hotkey(editor.keySequence())
            if combo and combo in seen_combos:
                QMessageBox.warning(
                    self, "TransSnip",
                    f"Hotkey '{combo}' đang gán cho cả "
                    f"'{seen_combos[combo]}' và '{action_id}'. Đổi 1 trong 2.",
                )
                return
            if combo:
                seen_combos[combo] = action_id
            new_hotkeys[action_id] = combo
        for action_id, combo in new_hotkeys.items():
            setattr(self._settings.hotkeys, action_id, combo)

        save_settings(self._settings)
        self.settings_saved.emit()
        self.accept()
