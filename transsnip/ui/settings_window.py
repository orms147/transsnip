from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transsnip.config.keyring_store import get_api_key, set_api_key
from transsnip.config.settings import load_settings, save_settings
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

        # --- Translation group ----------------------------------------------------
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

        root.addWidget(translate_group)

        # --- Footer ---------------------------------------------------------------
        # Slot for future tabs: hotkeys, display, voice. For now there's only one.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

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
        save_settings(self._settings)
        self.settings_saved.emit()
        self.accept()
