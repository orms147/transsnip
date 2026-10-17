from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from PIL import Image
from PySide6.QtCore import QObject, QRect, QTimer, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from transsnip.capture.region_selector import RegionSelector
from transsnip.capture.screen import active_monitor_logical_rect, capture_rect
from transsnip.config.history import HistoryEntry, HistoryStore
from transsnip.config.settings import Settings, get_preset, load_settings, save_settings
from transsnip.display.floating_popup import FloatingPopup
from transsnip.display.inline_overlay import InlineOverlay
from transsnip.display.subtitle_bar import SubtitleBar
from transsnip.linguistic.langdetect import effective_source
from transsnip.modes.fullscreen import build_numbered_batch, overlay_boxes, parse_numbered_batch
from transsnip.modes.video_subtitle import VideoSubtitleController
from transsnip.ocr.base import OCRBlock, OCRError, OCRResult
from transsnip.ocr.registry import OCRPipeline
from transsnip.ocr.registry import default_pipeline as default_ocr_pipeline
from transsnip.ocr.segment import segment_english_runon
from transsnip.translate.base import TranslationContext, TranslationError, TranslationResult
from transsnip.translate.registry import TranslationPipeline, pipeline_from_settings
from transsnip.tray.tray_icon import TrayController
from transsnip.ui.settings_window import SettingsWindow
from transsnip.utils.workers import run_in_pool

if TYPE_CHECKING:
    # Lazily-built windows — imported for annotations only so app start stays
    # snappy (neither is needed during the snip-and-translate flow).
    from transsnip.asr.whisper import WhisperTranscriber
    from transsnip.hotkeys.manager import HotkeyManager
    from transsnip.ui.about_dialog import AboutDialog
    from transsnip.ui.history_window import HistoryWindow

log = logging.getLogger(__name__)

