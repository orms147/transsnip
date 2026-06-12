"""Off-thread Edge-TTS generator + QMediaPlayer playback.

Why Edge TTS over Windows SAPI:
- Free, no API key, voices on par with paid offerings (Aria, Guy, etc.)
- Streaming over Microsoft's CDN — typical latency 500-1500ms for a short
  sentence, fine for "click to hear pronunciation" UX
- One small dep (`edge-tts`, pure-Python aiohttp client)

Threading:
- `edge-tts` is asyncio-only and the network call blocks ~1s, so we MUST
  run it off the Qt main thread (otherwise the UI freezes for the duration).
- A `QRunnable` wraps `asyncio.run(...)` and writes the MP3 bytes to a temp
  file, then emits a Qt signal back to the main thread.
- The main thread loads the file into `QMediaPlayer` and plays it.

The temp file is cleaned up once playback finishes (or 30s timeout — Qt's
`mediaStatusChanged` reaches EndOfMedia reliably; the timeout is just a
safety belt for player errors).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

log = logging.getLogger(__name__)

_DEFAULT_VOICE = "en-US-AriaNeural"
_CLEANUP_TIMEOUT_MS = 30_000  # delete temp file at most this long after playback


class _TTSSignals(QObject):
    ready = Signal(str)   # path to generated mp3
    failed = Signal(str)


class _TTSGenRunnable(QRunnable):
    """Runs `edge-tts` in a worker thread and emits the resulting mp3 path."""

    def __init__(self, text: str, voice: str, out_path: str) -> None:
        super().__init__()
        self._text = text
        self._voice = voice
        self._out_path = out_path
        self.signals = _TTSSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            asyncio.run(self._generate())
        except Exception as exc:  # noqa: BLE001 — worker must not raise
            log.warning("Edge-TTS generation failed: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        self.signals.ready.emit(self._out_path)

    async def _generate(self) -> None:
        # Import inside the worker so a missing dep degrades gracefully —
        # we still get the failure signal instead of crashing app startup.
        import edge_tts

        comm = edge_tts.Communicate(self._text, voice=self._voice)
        await comm.save(self._out_path)


class EdgeTTSPlayer(QObject):
    """Stateful TTS player: one in-flight clip at a time.

    Calling `speak()` while a previous clip is playing stops it and starts
    the new one — typical "user clicked another word" UX. We deliberately
    don't queue: queuing tends to surprise users who expect the latest click
    to take effect.
    """

    started = Signal()
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._current_path: str | None = None
        # Playback rate applied per clip (QMediaPlayer.setPlaybackRate works for
        # both the Edge mp3 and the SAPI wav fallback; volume goes through
        # QAudioOutput). These come from VoiceSettings via speak().
        self._rate: float = 1.0
        # Kept so we can re-synthesize via the offline SAPI fallback if the
        # online Edge call fails (e.g. no internet).
        self._last_text: str = ""
        self._last_voice: str = _DEFAULT_VOICE
        self._tried_fallback: bool = False
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)

    def speak(
        self,
        text: str,
        *,
        voice: str = _DEFAULT_VOICE,
        rate: float = 1.0,
        volume: float = 1.0,
    ) -> None:
        text = (text or "").strip()
        if not text:
            return
        # Stop whatever's playing and discard its temp file before starting.
        self._stop_and_cleanup()
        self._last_text = text
        self._last_voice = voice
        self._tried_fallback = False
        # Apply user voice prefs: rate via playback speed (set per-clip in
        # _on_audio_ready), volume via the audio output (0.0-1.0).
        self._rate = max(0.5, min(rate, 2.0))
        self._audio_out.setVolume(max(0.0, min(volume, 1.0)))

        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="transsnip_tts_")
        os.close(fd)  # we let edge-tts write to the path; we only needed it

        runner = _TTSGenRunnable(text, voice, path)
        runner.signals.ready.connect(self._on_audio_ready)
        runner.signals.failed.connect(self._on_audio_failed)
        QThreadPool.globalInstance().start(runner)
        self.started.emit()
        log.debug("TTS started: %d chars, voice=%s", len(text), voice)

    def stop(self) -> None:
        self._stop_and_cleanup()

    # ── Internals ──────────────────────────────────────────────────────────

    def _stop_and_cleanup(self) -> None:
        if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._player.stop()
        self._delete_current_path()

    def _delete_current_path(self) -> None:
        path = self._current_path
        self._current_path = None
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            log.debug("Could not delete %s: %s", path, exc)

    def _on_audio_ready(self, path: str) -> None:
        self._current_path = path
        self._player.setSource(QUrl.fromLocalFile(path))
        # setPlaybackRate must come after setSource; applies to mp3 (Edge) and
        # wav (SAPI) alike.
        self._player.setPlaybackRate(self._rate)
        self._player.play()
        # Safety: even if mediaStatusChanged never reaches EndOfMedia (rare
        # but possible on driver hiccups), make sure we eventually delete
        # the temp file so /tmp doesn't fill up over a long session.
        QTimer.singleShot(_CLEANUP_TIMEOUT_MS, self._delete_current_path)

    def _on_audio_failed(self, error: str) -> None:
        # Edge (online) failed — try the offline WinRT/SAPI voice once before
        # giving up, so pronunciation still works without internet.
        if not self._tried_fallback and self._last_text:
            from transsnip.tts.sapi import SapiGenRunnable, sapi_available
            if sapi_available():
                self._tried_fallback = True
                log.info("Edge-TTS failed (%s) — falling back to offline SAPI", error)
                fd, path = tempfile.mkstemp(suffix=".wav", prefix="transsnip_tts_")
                os.close(fd)
                runner = SapiGenRunnable(self._last_text, path)
                runner.signals.ready.connect(self._on_audio_ready)
                runner.signals.failed.connect(lambda msg: self.failed.emit(msg))
                QThreadPool.globalInstance().start(runner)
                return
        self.failed.emit(error)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.finished.emit()
            self._delete_current_path()

    def _on_player_error(self, _err: QMediaPlayer.Error, msg: str) -> None:
        if msg:
            log.warning("QMediaPlayer error: %s", msg)
            self.failed.emit(msg)
