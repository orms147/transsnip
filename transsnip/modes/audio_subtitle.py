"""Audio subtitle mode — translate the spoken audio of a video that has NO subtitles.

Pipeline (THREE decoupled threads so no audio is ever dropped):

    _CaptureThread (QThread)                     [continuous]
        LoopbackCapture.read() blocks → append to a shared _AudioBuffer
        (never blocks on ASR, so audio keeps flowing during transcription)
    _AsrLoop (QThread)
        pull a complete UTTERANCE from the buffer (speech bounded by a silence
        gap — energy VAD, not a fixed time slice) → WhisperTranscriber.transcribe()
        → dedupe (text_similarity) → emit new_source(text)
    _TranslateWorker (QThread)                   [REUSED from video_subtitle]
        coalesce latest → pipeline.translate() → emit text_ready(translated)
                              ▼
                       SubtitleBar.set_text()    [main thread]

Why three threads: ASR is ~0.5-0.6 RTF — faster than realtime, so it keeps up —
BUT a single capture+ASR loop would stop reading the audio device for the ~2.5s
each transcribe takes, and PortAudio would silently drop that audio (the "thiếu
nhiều câu" bug). A dedicated capture thread filling a shared buffer fixes it.

Threading: worker threads only emit signals — never touch the GUI. All PortAudio
/ Whisper work happens off the Qt main thread. `_TranslateWorker` (shared with
video mode) coalesces so only the most-recent transcript is translated.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal

from transsnip.modes.video_subtitle import _TranslateWorker  # reuse coalescing translator
from transsnip.translate.base import TranslationContext
from transsnip.translate.registry import TranslationPipeline
from transsnip.utils.image import text_similarity

log = logging.getLogger(__name__)

_TARGET_SR = 16000
# --- Utterance segmentation (energy VAD) -------------------------------------
# Instead of cutting every N seconds (which slices sentences mid-word and forces
# overlap → duplicated fragments), we accumulate audio and cut at a NATURAL pause
# (a silence gap after speech). Each ASR pass then gets a whole utterance → far
# better transcription + translation, and no overlap-induced repeats.
# The proper low-latency streaming upgrade is still LocalAgreement-2
# (ufal/whisper_streaming / WhisperLiveKit) — future work.
_VAD_FRAME_MS = 30       # granularity of the speech/silence decision
_VAD_RMS = 0.005         # frame RMS above this = speech (matches is_silent())
_MIN_SILENCE_MS = 350    # a pause this long after speech ends an utterance
                         # (lower = snappier subtitles, slightly more fragmented)
_MIN_UTTERANCE_MS = 400  # ignore speech blips shorter than this (clicks/noise)
_MAX_UTTERANCE_S = 4.5   # force-cut a non-stop monologue so a long sentence
                         # appears sooner instead of waiting up to 6s+ to finish
_MAX_BUFFER_S = 30.0     # cap buffered audio (drop oldest) if ASR ever falls behind
_TEXT_SIM_THRESH = 0.90  # skip translating a near-duplicate of the last line


class _AudioBuffer:
    """Thread-safe rolling float32 PCM buffer shared by capture → ASR."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf = None  # lazily a numpy array

    def append(self, block) -> None:
        import numpy as np
        if block is None or block.size == 0:
            return
        with self._lock:
            self._buf = block.copy() if self._buf is None else np.concatenate([self._buf, block])
            cap = int(_TARGET_SR * _MAX_BUFFER_S)
            if self._buf.size > cap:           # ASR behind → drop oldest (rare; RTF<1)
                self._buf = self._buf[-cap:]

    def take_utterance(self, sr: int = _TARGET_SR):
        """Pop the next complete spoken utterance, or None if none is ready yet.

        An utterance = the first run of speech that is terminated by a silence
        gap of ≥ _MIN_SILENCE_MS (a natural pause). If speech has been going
        non-stop for ≥ _MAX_UTTERANCE_S we force-cut so subtitles keep flowing.
        Leading silence is trimmed (and pure-silence buffers drained) so the
        buffer never grows unbounded while we wait for a pause.
        """
        import numpy as np

        with self._lock:
            buf = self._buf
            if buf is None or buf.size == 0:
                return None

            frame = int(sr * _VAD_FRAME_MS / 1000)
            n = buf.size // frame
            if n == 0:
                return None

            frames = buf[: n * frame].reshape(n, frame)
            rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
            speech = rms > _VAD_RMS

            if not speech.any():                      # all silence → drain it
                self._buf = buf[n * frame:]
                return None

            first = int(np.argmax(speech))            # first speech frame
            min_sil = max(1, int(_MIN_SILENCE_MS / _VAD_FRAME_MS))
            min_utt = max(1, int(_MIN_UTTERANCE_MS / _VAD_FRAME_MS))
            max_utt = int(_MAX_UTTERANCE_S * 1000 / _VAD_FRAME_MS)

            # Walk forward from the first speech frame looking for a silence run
            # long enough to mark the end of the utterance.
            end = None
            run = 0
            for i in range(first, n):
                if speech[i]:
                    run = 0
                else:
                    run += 1
                    if run >= min_sil and (i - run + 1 - first) >= min_utt:
                        end = i + 1                   # include the trailing pause
                        break

            if end is None:
                if (n - first) >= max_utt:            # non-stop talk → force cut
                    end = first + max_utt             # bound the slice (keep the rest)
                else:                                 # still talking → wait
                    if first > 0:                     # but trim leading silence
                        self._buf = buf[first * frame:]
                    return None

            cut = end * frame
            utterance = buf[first * frame:cut]
            self._buf = buf[cut:]
            return utterance


