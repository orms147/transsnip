from __future__ import annotations

import logging
import re
from datetime import datetime

from PIL import Image
from PySide6.QtCore import QObject, QRect, QThreadPool, QTimer, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from transsnip.capture.region_selector import RegionSelector
from transsnip.capture.screen import active_monitor_logical_rect, capture_rect
from transsnip.config.history import HistoryEntry, HistoryStore
from transsnip.config.settings import Settings, get_preset, load_settings
from transsnip.display.floating_popup import FloatingPopup
from transsnip.display.inline_overlay import InlineOverlay
from transsnip.display.subtitle_bar import SubtitleBar
from transsnip.modes.video_subtitle import VideoSubtitleController
from transsnip.ocr.base import OCRBlock, OCRResult
from transsnip.ocr.registry import OCRPipeline
from transsnip.ocr.registry import default_pipeline as default_ocr_pipeline
from transsnip.ocr.segment import segment_english_runon
from transsnip.ocr.worker import OCRWorker
from transsnip.translate.base import TranslationContext, TranslationResult
from transsnip.translate.registry import TranslationPipeline, build_pipeline
from transsnip.translate.worker import TranslationWorker, VisionWorker
from transsnip.tray.tray_icon import TrayController
from transsnip.ui.settings_window import SettingsWindow

log = logging.getLogger(__name__)

# Tiny delay between hiding the region overlay and grabbing pixels. Without it,
# the OS may still be compositing the (now-hidden) overlay into the next frame.
_CAPTURE_DELAY_MS = 80


