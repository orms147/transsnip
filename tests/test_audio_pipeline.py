"""Audio-subtitle pipeline — pure-logic units (format conversion + VAD gate).

These don't load Whisper or open an audio device — just the deterministic numpy
helpers that turn raw loopback PCM into Whisper-ready audio and gate silence.
Skipped if numpy isn't installed (it ships with the [ocr] extra in practice).
"""
import pytest

np = pytest.importorskip("numpy")

from transsnip.asr.whisper import is_silent
from transsnip.capture.audio import TARGET_SR, to_whisper_pcm


def test_to_whisper_pcm_stereo_48k_to_mono_16k():
    # 1 second of 48k stereo int16 → ~16000 mono float32 samples.
    rng = np.random.default_rng(0)
    stereo = rng.integers(-3000, 3000, size=48000 * 2, dtype=np.int16)
    out = to_whisper_pcm(stereo, native_sr=48000, native_channels=2)
    assert out.dtype == np.float32
    assert abs(out.size - TARGET_SR) <= 5          # ~16000 after 48k→16k
    assert float(out.min()) >= -1.0 and float(out.max()) <= 1.0


def test_to_whisper_pcm_mono_16k_passthrough_scale():
    mono = np.array([32767, -32768, 0, 16384], dtype=np.int16)
    out = to_whisper_pcm(mono, native_sr=TARGET_SR, native_channels=1)
    assert out.dtype == np.float32
    assert out.size == 4
    assert -1.0 <= float(out.min()) and float(out.max()) <= 1.0
    assert abs(out[2]) < 1e-6                        # 0 stays 0


def test_to_whisper_pcm_empty():
    out = to_whisper_pcm(np.zeros(0, dtype=np.int16), native_sr=48000, native_channels=2)
    assert out.size == 0


def test_is_silent_zeros():
    assert is_silent(np.zeros(16000, dtype=np.float32)) is True


def test_is_silent_empty():
    assert is_silent(np.zeros(0, dtype=np.float32)) is True


def test_is_silent_loud_signal():
    sine = (0.3 * np.sin(np.linspace(0, 500, 16000))).astype(np.float32)
    assert is_silent(sine) is False


# --- Utterance segmentation (energy VAD) -------------------------------------

pytest.importorskip("PySide6")  # _AudioBuffer lives in a Qt module


def _sine(seconds: float, sr: int = 16000, amp: float = 0.3, freq: int = 220):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _silence(seconds: float, sr: int = 16000):
    return np.zeros(int(sr * seconds), dtype=np.float32)


def test_take_utterance_cuts_at_silence():
    from transsnip.modes.audio_subtitle import _AudioBuffer
    buf = _AudioBuffer()
    # leading silence + 1s speech + a pause + a second utterance
    buf.append(np.concatenate([_silence(0.3), _sine(1.0), _silence(0.7), _sine(0.5)]))
    utt = buf.take_utterance(16000)
    assert utt is not None
    secs = utt.size / 16000
    assert 1.0 <= secs <= 1.9                 # ~speech + trailing pause, leading trimmed
    assert buf._buf is not None and buf._buf.size > 0   # second utterance retained


def test_take_utterance_waits_while_talking():
    from transsnip.modes.audio_subtitle import _AudioBuffer
    buf = _AudioBuffer()
    buf.append(_sine(1.0))                    # 1s non-stop speech, no pause yet
    assert buf.take_utterance(16000) is None  # nothing complete → wait
    assert buf._buf.size == 16000             # audio kept for when the pause comes


def test_take_utterance_force_cuts_long_monologue():
    from transsnip.modes.audio_subtitle import _AudioBuffer, _MAX_UTTERANCE_S
    buf = _AudioBuffer()
    buf.append(_sine(_MAX_UTTERANCE_S + 1.0))  # non-stop talk past the cap
    utt = buf.take_utterance(16000)
    assert utt is not None
    secs = utt.size / 16000
    assert _MAX_UTTERANCE_S - 0.5 <= secs <= _MAX_UTTERANCE_S + 0.1   # cut near cap
    assert buf._buf.size > 0                   # leftover kept for the next pass


def test_take_utterance_drains_silence():
    from transsnip.modes.audio_subtitle import _AudioBuffer
    buf = _AudioBuffer()
    buf.append(_silence(2.0))
    assert buf.take_utterance(16000) is None
    assert buf._buf is None or buf._buf.size < 480   # drained to < 1 frame