class _CaptureThread(QThread):
    """Continuously read the loopback device into the shared buffer."""

    error = Signal(str)

    def __init__(self, capture, buffer: _AudioBuffer) -> None:
        super().__init__()
        self._capture = capture
        self._buffer = buffer
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        try:
            self._capture.start()
        except Exception as exc:  # noqa: BLE001
            log.warning("audio capture start failed: %s", exc)
            self.error.emit(str(exc))
            return
        try:
            while self._running:
                self._buffer.append(self._capture.read())
        finally:
            self._capture.stop()


class _AsrLoop(QThread):
    """Pull complete utterances from the buffer → Whisper → emit each NEW line."""

    new_source = Signal(str)
    status = Signal(str)
    error = Signal(str)

    def __init__(self, transcriber, buffer: _AudioBuffer) -> None:
        super().__init__()
        self._transcriber = transcriber
        self._buffer = buffer
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        from transsnip.asr.whisper import is_silent

        self.status.emit("Đang tải model Whisper…")
        try:
            self._transcriber.load()   # downloads on first ever use
        except Exception as exc:  # noqa: BLE001
            log.warning("whisper load failed: %s", exc)
            self.error.emit(str(exc))
            return
        if hasattr(self._transcriber, "reset_language"):
            self._transcriber.reset_language()   # re-detect per session
        self.status.emit("Đang nghe âm thanh…")

        last_src = ""
        while self._running:
            chunk = self._buffer.take_utterance(_TARGET_SR)
            if chunk is None:
                self.msleep(100)   # no complete utterance yet (still talking/silent)
                continue
            if is_silent(chunk):   # belt-and-suspenders; take_utterance already gates
                continue
            try:
                src = self._transcriber.transcribe(chunk)
            except Exception as exc:  # noqa: BLE001 — one bad pass shouldn't kill the loop
                log.warning("transcribe failed: %s", exc)  # visible (not debug)
                continue
            if not src:
                log.debug("ASR: (no speech in chunk)")
                continue
            if text_similarity(src, last_src) >= _TEXT_SIM_THRESH:
                log.debug("ASR dup, skip: %r", src)
                continue
            log.info("ASR → %r", src)   # visible in --dev: what got recognized
            last_src = src
            self.new_source.emit(src)


class AudioSubtitleController(QObject):
    """Owns capture + ASR + the coalescing translate worker; re-emits on the main
    thread. No region/dpr/ocr — audio has no screen source, so it starts at once.
    """

    text_ready = Signal(str)
    status = Signal(str)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._capture_thread: _CaptureThread | None = None
        self._asr: _AsrLoop | None = None
        self._worker: _TranslateWorker | None = None

    def is_running(self) -> bool:
        return self._asr is not None and self._asr.isRunning()

    def start(self, transcriber, translator: TranslationPipeline, ctx: TranslationContext) -> None:
        self.stop()
        from transsnip.asr.whisper import asr_available
        from transsnip.capture.audio import LoopbackCapture, audio_capture_available

        if not (asr_available() and audio_capture_available()):
            self.error.emit("Chưa cài gói audio. Chạy: pip install \"transsnip[audio]\"")
            return

        buffer = _AudioBuffer()
        worker = _TranslateWorker(translator, ctx)
        worker.text_ready.connect(self.text_ready)
        capture_thread = _CaptureThread(LoopbackCapture(), buffer)
        capture_thread.error.connect(self.error)
        asr = _AsrLoop(transcriber, buffer)
        asr.new_source.connect(worker.submit)   # main-thread handoff (lock-guarded)
        asr.status.connect(self.status)
        asr.error.connect(self.error)

        self._worker = worker
        self._capture_thread = capture_thread
        self._asr = asr
        worker.start()
        capture_thread.start()
        asr.start()
        log.info("Audio subtitle pipeline started (capture + asr + translate)")

    def stop(self) -> None:
        threads = [self._asr, self._capture_thread, self._worker]
        if not any(threads):
            return
        for t in threads:
            if t is not None:
                t.stop()
                t.wait(2000)
        self._asr = None
        self._capture_thread = None
        self._worker = None
        log.info("Audio subtitle pipeline stopped")
        self.stopped.emit()