class AppController(QObject):
    """Top-level orchestrator. Maps hotkey events to mode flows.

    Owns the long-lived UI / pipeline pieces. Tray icon and HotkeyManager are
    injected — main() builds them and wires the signals in so this controller
    doesn't reach back up to construct app-level singletons.
    """

    def __init__(
        self,
        app: QApplication,
        tray: TrayController,
        *,
        ocr_pipeline: OCRPipeline | None = None,
        translation_pipeline: TranslationPipeline | None = None,
    ) -> None:
        super().__init__(parent=app)
        self._app = app
        self._tray = tray
        self._ocr_pipeline = ocr_pipeline or default_ocr_pipeline()
        self._settings_window: SettingsWindow | None = None

        self._settings = load_settings()
        self._translation_pipeline = translation_pipeline or build_pipeline(
            self._settings.translate.provider,
            openrouter_model=self._settings.translate.openrouter_model,
        )
        self._translation_ctx = _build_translation_ctx(self._settings)

        self._region_selector = RegionSelector()
        self._region_selector.selected.connect(self._on_region_selected)
        self._region_selector.cancelled.connect(self._on_region_cancelled)

        self._popup = FloatingPopup()
        self._popup.set_voice_settings(self._settings.voice)
        self._popup.set_display_mode(self._settings.translate.display_mode)
        self._popup.set_click_outside_close(self._settings.display.click_outside_close)
        self._popup.settings_requested.connect(self._open_settings)
        # New Cobalt-design signals from the rebuilt popup.
        self._popup.retry_requested.connect(self._on_popup_retry)
        self._popup.switch_provider_requested.connect(self._open_settings)

        self._overlay = InlineOverlay()
        self._overlay.refresh_requested.connect(self._on_overlay_refresh)

        # Video subtitle mode: a persistent bar + a background capture loop.
        # `_region_target` routes the NEXT region selection: the region selector
        # is shared with region-translate, so Alt+V flips this to "video" so the
        # drawn rectangle starts the subtitle loop instead of a one-shot translate.
        self._subtitle_bar = SubtitleBar()
        self._video = VideoSubtitleController(self)
        self._video.text_ready.connect(self._subtitle_bar.set_text)
        self._video.status.connect(self._subtitle_bar.set_status)
        self._video.error.connect(lambda msg: self._notify(f"Video subtitle: {msg}"))
        self._video.stopped.connect(self._subtitle_bar.stop)
        self._region_target = "translate"
        # Stop the background loop cleanly on quit so its QThread doesn't block
        # process exit.
        self._app.aboutToQuit.connect(self._video.stop)
        # AboutDialog instance — created lazily on first open so app start
        # stays snappy (it's never needed during the snipe-and-translate flow).
        # Typed as the actual AboutDialog via a TYPE_CHECKING-guarded import to
        # avoid pulling the UI module just for an annotation.
        from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from transsnip.ui.about_dialog import AboutDialog  # noqa: F401
        self._about_dialog: "AboutDialog | None" = None  # type: ignore[name-defined]
        # Last region cached so the popup's error-state Retry button can
        # re-run the same capture flow without forcing the user to re-snipe.
        self._last_region_for_retry: QRect | None = None
        # Per-fullscreen-session state: kept on `self` because OCR/translation
        # workers report back via signals, and we need to remember which blocks
        # and which monitor to paint when the translation eventually lands.
        self._fullscreen_blocks: list[OCRBlock] = []
        self._fullscreen_monitor_rect: QRect | None = None

        # Set later via `set_hotkey_manager()` — main() owns the manager so it
        # can wire `triggered` to `handle_hotkey` before we get a reference. We
        # only need it to rebind on settings-save.
        self._hotkey_manager = None

        # Translation history (recent results, browsable from the tray).
        self._history = HistoryStore()
        from typing import TYPE_CHECKING as _TC
        if _TC:
            from transsnip.ui.history_window import HistoryWindow  # noqa: F401
        self._history_window: "HistoryWindow | None" = None  # type: ignore[name-defined]

        self._tray.settings_requested.connect(self._open_settings)
        # Tray menu actions from the redesigned context menu.
        self._tray.about_requested.connect(self._open_about)
        self._tray.history_requested.connect(self._open_history)
        self._tray.region_translate_triggered.connect(
            lambda: self.handle_hotkey("region_translate")
        )
        self._tray.fullscreen_translate_triggered.connect(
            lambda: self.handle_hotkey("fullscreen_translate")
        )

    @property
    def settings(self):
        """Public accessor for the loaded settings — main() uses this to bind
        initial hotkeys without having to re-call load_settings() itself."""
        return self._settings

    def set_hotkey_manager(self, manager) -> None:
        """Wire the HotkeyManager so settings-save can rebind hotkeys."""
        self._hotkey_manager = manager

    # ── Hotkey dispatch ─────────────────────────────────────────────────────

    @Slot(str)
    def handle_hotkey(self, action_id: str) -> None:
        log.info("Hotkey action: %s", action_id)
        if action_id == "region_translate":
            # Dismiss any popup from the previous translation so it doesn't sit
            # on top of the new selection overlay.
            self._popup.hide_popup()
            self._region_selector.start()
        elif action_id == "fullscreen_translate":
            # Alt+F toggles the inline overlay: if one is visible, dismiss it;
            # otherwise start a fresh capture-OCR-translate cycle.
            if self._overlay.isVisible():
                self._overlay.close_overlay()
                return
            # Same reason as region mode: hide the region popup if it's open
            # so its pixels can't end up in the fullscreen screenshot.
            self._popup.hide_popup()
            self._start_fullscreen_translate()
        elif action_id == "video_subtitle_translate":
            # Toggle: if a subtitle loop is running, Alt+V stops it; otherwise
            # start by letting the user draw the subtitle region.
            if self._video.is_running():
                self._stop_video()
                return
            self._popup.hide_popup()
            self._region_target = "video"
            self._region_selector.start()
        elif action_id == "open_settings":
            self._open_settings()
        else:
            log.warning("Unknown hotkey action: %s", action_id)

    # ── Region translate flow ───────────────────────────────────────────────

    @Slot(QRect)
    def _on_region_selected(self, rect: QRect) -> None:
        # The region selector is shared between region-translate and video
        # subtitle mode; `_region_target` says which one asked for this rect.
        if self._region_target == "video":
            self._region_target = "translate"
            self._start_video_for_region(rect)
            return
        # Cache the rect so the popup's error-state Retry button can re-run
        # the same flow without forcing the user to re-snipe.
        self._last_region_for_retry = rect
        # Defer BOTH popup show and capture by _CAPTURE_DELAY_MS — see the
        # mentor doc 90 postmortem for why showing the popup before capture
        # leaks "Đang nhận diện…" pixels into the OCR input.
        QTimer.singleShot(_CAPTURE_DELAY_MS, lambda: self._capture_and_ocr(rect))

    @Slot()
    def _on_region_cancelled(self) -> None:
        # Reset the target so a cancelled Alt+V pick doesn't leave the next
        # region-translate selection accidentally routed to video mode.
        self._region_target = "translate"
        log.debug("Region selection cancelled by user")

    # ── Video subtitle flow ─────────────────────────────────────────────────

    def _start_video_for_region(self, rect: QRect) -> None:
        """Begin the live subtitle loop over `rect` (logical coords)."""
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        self._subtitle_bar.set_bg_opacity(self._settings.display.subtitle_bg_opacity)
        self._subtitle_bar.set_font_pt(self._settings.display.subtitle_font_pt)
        self._subtitle_bar.start_for_region(rect)
        self._video.start(
            rect, dpr, self._ocr_pipeline, self._translation_pipeline, self._translation_ctx,
        )
        self._notify("Video subtitle: đang chạy. Bấm Alt+V để dừng.")

    def _stop_video(self) -> None:
        self._video.stop()
        self._subtitle_bar.stop()
        self._notify("Video subtitle: đã dừng.")

    def _capture_and_ocr(self, rect: QRect) -> None:
        try:
            image = capture_rect(rect)
        except Exception as exc:  # noqa: BLE001
            log.exception("Capture failed")
            # Show popup now just to surface the error to the user.
            self._popup.show_for_region(rect)
            self._popup.show_error(f"capture — {exc}")
            return

        log.debug("Captured image: %dx%d", image.width, image.height)

        # Pixels are safely captured into `image` — now it's safe to draw the
        # popup. (Showing it earlier would risk having its own UI overlap the
        # capture region and leak status text into the OCR input.)
        self._popup.show_for_region(rect)

        if self._translation_pipeline.supports_vision():
            # Vision-capable provider (Gemini Vision, Claude Vision...) handles
            # OCR + translation in a single API call, with better accuracy on
            # diacritics and context-wrapped sentences than our OCR pipeline.
            self._popup.update_status("Đang gọi Vision API…")
            self._submit_vision(image)
            return

        self._popup.update_status("Đang OCR…")
        # Honor the source language picked in Settings; None means auto-detect.
        self._submit_ocr(image, lang=self._settings.translate.source_lang)

    def _submit_ocr(self, image: Image.Image, *, lang: str | None = None) -> None:
        worker = OCRWorker(image, lang, self._ocr_pipeline)
        worker.signals.done.connect(self._on_ocr_done)
        worker.signals.failed.connect(self._on_ocr_failed)
        QThreadPool.globalInstance().start(worker)

    def _submit_vision(self, image: Image.Image) -> None:
        worker = VisionWorker(image, self._translation_ctx, self._translation_pipeline)
        # Vision path produces a TranslationResult directly — same shape as the
        # OCR-then-translate path, so we reuse the existing done/failed slots.
        worker.signals.done.connect(self._on_translation_done)
        worker.signals.failed.connect(self._on_translation_failed)
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def _on_ocr_done(self, result: OCRResult) -> None:
        text = result.text.strip()
        if not text:
            self._popup.show_error("Không tìm thấy text trong vùng đã chọn.")
            return
        source_lang = self._settings.translate.source_lang
        # Stylized English titles (YouTube thumbnails, logos) often come back
        # from Windows OCR as one giant run-on token. wordninja inserts spaces
        # back; we only do this for explicit English source, since segmenting
        # CJK or other scripts would be nonsense.
        if source_lang == "en":
            text = segment_english_runon(text)
        log.info("OCR result (%s, %d blocks): %r", result.engine, len(result.blocks), text[:120])
        self._popup.update_source(
            text,
            source_lang=source_lang,
            show_phonetic=self._settings.translate.phonetic_audio_en,
        )
        self._submit_translation(text)

    @Slot(str)
    def _on_ocr_failed(self, error: str) -> None:
        self._popup.show_error(f"OCR — {error}")

    def _submit_translation(self, text: str) -> None:
        worker = TranslationWorker(text, self._translation_ctx, self._translation_pipeline)
        worker.signals.done.connect(self._on_translation_done)
        worker.signals.failed.connect(self._on_translation_failed)
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def _on_translation_done(self, result: TranslationResult) -> None:
        log.info(
            "Translation done (%s, cached=%s): src=%d chars, dst=%d chars",
            result.provider, result.cached,
            len(result.source_text), len(result.translated_text),
        )
        self._popup.update_translation(result)
        self._record_history(result)

    def _record_history(self, result: TranslationResult) -> None:
        """Append a region/vision translation to history (best-effort)."""
        if not result.translated_text.strip():
            return
        try:
            self._history.add(HistoryEntry(
                source_text=result.source_text,
                translated_text=result.translated_text,
                source_lang=result.source_lang or "auto",
                target_lang=result.target_lang,
                provider=result.provider,
                timestamp=datetime.now().isoformat(timespec="seconds"),
            ))
            # If the history window is open, reflect the new entry live.
            if self._history_window is not None and self._history_window.isVisible():
                self._history_window.refresh()
        except Exception as exc:  # noqa: BLE001 — history must never break translate
            log.debug("history add failed: %s", exc)

    @Slot(str)
    def _on_translation_failed(self, error: str) -> None:
        self._popup.show_error(f"Translation — {error}")

    # ── Full-screen translate flow ──────────────────────────────────────────
    #
    # Flow: hotkey → capture active monitor → OCR (multi-block) → batch all
    # block texts into one prompt with numeric prefixes [1], [2], ... → submit
    # to text translator → parse output back per index → render InlineOverlay
    # with one opaque box per OCR bbox.
    #
    # We deliberately stay on the TEXT translation path (`pipeline.translate`)
    # even if the active provider supports vision: vision providers return a
    # single blob with no bbox info, so we couldn't position overlay boxes.
    # Forcing text mode keeps the bbox→overlay coordinate chain intact for
    # every provider.

    def _start_fullscreen_translate(self) -> None:
        monitor_rect = active_monitor_logical_rect()
        log.info("Fullscreen translate on monitor %s", monitor_rect)
        self._tray.showMessage(
            "TransSnip",
            "Đang OCR + dịch toàn màn hình…",
            QSystemTrayIcon.MessageIcon.Information,
            1500,
        )
        try:
            image = capture_rect(monitor_rect)
        except Exception as exc:  # noqa: BLE001
            log.exception("Fullscreen capture failed")
            self._notify(f"Capture lỗi: {exc}")
            return
        log.debug("Fullscreen captured: %dx%d", image.width, image.height)
        self._fullscreen_monitor_rect = monitor_rect
        self._submit_fullscreen_ocr(image, lang=self._settings.translate.source_lang)

    def _submit_fullscreen_ocr(self, image: Image.Image, *, lang: str | None) -> None:
        worker = OCRWorker(image, lang, self._ocr_pipeline)
        worker.signals.done.connect(self._on_fullscreen_ocr_done)
        worker.signals.failed.connect(self._on_fullscreen_ocr_failed)
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def _on_fullscreen_ocr_done(self, result: OCRResult) -> None:
        blocks = [b for b in result.blocks if b.text.strip()]
        if not blocks:
            self._notify("Fullscreen: không tìm thấy text trên màn hình.")
            self._fullscreen_monitor_rect = None
            return
        log.info(
            "Fullscreen OCR (%s): %d blocks, %d chars total",
            result.engine, len(blocks), sum(len(b.text) for b in blocks),
        )
        self._fullscreen_blocks = blocks

        # Numbered batch — one API call for the whole screen. Robust if the
        # translator preserves the [N] markers (Claude/OpenRouter/Gemini do
        # this fine; Google Translate sometimes re-orders the brackets but
        # `_parse_numbered_batch` salvages whatever it gets back).
        batch = "\n".join(f"[{i + 1}] {b.text}" for i, b in enumerate(blocks))
        self._submit_fullscreen_translation(batch)

    @Slot(str)
    def _on_fullscreen_ocr_failed(self, error: str) -> None:
        log.warning("Fullscreen OCR failed: %s", error)
        self._notify(f"OCR fullscreen lỗi: {error}")
        self._fullscreen_blocks = []
        self._fullscreen_monitor_rect = None

    def _submit_fullscreen_translation(self, batch: str) -> None:
        worker = TranslationWorker(batch, self._translation_ctx, self._translation_pipeline)
        worker.signals.done.connect(self._on_fullscreen_translation_done)
        worker.signals.failed.connect(self._on_fullscreen_translation_failed)
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def _on_fullscreen_translation_done(self, result: TranslationResult) -> None:
        blocks = self._fullscreen_blocks
        monitor_rect = self._fullscreen_monitor_rect
        self._fullscreen_blocks = []
        self._fullscreen_monitor_rect = None
        if not blocks or monitor_rect is None:
            log.debug("Fullscreen translation arrived but state was cleared")
            return

        translations = _parse_numbered_batch(result.translated_text, len(blocks))

        # Convert each block's bbox from CAPTURED-image pixel coords (which the
        # OCR engine returned and we already de-scaled for the preprocessor)
        # into LOGICAL coords relative to the monitor's top-left. The overlay's
        # geometry IS the monitor rect, so monitor-local = overlay-local.
        screen = QGuiApplication.screenAt(monitor_rect.center()) \
            or QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0

        overlay_blocks: list[tuple[QRect, str]] = []
        for block, text in zip(blocks, translations):
            text = text.strip()
            if not text:
                continue
            x, y, w, h = block.bbox
            overlay_blocks.append((
                QRect(int(x / dpr), int(y / dpr), int(w / dpr), int(h / dpr)),
                text,
            ))

        if not overlay_blocks:
            log.warning("Fullscreen: translation returned nothing usable")
            self._notify("Fullscreen: kết quả dịch rỗng, vui lòng thử lại.")
            return

        log.info(
            "Fullscreen translate done (%s, cached=%s): %d/%d blocks rendered",
            result.provider, result.cached, len(overlay_blocks), len(blocks),
        )
        self._overlay.show_for_monitor(monitor_rect, overlay_blocks)

    @Slot(str)
    def _on_fullscreen_translation_failed(self, error: str) -> None:
        log.warning("Fullscreen translation failed: %s", error)
        self._notify(f"Dịch fullscreen lỗi: {error}")
        self._fullscreen_blocks = []
        self._fullscreen_monitor_rect = None

    # ── Settings ────────────────────────────────────────────────────────────

    @Slot()
    def _open_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow()
            self._settings_window.settings_saved.connect(self._on_settings_saved)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    @Slot()
    def _open_about(self) -> None:
        # Lazy: the About widget is heavy to build (paints app icon, three
        # panes of content) but rarely opened.
        if self._about_dialog is None:
            from transsnip.ui.about_dialog import AboutDialog
            self._about_dialog = AboutDialog()
        self._about_dialog.show()
        self._about_dialog.raise_()
        self._about_dialog.activateWindow()

    @Slot()
    def _open_history(self) -> None:
        if self._history_window is None:
            from transsnip.ui.history_window import HistoryWindow
            self._history_window = HistoryWindow(self._history)
        self._history_window.open()

    @Slot()
    def _on_popup_retry(self) -> None:
        """Error-state retry button — re-runs the last region capture flow.

        Falls back to a no-op if we never had a region (vision-only sessions
        with no OCR context to retry from).
        """
        if self._last_region_for_retry is not None:
            self._capture_and_ocr(self._last_region_for_retry)

    @Slot()
    def _on_overlay_refresh(self) -> None:
        """Overlay toolbar's Refresh button — re-capture the active monitor
        and re-run the OCR + batch translate. Useful when source text just
        scrolled or the user navigated to a new section.
        """
        if self._overlay.isVisible():
            self._overlay.close_overlay()
        self._start_fullscreen_translate()

    @Slot()
    def _on_settings_saved(self) -> None:
        self._settings = load_settings()
        self._translation_pipeline = build_pipeline(
            self._settings.translate.provider,
            openrouter_model=self._settings.translate.openrouter_model,
        )
        self._translation_ctx = _build_translation_ctx(self._settings)
        self._popup.set_voice_settings(self._settings.voice)
        self._popup.set_display_mode(self._settings.translate.display_mode)
        self._popup.set_click_outside_close(self._settings.display.click_outside_close)
        if self._hotkey_manager is not None:
            self._hotkey_manager.apply_from_settings(self._settings.hotkeys)
        log.info(
            "Settings reloaded — provider=%s target=%s",
            self._settings.translate.provider,
            self._settings.translate.target_lang,
        )

        # Update the tray menu summary lines so the user sees the new
        # provider / preset without having to re-open Settings.
        self._tray.set_provider_summary(self._translation_pipeline.provider_name)
        self._tray.set_preset_summary(self._settings.translate.preset_name)

        # Success toast (different tone from generic _notify so it shows the
        # green check icon + progress bar).
        try:
            from transsnip.ui.toast import get_toast_stack
            get_toast_stack().show_toast(
                "Settings đã lưu",
                f"Provider: {self._translation_pipeline.provider_name} · "
                f"Target: {self._translation_ctx.target_lang}",
                tone="success",
                duration_ms=3000,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("Toast failed, falling back to tray: %s", exc)
            self._notify("Settings đã lưu.")

    # ── Misc ────────────────────────────────────────────────────────────────

    def _notify(self, message: str, *, timeout_ms: int = 2500) -> None:
        """Surface a transient notification to the user.

        Uses the Cobalt ToastStack (slide-in card with progress bar) instead
        of the Windows-native tray balloon for full theme control — falls
        back to the tray balloon if QApplication isn't fully ready (which
        shouldn't happen at runtime, but stays defensive).
        """
        try:
            from transsnip.ui.toast import get_toast_stack
            get_toast_stack().show_toast(
                "TransSnip", message, tone="default", duration_ms=timeout_ms,
            )
            return
        except Exception as exc:  # noqa: BLE001 — toast must not crash app
            log.debug("Toast failed, falling back to tray: %s", exc)
        self._tray.showMessage(
            "TransSnip",
            message,
            QSystemTrayIcon.MessageIcon.Information,
            timeout_ms,
        )


def _build_translation_ctx(settings: Settings) -> TranslationContext:
    """Flatten `settings.translate` + active preset into a single
    TranslationContext object the providers consume.

    The active preset's `system_prompt` + `glossary` get injected here — that
    way all callers (region popup, fullscreen overlay, vision worker) share
    the same context without each having to look up the preset themselves.
    `get_preset()` returns a blank preset if `preset_name` is stale, so the
    fallback is "translate plainly" instead of crashing.
    """
    preset = get_preset(settings, settings.translate.preset_name)
    return TranslationContext(
        target_lang=settings.translate.target_lang,
        source_lang=settings.translate.source_lang,
        preset_name=preset.name,
        system_prompt=preset.system_prompt,
        glossary=preset.glossary,
        # Learning mode asks LLM providers for the per-word breakdown JSON.
        want_word_breakdown=settings.translate.display_mode == "learning",
    )


_BATCH_MARKER = re.compile(r"\[(\d+)\]\s*", re.MULTILINE)


def _parse_numbered_batch(output: str, n: int) -> list[str]:
    """Split a `[1] ... [2] ... [3] ...` batch translation back into n strings.

    We feed the translator a single prompt with each OCR block prefixed by a
    `[N]` marker so we can keep N→1 (one API call, single context window) and
    still map results back to their bbox. The translator MOSTLY preserves the
    markers, but real providers misbehave in predictable ways:

    - Google Free occasionally re-wraps `[N]` as `( N )` or `「N」` — we won't
      match these and the affected block gets dropped from the overlay.
    - Some LLMs add commentary before the first marker (e.g. "Sure, here are
      the translations:") — anything before `[1]` is ignored.
    - Numbering can come back out of order; we map by the integer, not order.

    Output: list of length `n` where index `i` holds the translation of input
    block `i` (or empty string if the translator skipped that index).
    """
    matches = list(_BATCH_MARKER.finditer(output))
    result = [""] * n
    for i, m in enumerate(matches):
        idx = int(m.group(1)) - 1
        if not (0 <= idx < n):
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        result[idx] = output[start:end].strip()
    return result