# Tiny delay between hiding the region overlay and grabbing pixels. Without it,
# the OS may still be compositing the (now-hidden) overlay into the next frame.
_CAPTURE_DELAY_MS = 80
# Background OCR warm-up runs this long after start, so it doesn't compete
# with building the tray/UI.
_WARM_UP_DELAY_MS = 1500


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
        self._settings_window: SettingsWindow | None = None

        self._settings = load_settings()
        self._ocr_pipeline_injected = ocr_pipeline is not None
        self._ocr_pipeline = ocr_pipeline or default_ocr_pipeline(
            self._settings.ocr.primary_engine
        )
        self._translation_pipeline = translation_pipeline or pipeline_from_settings(
            self._settings
        )
        self._translation_ctx = _build_translation_ctx(self._settings)

        self._region_selector = RegionSelector()
        self._region_selector.selected.connect(self._on_region_selected)
        self._region_selector.cancelled.connect(self._on_region_cancelled)

        self._popup = FloatingPopup()
        self._apply_popup_settings()
        self._popup.settings_requested.connect(self._open_settings)
        # New Cobalt-design signals from the rebuilt popup.
        self._popup.retry_requested.connect(self._on_popup_retry)
        self._popup.switch_provider_requested.connect(self._open_settings)
        # In-popup language switching: persist the pair and re-translate the
        # cached source text (no re-capture / re-OCR).
        self._popup.lang_pair_changed.connect(self._on_popup_lang_changed)

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

        # Audio subtitle mode (Alt+A): translate the spoken audio of a video that
        # has NO on-screen text. Shares the one SubtitleBar with video mode.
        # Heavy (Whisper) — built lazily; deps optional (`[audio]` extra).
        from transsnip.modes.audio_subtitle import AudioSubtitleController
        self._audio = AudioSubtitleController(self)
        self._audio.text_ready.connect(self._on_audio_text)
        self._audio.status.connect(self._subtitle_bar.set_status)
        self._audio.error.connect(lambda msg: self._notify(f"Audio subtitle: {msg}"))
        self._audio.stopped.connect(self._subtitle_bar.stop)
        self._app.aboutToQuit.connect(self._audio.stop)
        self._transcriber: WhisperTranscriber | None = None  # built on first Alt+A
        # Created lazily on first open (heavy to build, rarely opened).
        self._about_dialog: AboutDialog | None = None
        # Last region cached so the popup's error-state Retry button can
        # re-run the same capture flow without forcing the user to re-snipe.
        # The companion image is the freeze-frame crop (gaming mode) — retry
        # must reuse it, since the game may be minimized by the time the user
        # clicks Retry and a fresh capture would grab the desktop.
        self._last_region_for_retry: QRect | None = None
        self._last_region_image: Image.Image | None = None
        # True while a deferred freeze-frame selector open is scheduled —
        # guards hotkey double-taps from racing the compositor delay.
        self._selector_start_pending = False
        # Per-fullscreen-session state: kept on `self` because OCR/translation
        # workers report back via signals, and we need to remember which blocks
        # and which monitor to paint when the translation eventually lands.
        self._fullscreen_blocks: list[OCRBlock] = []
        self._fullscreen_monitor_rect: QRect | None = None
        # Monotonic session counter — async OCR/translate results tagged with
        # an older generation are stale and dropped (see _start_fullscreen_translate).
        self._fullscreen_gen = 0

        # Set later via `set_hotkey_manager()` — main() owns the manager so it
        # can wire `triggered` to `handle_hotkey` before we get a reference. We
        # only need it to rebind on settings-save.
        self._hotkey_manager: HotkeyManager | None = None

        # Translation history (recent results, browsable from the tray).
        self._history = HistoryStore()
        self._history_window: HistoryWindow | None = None

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
        QTimer.singleShot(_WARM_UP_DELAY_MS, self._warm_up_ocr)

    @property
    def settings(self) -> Settings:
        """Public accessor for the loaded settings — main() uses this to bind
        initial hotkeys without having to re-call load_settings() itself."""
        return self._settings

    def set_hotkey_manager(self, manager: HotkeyManager) -> None:
        """Wire the HotkeyManager so settings-save can rebind hotkeys."""
        self._hotkey_manager = manager

    # ── Hotkey dispatch ─────────────────────────────────────────────────────

    @Slot(str)
    def handle_hotkey(self, action_id: str) -> None:
        log.info("Hotkey action: %s", action_id)
        if action_id == "region_translate":
            # Dismiss any popup from the previous translation so it doesn't sit
            # on top of the new selection overlay.
            was_visible = self._popup.isVisible()
            self._popup.hide_popup()
            if self._settings.hotkeys.high_priority:
                # Gaming mode: freeze the screen BEFORE the selector steals
                # focus — an exclusive-fullscreen game minimizes on focus loss,
                # so a live view (and a post-selection capture) would show the
                # desktop instead of the game. If the popup was up, give the
                # compositor one beat to actually remove its pixels first.
                # The pending guard stops a quick double-tap from re-entering
                # with delay=0 (popup already hidden by press one) and baking
                # still-composited popup pixels into the frozen frame.
                if self._selector_start_pending or self._region_selector.isVisible():
                    return
                self._selector_start_pending = True
                delay = _CAPTURE_DELAY_MS if was_visible else 0
                QTimer.singleShot(delay, self._start_frozen_selector)
            else:
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
            if self._region_selector.isVisible():
                # A region selection (possibly a frozen-frame Alt+T session)
                # is in progress — don't silently re-route its result into
                # the video loop.
                return
            self._audio.stop()  # share one SubtitleBar — stop the other mode first
            self._popup.hide_popup()
            self._region_target = "video"
            self._region_selector.start()
        elif action_id == "audio_subtitle_translate":
            # Toggle: Alt+A starts/stops audio translation. No region needed —
            # it captures system audio and starts immediately.
            if self._audio.is_running():
                self._stop_audio()
                return
            self._video.stop()  # share one SubtitleBar
            self._start_audio()
        elif action_id == "open_settings":
            self._open_settings()
        else:
            log.warning("Unknown hotkey action: %s", action_id)

    # ── Region translate flow ───────────────────────────────────────────────

    def _start_frozen_selector(self) -> None:
        """Deferred freeze-frame open of the region selector (gaming mode)."""
        self._selector_start_pending = False
        if self._region_selector.isVisible():
            return  # start() would discard the frame anyway — skip the capture
        frozen, monitor_rect = self._freeze_frame_or_none()
        self._region_selector.start(frozen_image=frozen, frozen_rect=monitor_rect)

    def _freeze_frame_or_none(self) -> tuple[Image.Image | None, QRect | None]:
        """Pre-capture the cursor's monitor for freeze-frame region select.

        Returns (frame, monitor_rect) — the rect pins WHICH monitor the frame
        belongs to, so the selector opens on that monitor even if the cursor
        hops to another (identically-sized) one while mss is grabbing.
        Best-effort: a capture failure just degrades to the live selector
        (same behavior as with the setting off) instead of blocking the flow.
        """
        monitor_rect = active_monitor_logical_rect()
        try:
            return capture_rect(monitor_rect), monitor_rect
        except Exception:
            log.exception("Freeze-frame capture failed — using live selector")
            return None, None

    @Slot(QRect)
    def _on_region_selected(self, rect: QRect) -> None:
        # The region selector is shared between region-translate and video
        # subtitle mode; `_region_target` says which one asked for this rect.
        if self._region_target == "video":
            self._region_target = "translate"
            self._start_video_for_region(rect)
            return
        # Cache the rect (and the frozen crop, if any) so the popup's
        # error-state Retry button can re-run the same flow without forcing
        # the user to re-snipe — or re-capturing a game that's minimized now.
        frozen = self._region_selector.frozen_crop(rect)
        self._last_region_for_retry = rect
        self._last_region_image = frozen
        if frozen is not None:
            # Pixels were captured before the selector even appeared — there
            # are no overlay pixels to wait out, start OCR immediately.
            self._capture_and_ocr(rect, image=frozen)
            return
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
        self._style_subtitle_bar()
        self._subtitle_bar.set_two_lines(False)  # video: one on-screen line ↔ one subtitle
        self._subtitle_bar.start_for_region(rect)
        self._video.start(
            rect, dpr, self._ocr_pipeline, self._translation_pipeline, self._translation_ctx,
        )
        self._notify("Video subtitle: đang chạy. Bấm Alt+V để dừng.")

    def _style_subtitle_bar(self) -> None:
        """Re-read bar style at each start so Settings changes apply next run."""
        self._subtitle_bar.set_bg_opacity(self._settings.display.subtitle_bg_opacity)
        self._subtitle_bar.set_font_pt(self._settings.display.subtitle_font_pt)

    def _stop_video(self) -> None:
        self._video.stop()
        self._subtitle_bar.stop()
        self._notify("Video subtitle: đã dừng.")

    # ── Audio subtitle flow ─────────────────────────────────────────────────

    def _start_audio(self) -> None:
        """Begin live audio→subtitle translation (no region — captures system audio).

        Pressing Alt+A IS the opt-in — no separate enable flag. If the optional
        audio deps aren't installed, the controller emits a clear error toast.
        """
        from transsnip.asr.whisper import WhisperTranscriber
        if self._transcriber is None:
            # Use the configured source language as the Whisper hint — a FIXED
            # language is more accurate than per-chunk auto-detect (no zh→ru→en
            # jitter, no wrong-language hallucination) and skips detection.
            # WhisperTranscriber normalizes BCP-47 → ISO ("zh-Hans" → "zh"); a
            # None/"auto" setting falls back to auto-detect + language lock.
            # compute_type left "auto" so the transcriber picks per device
            # (CUDA→float16, CPU→int8) — see WhisperTranscriber._resolve_device.
            self._transcriber = WhisperTranscriber(
                tier=self._settings.audio.whisper_tier,
                source_lang=self._settings.translate.source_lang,
            )
        self._style_subtitle_bar()
        self._subtitle_bar.set_two_lines(True)   # audio: previous + newest utterance
        self._subtitle_bar.start_anchored(active_monitor_logical_rect())
        self._audio.start(self._transcriber, self._translation_pipeline, self._translation_ctx)
        mb = self._transcriber.expected_download_mb()
        self._notify(f"Audio subtitle: đang nghe… (lần đầu tải model ~{mb}MB). Bấm Alt+A để dừng.")

    def _on_audio_text(self, text: str) -> None:
        log.info("audio subtitle → %r", text)   # visible: translated line reaching the bar
        self._subtitle_bar.set_text(text)

    def _stop_audio(self) -> None:
        self._audio.stop()
        self._subtitle_bar.stop()
        self._notify("Audio subtitle: đã dừng.")

    def _capture_and_ocr(self, rect: QRect, image: Image.Image | None = None) -> None:
        # `image` is the freeze-frame crop in gaming mode — the screen content
        # at hotkey time, already safe from our own UI. Live mode captures now.
        if image is None:
            try:
                image = capture_rect(rect)
            except Exception as exc:
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
        self._popup.set_lang_pair(
            self._settings.translate.source_lang, self._settings.translate.target_lang
        )

        if self._translation_pipeline.supports_vision():
            # Vision-capable provider (Gemini Vision, Claude Vision...) handles
            # OCR + translation in a single API call, with better accuracy on
            # diacritics and context-wrapped sentences than our OCR pipeline.
            self._popup.update_status("Đang gọi Vision API…")
            self._submit_vision(image)
            return

        self._popup.update_status("Đang OCR…")
        # Honors the source language picked in Settings; None means auto-detect.
        self._submit_ocr(image, self._on_ocr_done, self._on_ocr_failed)

    # ── Background workers ──────────────────────────────────────────────────
    #
    # All three block for 0.2-5 s, so they run on the QThreadPool; results come
    # back on the main thread. Pipelines/ctx are bound NOW (not looked up when
    # the worker runs) so a settings save mid-flight can't mix configs.

    def _submit_ocr(
        self,
        image: Image.Image,
        on_done: Callable[[Any], None],
        on_failed: Callable[[str], None],
    ) -> None:
        pipeline, lang = self._ocr_pipeline, self._settings.translate.source_lang
        run_in_pool(lambda: pipeline.recognize(image, lang), on_done, on_failed,
                    expected=(OCRError,), label="OCR")

    def _submit_translation(
        self,
        text: str,
        on_done: Callable[[Any], None] | None = None,
        on_failed: Callable[[str], None] | None = None,
        *,
        ctx: TranslationContext | None = None,
    ) -> None:
        pipeline, ctx = self._translation_pipeline, ctx or self._translation_ctx
        run_in_pool(lambda: pipeline.translate(text, ctx),
                    on_done or self._on_translation_done,
                    on_failed or self._on_translation_failed,
                    expected=(TranslationError,), label="translation")

    def _submit_vision(self, image: Image.Image) -> None:
        pipeline, ctx = self._translation_pipeline, self._translation_ctx
        # Vision path produces a TranslationResult directly — same shape as the
        # OCR-then-translate path, so we reuse the existing done/failed slots.
        run_in_pool(lambda: pipeline.translate_image(image, ctx),
                    self._on_translation_done, self._on_translation_failed,
                    expected=(TranslationError, NotImplementedError), label="vision")

    @Slot(object)
    def _on_ocr_done(self, result: OCRResult) -> None:
        text = result.text.strip()
        if not text:
            self._popup.show_error("Không tìm thấy text trong vùng đã chọn.")
            return
        setting = self._settings.translate.source_lang
        # Auto mode: settle the language from the text's script so the English
        # features (run-on split, IPA), the popup chip and fonts still work.
        source_lang, confident = effective_source(setting, text)
        # Stylized English titles (YouTube thumbnails, logos) often come back
        # from OCR as one giant run-on token. wordninja inserts spaces back;
        # only for English, since segmenting CJK or other scripts is nonsense.
        if source_lang == "en":
            text = segment_english_runon(text)
        log.info("OCR result (%s, %d blocks, lang=%s%s): %r", result.engine, len(result.blocks),
                 source_lang, "" if setting else " detected", text[:120])
        self._popup.update_source(
            text,
            source_lang=source_lang,
            show_phonetic=self._settings.translate.phonetic_audio_en,
            detected=setting is None,
        )
        # Pin the translator's source only when the script is unambiguous
        # (kana → ja, plain Latin → en); Han-only text could be either zh or
        # kanji-only ja, so the provider keeps its own auto-detect there.
        ctx = self._translation_ctx
        if setting is None and confident:
            ctx = replace(ctx, source_lang=source_lang)
        self._submit_translation(text, ctx=ctx)

    @Slot(str)
    def _on_ocr_failed(self, error: str) -> None:
        self._popup.show_error(f"OCR — {error}")

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
    # capture monitor → OCR blocks → one numbered batch translate → overlay.
    # The pure parts (batching, parsing, bbox conversion) live in
    # modes/fullscreen.py, including why this stays on the TEXT path even for
    # vision-capable providers.

    def _start_fullscreen_translate(self) -> None:
        # Each invocation gets a generation number; async results carry it and
        # are dropped when stale. Without this, pressing Alt+F twice quickly
        # zips run 1's translations with run 2's bboxes (shared state) — text
        # lands in the wrong boxes and run 2's result gets discarded.
        self._fullscreen_gen += 1
        gen = self._fullscreen_gen
        monitor_rect = active_monitor_logical_rect()
        log.info("Fullscreen translate on monitor %s (gen=%d)", monitor_rect, gen)
        self._tray.showMessage(
            "TransSnip",
            "Đang OCR + dịch toàn màn hình…",
            QSystemTrayIcon.MessageIcon.Information,
            1500,
        )
        try:
            image = capture_rect(monitor_rect)
        except Exception as exc:
            log.exception("Fullscreen capture failed")
            self._notify(f"Capture lỗi: {exc}")
            return
        log.debug("Fullscreen captured: %dx%d", image.width, image.height)
        self._fullscreen_monitor_rect = monitor_rect
        self._submit_ocr(
            image, partial(self._on_fullscreen_ocr_done, gen=gen),
            partial(self._on_fullscreen_failed, gen=gen),
        )

    def _on_fullscreen_ocr_done(self, result: OCRResult, gen: int) -> None:
        if gen != self._fullscreen_gen:
            log.debug("Fullscreen OCR result from gen %d dropped (current gen %d)",
                      gen, self._fullscreen_gen)
            return
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
        # `parse_numbered_batch` salvages whatever it gets back).
        self._submit_translation(
            build_numbered_batch(blocks),
            partial(self._on_fullscreen_translation_done, gen=gen),
            partial(self._on_fullscreen_failed, gen=gen),
        )

    def _on_fullscreen_translation_done(self, result: TranslationResult, gen: int) -> None:
        if gen != self._fullscreen_gen:
            log.debug("Fullscreen translation from gen %d dropped (current gen %d)",
                      gen, self._fullscreen_gen)
            return
        blocks = self._fullscreen_blocks
        monitor_rect = self._fullscreen_monitor_rect
        self._fullscreen_blocks = []
        self._fullscreen_monitor_rect = None
        if not blocks or monitor_rect is None:
            log.debug("Fullscreen translation arrived but state was cleared")
            return

        translations = parse_numbered_batch(result.translated_text, len(blocks))
        screen = (
            QGuiApplication.screenAt(monitor_rect.center()) or QGuiApplication.primaryScreen()
        )
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        overlay_blocks = [
            (QRect(*box), text) for box, text in overlay_boxes(blocks, translations, dpr)
        ]
        if not overlay_blocks:
            log.warning("Fullscreen: translation returned nothing usable")
            self._notify("Fullscreen: kết quả dịch rỗng, vui lòng thử lại.")
            return

        log.info(
            "Fullscreen translate done (%s, cached=%s): %d/%d blocks rendered",
            result.provider, result.cached, len(overlay_blocks), len(blocks),
        )
        self._overlay.show_for_monitor(monitor_rect, overlay_blocks)

    def _on_fullscreen_failed(self, error: str, gen: int) -> None:
        # Shared by the OCR and translate stages. A stale run's failure must
        # not wipe the state a newer run is still waiting on.
        if gen != self._fullscreen_gen:
            return
        log.warning("Fullscreen translate failed: %s", error)
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
        self._history_window.set_output_device(self._settings.voice.output_device)
        self._history_window.open()

    @Slot()
    def _on_popup_retry(self) -> None:
        """Error-state retry button — re-runs the last region capture flow.

        Falls back to a no-op if we never had a region (vision-only sessions
        with no OCR context to retry from).
        """
        if self._last_region_for_retry is not None:
            self._capture_and_ocr(self._last_region_for_retry, image=self._last_region_image)

    @Slot(object, str)
    def _on_popup_lang_changed(self, source_lang: str | None, target_lang: str) -> None:
        """User picked a new language pair via the popup chips / swap button.

        Persists to global settings (the next snip almost always wants the
        same pair — a popup-local override would leave retry and the other
        modes on a different pair) and re-translates the already-captured
        source text in place.
        """
        t = self._settings.translate
        t.source_lang = source_lang or None
        t.target_lang = target_lang
        save_settings(self._settings)
        self._translation_ctx = _build_translation_ctx(self._settings)
        self._warm_up_ocr()
        log.info("Popup lang pair changed: %s -> %s", source_lang or "auto", target_lang)
        text = self._popup.last_source_text().strip()
        if text:
            self._submit_translation(text)

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
        self._translation_pipeline = pipeline_from_settings(self._settings)
        self._translation_ctx = _build_translation_ctx(self._settings)
        if not self._ocr_pipeline_injected:
            # Cheap: engines build their models lazily (and warm-up below
            # pre-builds the new primary off the GUI thread).
            self._ocr_pipeline = default_ocr_pipeline(self._settings.ocr.primary_engine)
        self._warm_up_ocr()
        # Drop the cached transcriber so a changed Whisper tier / source-lang
        # takes effect on the next Alt+A (rebuilt lazily in _start_audio).
        self._transcriber = None
        # Frozen-crop reuse on Retry only makes sense while gaming mode is on
        # (the game may be minimized); once it's off, Retry should re-capture
        # live pixels like it always did.
        if not self._settings.hotkeys.high_priority:
            self._last_region_image = None
        self._apply_popup_settings()
        if self._hotkey_manager is not None:
            failed = self._hotkey_manager.apply_from_settings(self._settings.hotkeys)
            if failed:
                labels = ", ".join(
                    getattr(self._settings.hotkeys, aid, aid) or aid for aid in failed
                )
                self._notify(
                    f"Không đăng ký được hotkey: {labels} — có thể app khác đang giữ tổ hợp này. "
                    "Hãy chọn tổ hợp khác trong Settings."
                )
            if (
                self._settings.hotkeys.high_priority
                and not self._hotkey_manager.high_priority_active()
            ):
                # Toggle is on but the hook didn't come up — without this the
                # user believes gaming mode is protecting their hotkeys while
                # only the normal RegisterHotKey path is actually running.
                self._notify(
                    "Không bật được hotkey ưu tiên cao — hotkey vẫn chạy ở chế độ thường."
                )
        log.info(
            "Settings reloaded — provider=%s target=%s",
            self._settings.translate.provider,
            self._settings.translate.target_lang,
        )

        # Update the tray menu summary lines so the user sees the new
        # provider / preset without having to re-open Settings.
        self._tray.set_provider_summary(self._translation_pipeline.provider_name)
        self._tray.set_preset_summary(self._settings.translate.preset_name)

        # A running subtitle session captured its pipeline/ctx at start() and
        # keeps translating with the OLD config — say so instead of letting
        # the user believe the change took effect.
        running_modes = []
        if self._video.is_running():
            running_modes.append("Video (Alt+V)")
        if self._audio.is_running():
            running_modes.append("Audio (Alt+A)")
        if running_modes:
            self._notify(
                f"{' và '.join(running_modes)} đang chạy với config cũ — "
                "tắt/bật lại để áp dụng thay đổi.",
                timeout_ms=5000,
            )

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

    def _warm_up_ocr(self) -> None:
        """Pre-build whichever OCR engine will serve the source language, off
        the GUI thread — RapidOCR's first call is otherwise ~0.8 s slower
        than the rest. No-op when Windows OCR serves it (already fast cold)."""
        pipeline, lang = self._ocr_pipeline, self._settings.translate.source_lang
        run_in_pool(lambda: pipeline.warm_up(lang), lambda _r: None, lambda _e: None,
                    label="OCR warm-up")

    def _apply_popup_settings(self) -> None:
        self._popup.set_voice_settings(self._settings.voice)
        self._popup.set_display_mode(self._settings.translate.display_mode)
        self._popup.set_click_outside_close(self._settings.display.click_outside_close)

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
