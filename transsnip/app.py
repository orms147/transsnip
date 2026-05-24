from __future__ import annotations

import logging

from PIL import Image
from PySide6.QtCore import QObject, QRect, QThreadPool, QTimer, Slot
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from transsnip.capture.region_selector import RegionSelector
from transsnip.capture.screen import capture_rect
from transsnip.config.settings import load_settings
from transsnip.display.floating_popup import FloatingPopup
from transsnip.ocr.base import OCRResult
from transsnip.ocr.registry import OCRPipeline
from transsnip.ocr.registry import default_pipeline as default_ocr_pipeline
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
            self._settings.translate.provider
        )
        self._translation_ctx = TranslationContext(
            target_lang=self._settings.translate.target_lang,
            source_lang=self._settings.translate.source_lang,
            preset_name=self._settings.translate.preset_name,
        )

        self._region_selector = RegionSelector()
        self._region_selector.selected.connect(self._on_region_selected)
        self._region_selector.cancelled.connect(self._on_region_cancelled)

        self._popup = FloatingPopup()
        self._popup.settings_requested.connect(self._open_settings)

        self._tray.settings_requested.connect(self._open_settings)

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
            self._notify("Full-screen translate chưa wire — sẽ build ở milestone 8.")
        elif action_id == "video_subtitle_translate":
            self._notify("Video subtitle chưa wire — Phase 2.")
        else:
            log.warning("Unknown hotkey action: %s", action_id)

    # ── Region translate flow ───────────────────────────────────────────────

    @Slot(QRect)
    def _on_region_selected(self, rect: QRect) -> None:
        # Defer BOTH popup show and capture by _CAPTURE_DELAY_MS:
        #   - the delay lets the RegionSelector overlay disappear from the
        #     framebuffer before we grab pixels (otherwise its dim tint and
        #     rubber-band rectangle end up in the screenshot)
        #   - showing the popup AFTER capture (inside _capture_and_ocr) ensures
        #     the popup's own pixels can never bleed into the OCR input. We
        #     previously saw the popup status text "Đang nhận diện…" show up in
        #     the OCR result when popup ended up overlaying the captured area.
        QTimer.singleShot(_CAPTURE_DELAY_MS, lambda: self._capture_and_ocr(rect))

    @Slot()
    def _on_region_cancelled(self) -> None:
        log.debug("Region selection cancelled by user")

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
        log.info("OCR result (%s, %d blocks): %r", result.engine, len(result.blocks), text[:120])
        self._popup.update_source(text)
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

    @Slot(str)
    def _on_translation_failed(self, error: str) -> None:
        self._popup.show_error(f"Translation — {error}")

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
    def _on_settings_saved(self) -> None:
        self._settings = load_settings()
        self._translation_pipeline = build_pipeline(self._settings.translate.provider)
        self._translation_ctx = TranslationContext(
            target_lang=self._settings.translate.target_lang,
            source_lang=self._settings.translate.source_lang,
            preset_name=self._settings.translate.preset_name,
        )
        log.info(
            "Settings reloaded — provider=%s target=%s",
            self._settings.translate.provider,
            self._settings.translate.target_lang,
        )
        self._notify(
            f"Settings đã lưu. Provider: {self._translation_pipeline.provider_name}, "
            f"target: {self._translation_ctx.target_lang}",
            timeout_ms=3000,
        )

    # ── Misc ────────────────────────────────────────────────────────────────

    def _notify(self, message: str, *, timeout_ms: int = 2500) -> None:
        """Tray notification — used for events unrelated to the translation popup
        (settings saved, hotkey for not-yet-wired mode, etc.)."""
        self._tray.showMessage(
            "TransSnip",
            message,
            QSystemTrayIcon.MessageIcon.Information,
            timeout_ms,
        )
