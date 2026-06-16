"""System-audio capture (WASAPI loopback) for the audio-subtitle mode.

Captures whatever is playing through the speakers/headphones (the system render
mix = the video's audio track) and hands it downstream as the format Whisper
wants: 16 kHz, mono, float32 in [-1, 1]. ALL format conversion lives here so the
ASR layer never sees stereo/int16/48 kHz.

Heavy deps (`pyaudiowpatch`, `numpy`) are imported lazily so the base app starts
without the optional `[audio]` extra installed — `audio_capture_available()`
reports whether the feature can run (mirrors `ocr/rapid_ocr.py`'s degrade path).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # type-only — no runtime import of the heavy dep
    import numpy as np

log = logging.getLogger(__name__)

TARGET_SR = 16000  # Whisper expects 16 kHz mono


class AudioCaptureError(Exception):
    """Raised when WASAPI loopback can't be opened (no device / driver issue)."""


def audio_capture_available() -> bool:
    """True if the optional audio-capture deps are importable."""
    try:
        import numpy  # noqa: F401
        import pyaudiowpatch  # noqa: F401
        return True
    except ImportError:
        return False


def to_whisper_pcm(raw_int16: "np.ndarray", native_sr: int, native_channels: int) -> "np.ndarray":
    """Convert one interleaved int16 block to float32 mono @16 kHz.

    PURE function (no I/O) so it's unit-testable: reshape→mono mean→/32768→resample.
    """
    import numpy as np

    samples = raw_int16.astype(np.float32)
    if native_channels > 1:
        samples = samples.reshape(-1, native_channels).mean(axis=1)
    samples /= 32768.0
    np.clip(samples, -1.0, 1.0, out=samples)
    if native_sr == TARGET_SR or samples.size == 0:
        return samples
    return _resample(samples, native_sr, TARGET_SR)


def _resample(x: "np.ndarray", src_sr: int, dst_sr: int) -> "np.ndarray":
    import numpy as np
    try:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(int(src_sr), int(dst_sr))
        return resample_poly(x, dst_sr // g, src_sr // g).astype(np.float32)
    except ImportError:
        # Linear-interp fallback if scipy is absent — adequate for speech ASR.
        n = int(round(len(x) * dst_sr / src_sr))
        if n <= 0:
            return np.zeros(0, dtype=np.float32)
        idx = np.linspace(0, len(x), n, endpoint=False)
        return np.interp(idx, np.arange(len(x)), x).astype(np.float32)


class LoopbackCapture:
    """Owns a PyAudioWPatch WASAPI loopback stream on the default render device.

    Not a QThread — the `_AudioLoop` QThread drives it via start()/read()/stop()
    so all PortAudio calls happen off the Qt main thread.
    """

    def __init__(self, block_ms: int = 100) -> None:
        self._block_ms = block_ms
        self._pa = None
        self._stream = None
        self._sr = TARGET_SR
        self._channels = 1

    def start(self) -> None:
        import pyaudiowpatch as pyaudio

        self._pa = pyaudio.PyAudio()
        try:
            dev = self._pa.get_default_wasapi_loopback()
        except Exception as exc:  # noqa: BLE001 — surface as our typed error
            self._pa.terminate()
            self._pa = None
            raise AudioCaptureError(f"Không tìm thấy thiết bị loopback: {exc}") from exc
        self._sr = int(dev["defaultSampleRate"])
        self._channels = int(dev["maxInputChannels"])
        self._frames = max(1, int(self._sr * self._block_ms / 1000))
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._sr,
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=self._frames,
        )
        log.info("Loopback capture: %s  sr=%d ch=%d", dev.get("name"), self._sr, self._channels)

    def read(self) -> "np.ndarray":
        """Read one block → float32 mono @16 kHz. Returns empty array on under-run."""
        import numpy as np

        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        raw = self._stream.read(self._frames, exception_on_overflow=False)
        return to_whisper_pcm(np.frombuffer(raw, dtype=np.int16), self._sr, self._channels)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("loopback stream close: %s", exc)
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
