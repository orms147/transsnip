"""FloatingPopup — Cobalt redesign.

The popup is a state machine with four states matching the design's
`<FloatingPopup state>` prop in `surface-popup.jsx`:
    - "loading"  — skeleton lines while OCR/translate is running
    - "learning" — English source with IPA furigana + 🔊 button
    - "ja-vi"    — generic translated state (any source/target lang)
    - "error"    — failure with inline retry / switch-provider actions

The chrome stays identical across states (brand · drag · status · actions);
only the body content changes. PhoneticSource handles the two-row IPA layout
with per-word click → Edge TTS. Drag is restricted to the dedicated drag
area in the header; selecting text in the body never starts a window move.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transsnip.config.settings import VoiceSettings, ZhStudySettings
from transsnip.display.popup.chinese import ChineseSource
from transsnip.display.popup.constants import (
    _COMMON_LANGS,
    _DEFAULT_HEIGHT,
    _DEFAULT_WIDTH,
    _FONT_MAX_SCALE,
    _FONT_MIN_SCALE,
    _FONT_SOURCE_PT,
    _FONT_TRANSLATION_PT,
    _GAP_FROM_REGION,
    _MARGIN_FROM_EDGE,
    _MIN_HEIGHT,
    _MIN_WIDTH,
    _lang_display_name,
    _truncate,
    _voice_for_lang,
    cjk_font_css,
)
from transsnip.display.popup.dismiss import _OutsideDismissMixin
from transsnip.display.popup.phonetic import (
    _PhoneticSource,
    _WordBreakdown,
)
from transsnip.display.popup.resize import _EdgeResizeMixin
from transsnip.display.popup.widgets import (
    _ErrorPanel,
    _PopupHeader,
    _Skeleton,
)
from transsnip.translate.base import TranslationResult
from transsnip.tts.edge_tts_player import EdgeTTSPlayer
from transsnip.ui.atoms import (
    IconButton,
    KbdSeq,
    LangChip,
)
from transsnip.ui.glass import Glass
from transsnip.ui.theme import get_theme


# ── FloatingPopup (main widget) ───────────────────────────────────────────
class FloatingPopup(_OutsideDismissMixin, _EdgeResizeMixin, QWidget):
    """Region-translate result popup. State machine: loading / source-known /
    translation-done / error. Same widget instance reused across hotkey
    invocations — `show_for_region` resets state.

    See module docstring for the four states and what each renders.
    """

    closed = Signal()
    settings_requested = Signal()
    retry_requested = Signal()
    switch_provider_requested = Signal()
    pin_changed = Signal(bool)
    # (source_lang: str | None, target_lang: str) — user picked a new pair via
    # the chip menus / swap button. AppController persists it and re-translates
    # the cached source text (no re-capture, no re-OCR).
    lang_pair_changed = Signal(object, str)
    # Chinese study: a word in the source was clicked → (word, sentence, translation).
    word_lookup_requested = Signal(str, str, str)

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("FloatingPopupRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._glass = Glass(self)
        self.setMouseTracking(True)

        # Session state
        self._last_region: QRect | None = None
        self._last_translation: str = ""
        self._last_source_text: str = ""
        self._last_source_lang: str | None = None
        self._last_target_lang: str = "vi"
        # Source lang the user *asked* for (None = auto-detect) — distinct from
        # `_last_source_lang`, which reflects what OCR / the provider detected.
        self._requested_source_lang: str | None = None
        self._show_phonetic_active: bool = False
        self._filter_installed = False
        # Whether clicking outside the popup dismisses it (Settings → Display).
        # When pinned (pin button), the popup ignores click-outside / focus-loss
        # auto-close — it stays put until Esc or the close button.
        self._pinned = False
        self._user_resized = False
        self._current_state = "loading"
        self._current_font_scale = 1.0
        # User-controlled text size (header A−/A+). Decoupled from width so
        # dragging the popup wider reflows text instead of zooming it.
        self._user_font_scale = 1.0

        # Resize state
        self._resize_edges = 0
        self._resize_start_geom: QRect | None = None
        self._resize_start_global: QPoint | None = None
        self._edge_cursor_active = False  # True while the ↔/↕ resize cursor is shown

        self._tts_player = EdgeTTSPlayer(self)
        # User voice prefs (Settings → Voice). AppController pushes the real
        # values via set_voice_settings(); defaults keep the popup usable
        # standalone (tests, first run before settings load).
        self._voice_settings = VoiceSettings()
        # Result detail level (Settings → Translation). "standard" adds a 🔊 to
        # read the source aloud even without the learning breakdown.
        self._display_mode = "simple"
        # Chinese study block (pinyin + Hán-Việt per word, clickable).
        self._zh_settings = ZhStudySettings()
        self._zh_active = False

        self._build_ui()
        # On theme switch, re-apply label colors AND repaint the frame. Without
        # re-running _apply_style the translation/source labels keep the OLD
        # palette's color — which after a light↔dark switch matches the new
        # background, making the text invisible until selected.
        get_theme().mode_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _palette=None) -> None:
        self._apply_style()
        self.update()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)  # 1px so paintEvent border doesn't get clipped
        root.setSpacing(0)

        # Header
        self._header = _PopupHeader(self)
        self._header.speak_requested.connect(self._on_speak_sentence)
        self._header.copy_requested.connect(self._on_copy)
        self._header.font_dec_requested.connect(lambda: self._adjust_font(-0.15))
        self._header.font_inc_requested.connect(lambda: self._adjust_font(+0.15))
        self._header.pin_toggled.connect(self._on_pin_toggled)
        self._header.pin_toggled.connect(self.pin_changed.emit)
        self._header.settings_requested.connect(self.settings_requested.emit)
        self._header.close_requested.connect(self.hide_popup)
        root.addWidget(self._header)

        # Body in scroll area (so long translations scroll)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("popupScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._body = QWidget()
        self._body.setObjectName("popupBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 12, 14, 12)
        self._body_layout.setSpacing(12)

        # Body sub-widgets (lazy-built per state).
        self._source_chip = LangChip("", "")
        self._source_chip.set_interactive(True)
        self._source_chip.setToolTip("Đổi ngôn ngữ nguồn")
        self._source_chip.clicked.connect(
            lambda: self._open_lang_menu(self._source_chip, is_source=True)
        )
        self._source_chip.hide()
        self._learning_tag = QLabel("Learning mode")
        self._learning_tag.hide()
        self._source_label = QLabel()  # plain (JA-VI) source
        self._source_label.setWordWrap(True)
        self._source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._source_label.hide()
        self._phonetic = _PhoneticSource()
        self._phonetic.speak_requested.connect(self._on_speak_word)
        self._phonetic.hide()
        # Learning-mode per-word gloss (IPA + meaning + pos). Populated from
        # result.words; shown instead of the plain source when present.
        self._word_breakdown = _WordBreakdown()
        self._word_breakdown.speak_requested.connect(self._on_speak_word)
        self._word_breakdown.hide()
        self._last_words: list = []
        self._chinese = ChineseSource()
        self._chinese.word_clicked.connect(
            lambda w, s: self.word_lookup_requested.emit(w, s, self._last_translation)
        )
        self._chinese.hide()
        self._divider = QFrame()
        self._divider.setFixedHeight(1)
        self._divider.hide()

        self._target_chip = LangChip("VI", "Tiếng Việt")
        self._target_chip.set_interactive(True)
        self._target_chip.setToolTip("Đổi ngôn ngữ đích")
        self._target_chip.clicked.connect(
            lambda: self._open_lang_menu(self._target_chip, is_source=False)
        )
        self._target_chip.hide()
        self._translation_label = QLabel()
        self._translation_label.setWordWrap(True)
        self._translation_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._footer_hint = QWidget()
        self._build_footer_hint()
        self._footer_hint.hide()

        self._skeleton = _Skeleton()
        self._skeleton.hide()
        self._error_panel = _ErrorPanel()
        self._error_panel.retry_requested.connect(self.retry_requested.emit)
        self._error_panel.switch_provider_requested.connect(self.switch_provider_requested.emit)
        self._error_panel.hide()

        # Initial layout: source-section + divider + translation-section
        src_section = QWidget()
        src_layout = QVBoxLayout(src_section)
        src_layout.setContentsMargins(0, 0, 0, 0)
        src_layout.setSpacing(6)
        src_head = QHBoxLayout()
        src_head.setSpacing(6)
        src_head.addWidget(self._source_chip)
        src_head.addWidget(self._learning_tag)
        src_head.addStretch(1)
        src_layout.addLayout(src_head)
        src_layout.addWidget(self._source_label)
        src_layout.addWidget(self._phonetic)
        src_layout.addWidget(self._word_breakdown)
        src_layout.addWidget(self._chinese)

        tx_section = QWidget()
        tx_layout = QVBoxLayout(tx_section)
        tx_layout.setContentsMargins(0, 0, 0, 0)
        tx_layout.setSpacing(6)
        tx_head = QHBoxLayout()
        tx_head.setSpacing(6)
        tx_head.addWidget(self._target_chip)
        # Swap translation direction. Mostly useful when the pair was set
        # backwards (snipped Vietnamese while set to EN→VI) — with an Auto
        # source it swaps using the DETECTED language.
        self._swap_btn = IconButton("swap", size=24, icon_size=13,
                                    tooltip="Đảo chiều dịch")
        self._swap_btn.clicked.connect(self._on_swap_langs)
        self._swap_btn.hide()
        tx_head.addWidget(self._swap_btn)
        tx_head.addStretch(1)
        # Speak the TRANSLATION in a target-language voice (Standard/Learning).
        self._speak_dst_btn = IconButton("volume", size=24, icon_size=13,
                                         tooltip="Nghe bản dịch")
        self._speak_dst_btn.clicked.connect(self._on_speak_translation)
        self._speak_dst_btn.hide()
        tx_head.addWidget(self._speak_dst_btn)
        tx_layout.addLayout(tx_head)
        tx_layout.addWidget(self._translation_label)

        self._body_layout.addWidget(src_section)
        self._body_layout.addWidget(self._divider)
        self._body_layout.addWidget(tx_section)
        self._body_layout.addWidget(self._skeleton)
        self._body_layout.addWidget(self._error_panel)
        self._body_layout.addStretch(1)
        self._body_layout.addWidget(self._footer_hint)

        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, stretch=1)

        self.setMinimumSize(_MIN_WIDTH, _MIN_HEIGHT)
        self._apply_style()
        self._apply_fonts(force=True)

    def _build_footer_hint(self) -> None:
        layout = QHBoxLayout(self._footer_hint)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        self._hint_esc = KbdSeq(["Esc"])
        layout.addWidget(self._hint_esc)
        lbl_esc = QLabel("đóng ·")
        lbl_esc.setProperty("hint", True)
        layout.addWidget(lbl_esc)
        self._hint_ctrl_c = KbdSeq(["Ctrl", "C"])
        layout.addWidget(self._hint_ctrl_c)
        lbl_ctrl_c = QLabel("copy · click vào từ để nghe phát âm")
        lbl_ctrl_c.setProperty("hint", True)
        layout.addWidget(lbl_ctrl_c, stretch=1)
        get_theme().mode_changed.connect(lambda _p: self._apply_footer_style())
        self._footer_hint_labels = [lbl_esc, lbl_ctrl_c]
        self._apply_footer_style()

    def _apply_footer_style(self) -> None:
        p = get_theme().palette
        for lbl in self._footer_hint_labels:
            lbl.setStyleSheet(f"color: {p.text_3}; font-size: 10.5px;")

    # ── Public state API ──────────────────────────────────────────────────

    def show_for_region(self, region: QRect) -> None:
        """Open the popup for a fresh OCR/translate cycle. Resets state."""
        self._last_region = region
        self._last_translation = ""
        self._last_source_text = ""
        self._last_source_lang = None
        self._show_phonetic_active = False
        self._last_words = []
        self._user_resized = False
        self._tts_player.stop()
        self._set_state("loading")
        self._header.set_status("ocr")
        self._header.set_voice_available(False)
        self._position_near(region)
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self._install_event_filter()

    def update_status(self, status: str) -> None:
        """Map old status strings to new state codes."""
        if "OCR" in status:
            self._header.set_status("ocr")
        elif "dịch" in status.lower() or "vision" in status.lower():
            self._header.set_status("translating")

    def update_source(
        self,
        source_text: str,
        *,
        source_lang: str | None = None,
        show_phonetic: bool = False,
        detected: bool = False,
    ) -> None:
        """OCR done — display source text with optional IPA furigana.

        `detected`: `source_lang` came from auto-detection, not Settings — the
        chip says so, so it doesn't read as a changed setting.
        """
        self._last_source_text = source_text
        self._last_source_lang = source_lang
        self._source_detected = detected
        self._show_phonetic_active = show_phonetic and source_lang == "en"
        self._zh_active = False
        if self._zh_settings.enabled and (source_lang or "").lower().startswith("zh"):
            zs = self._zh_settings
            self._zh_active = self._chinese.set_text(
                source_text[:400], scale=self._current_font_scale, show_pinyin=zs.show_pinyin,
                show_hanviet=zs.show_hanviet, tone_colors=zs.tone_colors)
        self._header.set_status("translating")
        truncated = _truncate(source_text)
        self._render_source_block(truncated, source_lang)
        self._set_state("source-known")

    def update_translation(self, result: TranslationResult) -> None:
        """Translation done — populate the target section + footer."""
        if result.source_text and result.source_text != self._last_source_text:
            # Vision provider may produce a different source than OCR; honor it.
            self._last_source_text = result.source_text
            self._render_source_block(
                _truncate(result.source_text), result.source_lang or self._last_source_lang
            )
        elif result.source_lang and result.source_lang != "auto":
            # Same text, but the provider DETECTED the source language — update
            # the chip so an Auto-detect source doesn't sit at "??" forever.
            self._last_source_lang = result.source_lang
            self._source_chip.set_lang(
                result.source_lang.upper(), _lang_display_name(result.source_lang)
            )

        self._last_translation = result.translated_text
        self._translation_label.setText(result.translated_text)
        # Learning mode: if the provider returned a per-word breakdown, render it
        # (it replaces the plain source / phonetic block — see _set_state).
        self._last_words = list(result.words) if result.words else []
        if self._last_words:
            self._word_breakdown.set_words(self._last_words, scale=self._current_font_scale)
        # Reflect the ACTUAL target language on the chip — it was previously
        # left at its hardcoded "VI / Tiếng Việt" init value, so translating to
        # any other language (e.g. ja) showed the wrong label.
        target_lang = result.target_lang or "vi"
        self._last_target_lang = target_lang
        self._target_chip.set_lang(target_lang.upper(), _lang_display_name(target_lang))
        self._target_chip.show()
        self._header.set_status(
            "done",
            provider=result.provider,
            cached=result.cached,
        )
        self._set_state("translation-done")
        self._fit_height_to_content()

        # Autoplay: read the English source aloud when the user enabled it.
        # Gated to English source so a Vietnamese/Japanese popup doesn't blurt
        # out with an English voice unexpectedly.
        if (
            self._voice_settings.autoplay_en
            and (self._last_source_lang or "").lower().startswith("en")
            and self._last_source_text.strip()
        ):
            self._speak(self._last_source_text)

    def retry_translation(self) -> None:
        """Back from the error state to "source shown, translating…" — the
        OCR'd text is kept and only the translation is re-run."""
        self._header.set_status("translating")
        self._set_state("source-known")

    def show_error(self, message: str) -> None:
        self._header.set_status("error")
        self._error_panel.set_error(message)
        self._set_state("error")
        self._fit_height_to_content()     # shrink from a previous long result

    def hide_popup(self) -> None:
        self._remove_event_filter()
        self._tts_player.stop()
        self.hide()
        self.closed.emit()

    # ── State machine helpers ─────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        self._current_state = state
        # Show/hide elements based on state.
        is_loading = state == "loading"
        is_error = state == "error"
        is_source_known = state == "source-known"
        is_done = state == "translation-done"

        self._skeleton.setVisible(is_loading)
        self._error_panel.setVisible(is_error)

        # Source section visible whenever we have content.
        source_visible = (is_source_known or is_done) and bool(self._last_source_text)
        # Learning-mode breakdown takes over the source block once translation
        # is done and the provider returned per-word data.
        has_breakdown = is_done and bool(self._last_words)
        self._source_chip.setVisible(source_visible)
        self._chinese.setVisible(source_visible and self._zh_active)
        if source_visible and self._zh_active:
            # Chinese study block replaces every other source rendering.
            self._learning_tag.setVisible(False)
            self._phonetic.setVisible(False)
            self._word_breakdown.setVisible(False)
            self._source_label.setVisible(False)
            self._header.set_voice_available(True)
        elif has_breakdown:
            self._learning_tag.setVisible(True)
            self._word_breakdown.setVisible(True)
            self._phonetic.setVisible(False)
            self._source_label.setVisible(False)
            self._header.set_voice_available(True)
        elif source_visible and self._show_phonetic_active:
            self._learning_tag.setVisible(True)
            self._phonetic.setVisible(True)
            self._word_breakdown.setVisible(False)
            self._source_label.setVisible(False)
            self._header.set_voice_available(True)
        elif source_visible:
            self._learning_tag.setVisible(False)
            self._phonetic.setVisible(False)
            self._word_breakdown.setVisible(False)
            self._source_label.setVisible(True)
            # Standard mode: offer the speak button (reads the source sentence).
            self._header.set_voice_available(self._display_mode == "standard")
        else:
            self._learning_tag.setVisible(False)
            self._phonetic.setVisible(False)
            self._word_breakdown.setVisible(False)
            self._source_label.setVisible(False)

        # Divider + target section only on done state.
        self._divider.setVisible(is_done and source_visible)
        self._target_chip.setVisible(is_done)
        self._swap_btn.setVisible(is_done)
        # Language switching only makes sense once a result is on screen; while
        # a (re-)translation is in flight the controls stay locked so two
        # workers can't race to fill the popup out of order.
        self._set_lang_controls_enabled(is_done)
        self._translation_label.setVisible(is_done)
        # Speak-translation button: Standard/Learning modes, once there's a result.
        self._speak_dst_btn.setVisible(
            is_done and bool(self._last_translation)
            and self._display_mode in ("standard", "learning")
        )

        # Footer hint only when done and English source.
        self._footer_hint.setVisible(is_done and self._show_phonetic_active)

    def _content_width(self) -> int:
        """Available pixel width for wrapping body content (phonetic rows).

        Uses the scroll viewport once laid out; falls back to the window width
        minus chrome before the first show (viewport width is 0 then).
        """
        vw = self._scroll.viewport().width()
        if vw <= 80:
            vw = self.width() - 36
        return max(120, vw - 28)

    def _render_source_block(self, text: str, source_lang: str | None) -> None:
        # Update chip in place (LangChip.set_lang) — avoids re-parenting which
        # fights with the layout we already placed the chip into.
        code = (source_lang or "auto").upper()
        name = _lang_display_name(source_lang) or ("Auto" if not source_lang else "")
        if source_lang and getattr(self, "_source_detected", False):
            name = f"{name} · auto"
        self._source_chip.set_lang(code, name)
        self._apply_style()  # source font follows the (detected) language
        if self._show_phonetic_active:
            self._phonetic.set_text(
                text, scale=self._current_font_scale, avail_px=self._content_width()
            )
        else:
            self._source_label.setText(text)

    # ── TTS handlers ──────────────────────────────────────────────────────

    def set_voice_settings(self, vs: VoiceSettings) -> None:
        """Push the user's Settings → Voice prefs (voice id, rate, volume, autoplay)."""
        self._voice_settings = vs
        self._tts_player.set_output_device(vs.output_device)

    def set_zh_settings(self, zs: ZhStudySettings) -> None:
        """Push Settings → Học tiếng Trung."""
        self._zh_settings = zs

    def set_display_mode(self, mode: str) -> None:
        """Result detail level: 'simple' / 'standard' / 'learning'."""
        self._display_mode = mode

    # ── In-popup language switching ───────────────────────────────────────

    def set_lang_pair(self, source_lang: str | None, target_lang: str) -> None:
        """Sync the requested pair from settings — AppController calls this on
        each show_for_region so the chip menus reflect the current config."""
        self._requested_source_lang = source_lang
        self._last_target_lang = target_lang or "vi"

    def last_source_text(self) -> str:
        """Full (untruncated) OCR/vision source text of the current session —
        AppController re-submits this on a language change (no re-capture)."""
        return self._last_source_text

    def _open_lang_menu(self, anchor: QWidget, *, is_source: bool) -> None:
        menu = QMenu(self)
        current = self._requested_source_lang if is_source else self._last_target_lang
        if is_source:
            auto = menu.addAction("Auto-detect")
            auto.setCheckable(True)
            auto.setChecked(current is None)
            auto.triggered.connect(lambda: self._pick_lang(None, is_source=True))
            menu.addSeparator()
        for code in _COMMON_LANGS:
            action = menu.addAction(f"{code.upper()}  ·  {_lang_display_name(code)}")
            action.setCheckable(True)
            action.setChecked(code == current)
            action.triggered.connect(
                lambda _checked=False, c=code, s=is_source: self._pick_lang(c, is_source=s)
            )
        menu.addSeparator()
        other = menu.addAction("Ngôn ngữ khác…")
        other.triggered.connect(self.settings_requested.emit)
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))

    def _pick_lang(self, code: str | None, *, is_source: bool) -> None:
        if is_source:
            if code == self._requested_source_lang:
                return
            self._requested_source_lang = code
            self._source_chip.set_lang(
                (code or "auto").upper(), _lang_display_name(code) or "Auto"
            )
        else:
            if not code or code == self._last_target_lang:
                return
            self._last_target_lang = code
            self._target_chip.set_lang(code.upper(), _lang_display_name(code))
        self._emit_lang_pair()

    def _on_swap_langs(self) -> None:
        # Explicit request wins; with an Auto source fall back to what was
        # actually detected, then to English.
        old_source = self._requested_source_lang or self._last_source_lang
        if old_source in (None, "auto"):
            old_source = "en"
        new_source = self._last_target_lang
        if new_source == old_source:
            return
        self._requested_source_lang = new_source
        self._last_target_lang = old_source
        self._source_chip.set_lang(new_source.upper(), _lang_display_name(new_source))
        self._target_chip.set_lang(old_source.upper(), _lang_display_name(old_source))
        self._emit_lang_pair()

    def _emit_lang_pair(self) -> None:
        # Lock the switch controls until the re-translation lands
        # (update_translation → _set_state re-enables) — prevents two
        # in-flight workers racing to fill the popup out of order.
        self._set_lang_controls_enabled(False)
        self._header.set_status("translating")
        self.lang_pair_changed.emit(self._requested_source_lang, self._last_target_lang)

    def _set_lang_controls_enabled(self, enabled: bool) -> None:
        self._source_chip.setEnabled(enabled)
        self._target_chip.setEnabled(enabled)
        self._swap_btn.setEnabled(enabled)

    def set_pinned(self, pinned: bool) -> None:
        """Apply the saved pin state — it persists across snips (and restarts,
        see DisplaySettings.popup_pinned) until the user unpins."""
        self._pinned = pinned
        self._header.set_pinned(pinned)

    def _on_pin_toggled(self, pinned: bool) -> None:
        # Pinned popups survive clicks elsewhere; only Esc / close dismisses them.
        self._pinned = pinned

    def _speak(self, text: str, lang: str | None = None) -> None:
        vs = self._voice_settings
        # The configured voice is an English one (IPA / learning mode); any other
        # known source language gets its own native voice.
        primary = (lang or "en").split("-")[0]
        voice = vs.voice if primary == "en" else _voice_for_lang(lang or "en")
        self._tts_player.speak(text, voice=voice, rate=vs.rate, volume=vs.volume)

    def _on_speak_sentence(self) -> None:
        # Toggle: click the speaker once to play the source, again to stop.
        if self._tts_player.is_active():
            self._tts_player.stop()
            return
        text = (self._last_source_text or "").strip()
        if text:
            self._speak(text, lang=self._last_source_lang)

    def _on_speak_word(self, word: str) -> None:
        # Per-word: always play the clicked word (don't toggle — clicking a
        # different word should switch, not stop). speak() stops any prior clip.
        if word.strip():
            self._speak(word.strip(), lang=self._last_source_lang)

    def _on_speak_translation(self) -> None:
        """Toggle reading the translation aloud (target-language voice)."""
        if self._tts_player.is_active():
            self._tts_player.stop()
            return
        text = (self._last_translation or "").strip()
        if not text:
            return
        vs = self._voice_settings
        self._tts_player.speak(
            text, voice=_voice_for_lang(self._last_target_lang), rate=vs.rate, volume=vs.volume,
        )

    def _on_copy(self) -> None:
        if not self._last_translation:
            return
        QGuiApplication.clipboard().setText(self._last_translation)

    # ── Positioning + sizing ──────────────────────────────────────────────

    def _position_near(self, region: QRect) -> None:
        """Place popup near region, anti-clip against screen bounds.

        Region comes from RegionSelector in logical coords — no DPI math here.
        See doc 90 in mentor docs for the bug that taught us never to /dpr.
        """
        screen = QGuiApplication.screenAt(region.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        # Keep the width (the user may have widened it); the height starts
        # compact every snip — the last result's height (a long translation)
        # would otherwise carry over, e.g. a screen-tall popup for a 2-line
        # error. _fit_height_to_content() grows it to the new content.
        cur_w = self.width()
        w = cur_w if cur_w >= _MIN_WIDTH else _DEFAULT_WIDTH
        h = _DEFAULT_HEIGHT
        w = min(w, available.width() - 2 * _MARGIN_FROM_EDGE)
        h = min(h, available.height() - 2 * _MARGIN_FROM_EDGE)

        x = region.left()
        y = region.bottom() + _GAP_FROM_REGION
        if y + h > available.bottom() - _MARGIN_FROM_EDGE:
            flipped_y = region.top() - h - _GAP_FROM_REGION
            if flipped_y >= available.top() + _MARGIN_FROM_EDGE:
                y = flipped_y
            else:
                y = max(
                    available.top() + _MARGIN_FROM_EDGE,
                    available.bottom() - h - _MARGIN_FROM_EDGE,
                )
        if x + w > available.right() - _MARGIN_FROM_EDGE:
            x = available.right() - w - _MARGIN_FROM_EDGE
        if x < available.left() + _MARGIN_FROM_EDGE:
            x = available.left() + _MARGIN_FROM_EDGE

        self.setGeometry(x, y, w, h)

    def _fit_height_to_content(self) -> None:
        if self._user_resized:
            return
        self._body.adjustSize()
        chrome = self.height() - self._scroll.viewport().height() + 12
        desired = self._body.sizeHint().height() + chrome
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) \
            or QGuiApplication.primaryScreen()
        max_h = (screen.availableGeometry().height() - 2 * _MARGIN_FROM_EDGE) if screen else desired
        new_h = max(_MIN_HEIGHT, min(desired, max_h))
        if abs(new_h - self.height()) <= 2:
            return
        self.resize(self.width(), new_h)

    def _adjust_font(self, delta: float) -> None:
        """Header A−/A+ — change the user text size and re-apply."""
        self._user_font_scale = max(_FONT_MIN_SCALE, min(self._user_font_scale + delta,
                                                         _FONT_MAX_SCALE))
        self._apply_fonts(force=True)
        self._fit_height_to_content()

    def _apply_fonts(self, *, force: bool = False) -> None:
        # Font size is USER-controlled (A−/A+), NOT tied to popup width — so
        # dragging the popup wider reflows the text wider instead of zooming it.
        # We size via STYLESHEET (font-size), not setFont(), because the global
        # theme stylesheet sets a pixel font-size that would override setFont().
        scale = max(_FONT_MIN_SCALE, min(self._user_font_scale, _FONT_MAX_SCALE))
        if not force and abs(scale - self._current_font_scale) < 0.05:
            return
        self._current_font_scale = scale
        self._apply_style()  # re-applies label stylesheets at the new font size
        if self._show_phonetic_active and self._last_source_text:
            self._phonetic.set_text(
                _truncate(self._last_source_text), scale=scale, avail_px=self._content_width()
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Width changed → REFLOW text to the new width (re-pack phonetic rows);
        # do NOT rescale the font. Plain wordWrap labels (source/translation)
        # reflow on their own; only the phonetic table layout needs re-rendering.
        if self._show_phonetic_active and self._last_source_text:
            self._phonetic.set_text(
                _truncate(self._last_source_text),
                scale=self._current_font_scale,
                avail_px=self._content_width(),
            )

    # ── Apply style (text colors, divider, learning tag) ──────────────────

    def _apply_style(self) -> None:
        p = get_theme().palette
        # Font sizes scale with the user's A−/A+ choice (via stylesheet so they
        # win over the global theme's pixel font-size).
        src_pt = max(8, round(_FONT_SOURCE_PT * self._current_font_scale))
        tx_pt = max(9, round(_FONT_TRANSLATION_PT * self._current_font_scale))
        self._divider.setStyleSheet(f"background: {p.border_1};")
        self._source_label.setStyleSheet(
            f"color: {p.text_2}; line-height: 1.55; font-size: {src_pt}pt;"
            + cjk_font_css(getattr(self, "_last_source_lang", None))
        )
        self._translation_label.setStyleSheet(
            f"color: {p.text_1}; line-height: 1.6; font-weight: 600; font-size: {tx_pt}pt;"
            + cjk_font_css(getattr(self, "_last_target_lang", None))
        )
        self._learning_tag.setStyleSheet(
            f"color: {p.accent}; background: {p.accent_soft}; "
            f"padding: 1px 8px; border-radius: 999px; "
            f"font-size: 10px; font-weight: 600; letter-spacing: {p.letter_caps};"
        )

    # ── Drag-from-edge resize, event filter, key handlers ─────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_popup()
            return
        if event.matches(Qt.MatchFlag.MatchExactly) if False else (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_C
        ):
            self._on_copy()
            return
        if event.key() == Qt.Key.Key_Space and self._show_phonetic_active:
            self._on_speak_sentence()
            return
        super().keyPressEvent(event)
