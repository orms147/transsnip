"""faster-whisper ASR wrapper for the audio-subtitle mode.

faster-whisper (CTranslate2) runs Whisper int8 on CPU at ~0.25-0.4 RTF for short
speech chunks (measured: small int8 transcribes 7-10s of speech in ~2.5s, peak
RAM ~400MB — see scripts/audio_asr_probe.py). A multilingual Whisper model is
REQUIRED because Vietnamese is the target and the fast English/European ASR
models (e.g. NVIDIA Parakeet) don't cover Vietnamese.

Heavy deps are imported lazily so the base app runs without the `[audio]` extra.
The model (~460MB for `small`) is fetched on first use to a per-user cache dir,
NOT bundled in the installer.

v1 is chunk-based and stateless. A later upgrade is LocalAgreement-2 streaming
(ufal/whisper_streaming / WhisperLiveKit) for lower latency + less caption churn.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

# Per-tier rough on-disk size (float16 CT2 model.bin; int8 quantizes at load).
TIER_SIZE_MB = {"tiny": 75, "base": 145, "small": 480, "medium": 1500, "large-v3": 3000}

# --- Decoding / quality knobs -------------------------------------------------
# beam_size=5 (not greedy 1): RTF headroom is large (~0.3 measured), so we spend
# it on accuracy. The three thresholds below are OpenAI Whisper's own silence/
# gibberish heuristics, applied per-segment to drop hallucinations.
_BEAM_SIZE = 5
_NO_SPEECH_MAX = 0.6      # seg.no_speech_prob above this → likely silence
_LOGPROB_MIN = -1.0       # seg.avg_logprob below this → low-confidence garbage
_COMPRESSION_MAX = 2.4    # seg.compression_ratio above this → repetition loop
# Lock the auto-detected language once a chunk is at least this confident, so a
# single-language video stops re-detecting (and mis-detecting "ru"/"en" on quiet
# chunks). Reset per session via reset_language().
_LANG_LOCK_PROB = 0.65

# Whisper's notorious phantom outputs on silence / music / non-speech. Matched
# only when a segment's ENTIRE text equals one of these (normalized), so real
# speech containing these words is unaffected.
_HALLUCINATION_PHRASES = frozenset({
    "you", "thank you", "thanks for watching", "thanks for watching!",
    "bye", "bye bye", "okay", "please subscribe", "subscribe",
    "谢谢观看", "谢谢大家", "请订阅", "字幕由amara.org社区提供", "下次再见",
    "請不吝點贊 訂閱 轉發 打賞支持明鏡與點點欄目",
    "ご視聴ありがとうございました", "視聴ありがとうございました",
    "시청해주셔서 감사합니다",
})


def _is_hallucination(text: str) -> bool:
    """True if `text` is (just) a known Whisper phantom phrase."""
    t = text.strip().lower().rstrip(".!?。！？、，, ").strip()
    return t == "" or t in _HALLUCINATION_PHRASES


def _add_cuda_dll_dirs() -> None:
    """Windows: make CUDA libs from the `nvidia-*-cu12` pip wheels loadable.

    Those wheels drop cublas/cudnn DLLs under `site-packages/nvidia/*/bin`, which
    isn't on the DLL search path — so CTranslate2 can't find them without this.
    Lets `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` enable the GPU with
    no manual PATH editing. Fully defensive: any failure just leaves things as-is.
    """
    if os.name != "nt":
        return
    try:
        import site

        roots = list(site.getsitepackages())
        user_site = site.getusersitepackages()
        if isinstance(user_site, str):
            roots.append(user_site)
        try:                       # also resolve the nvidia namespace pkg directly
            import nvidia
            roots.extend(str(Path(p).parent) for p in nvidia.__path__)
        except Exception:  # noqa: BLE001
            pass

        seen: set[str] = set()
        for base in roots:
            nvidia_dir = Path(base) / "nvidia"
            if not nvidia_dir.is_dir():
                continue
            for bindir in nvidia_dir.glob("*/bin"):
                bd = str(bindir)
                if bd in seen:
                    continue
                seen.add(bd)
                try:
                    os.add_dll_directory(bd)
                except OSError:
                    pass
                # The part that actually works: CTranslate2 loads cublas/cudnn
                # with plain LoadLibrary, which searches PATH — NOT the
                # add_dll_directory list. So prepend the bin dir to PATH too.
                os.environ["PATH"] = bd + os.pathsep + os.environ.get("PATH", "")
    except Exception:  # noqa: BLE001 — best-effort; CPU still works without it
        pass


def asr_available() -> bool:
    """True if faster-whisper is importable (the optional `[audio]` extra)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def whisper_cache_dir() -> Path:
    """Writable per-user dir for Whisper models — `%APPDATA%/transsnip/whisper-models`.

    NOT `ocr.models.models_dir()`: that resolves to the read-only `sys._MEIPASS`
    bundle in a frozen install, but Whisper models are fetched at runtime and
    must live somewhere writable (mirrors `config.settings._settings_path`).
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.transsnip")
    path = Path(base) / "transsnip" / "whisper-models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_silent(pcm: "np.ndarray", rms_threshold: float = 0.005) -> bool:
    """Pure-numpy VAD gate: True when the chunk's RMS is below `rms_threshold`.

    Cheap pre-filter so we don't spend an ASR pass on silence/near-silence.
    """
    import numpy as np

    if pcm.size == 0:
        return True
    return float(np.sqrt(np.mean(np.square(pcm, dtype=np.float64)))) < rms_threshold


class WhisperTranscriber:
    """Lazy-loaded faster-whisper model. Build once, call `transcribe()` per chunk."""

    def __init__(
        self,
        tier: str = "small",
        compute_type: str = "auto",
        source_lang: Optional[str] = None,
    ) -> None:
        self._tier = tier
        # "auto" → pick per device at load (CUDA→float16, CPU→int8). An explicit
        # value ("int8"/"float16"/…) is honored on whatever device is chosen.
        self._requested_compute = compute_type
        self._device = "cpu"          # resolved in load()
        self._compute_type = "int8"   # resolved in load()
        # None → Whisper auto-detects per chunk. Whisper wants ISO-639-1 ("zh",
        # "ja"), NOT BCP-47 ("zh-Hans", "en-US") — passing the latter raises and
        # the chunk silently yields nothing. Normalize: strip the region subtag,
        # and treat ""/"auto" as auto-detect.
        self._lang = self._normalize_lang(source_lang)
        self._locked_lang: Optional[str] = None  # auto-detected lock (per session)
        self._model = None

    @staticmethod
    def _normalize_lang(tag: Optional[str]) -> Optional[str]:
        if not tag or tag.lower() == "auto":
            return None
        return tag.split("-")[0].lower()

    def reset_language(self) -> None:
        """Clear the auto-detected language lock — call when (re)starting a
        session so a video in a different language gets re-detected.
        """
        self._locked_lang = None

    def is_available(self) -> bool:
        return asr_available()

    def expected_download_mb(self) -> int:
        return TIER_SIZE_MB.get(self._tier, 480)

    def _resolve_device(self) -> tuple[str, str]:
        """Pick (device, compute_type): CUDA GPU if present, else CPU.

        An explicit `compute_type` (anything but "auto") overrides the per-device
        default. Any detection error degrades silently to CPU/int8.
        """
        device, compute = "cpu", "int8"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                device, compute = "cuda", "float16"
        except Exception:  # noqa: BLE001 — no CUDA / old CT2 → just use CPU
            pass
        if self._requested_compute and self._requested_compute != "auto":
            compute = self._requested_compute
        return device, compute

    def load(self) -> None:
        """Construct the model (downloads on first use). Idempotent.

        Uses the GPU when available. The CUDA *constructor* succeeds even when
        cuBLAS/cuDNN are missing — those only load at inference — so we run a
        tiny warmup transcription to actually validate the GPU. If anything
        fails we rebuild on CPU/int8, so the feature never silently dies on a
        box with a half-installed CUDA stack (and the warmup also primes the
        model so the first real chunk isn't slow).
        """
        if self._model is not None:
            return
        _add_cuda_dll_dirs()   # let pip-installed CUDA wheels be found (Windows)
        from faster_whisper import WhisperModel

        device, compute = self._resolve_device()
        try:
            model = WhisperModel(
                self._tier, device=device, compute_type=compute,
                download_root=str(whisper_cache_dir()),
            )
            if device != "cpu":
                self._warmup(model)            # forces cuBLAS/cuDNN load — may raise
        except Exception as exc:  # noqa: BLE001
            if device == "cpu":
                raise
            log.warning(
                "Whisper GPU unavailable (%s) — falling back to CPU/int8. "
                "To enable GPU: pip install nvidia-cublas-cu12 nvidia-cudnn-cu12",
                exc,
            )
            device, compute = "cpu", "int8"
            model = WhisperModel(
                self._tier, device=device, compute_type=compute,
                download_root=str(whisper_cache_dir()),
            )
        self._model = model
        self._device, self._compute_type = device, compute
        log.info(
            "Whisper model loaded: tier=%s device=%s compute=%s",
            self._tier, device, compute,
        )

    @staticmethod
    def _warmup(model) -> None:
        """Run one real inference to confirm GPU libraries actually load."""
        import numpy as np

        tone = (0.05 * np.sin(np.linspace(0, 220, 16000, dtype=np.float32))).astype(
            np.float32
        )
        segments, _info = model.transcribe(tone, vad_filter=False, beam_size=1)
        list(segments)  # consume the lazy generator → triggers the GPU kernels

    def transcribe(self, pcm: "np.ndarray") -> str:
        """float32 mono @16 kHz → recognized text ('' if silent/empty).

        Drops Whisper's silence/music hallucinations (e.g. "Thank you.", "Bye.")
        via per-segment no_speech_prob / avg_logprob / compression_ratio, and
        locks onto the first confidently-detected language to stop per-chunk
        mis-detection on quiet passages.
        """
        if self._model is None:
            self.load()
        if is_silent(pcm):
            return ""

        lang = self._lang or self._locked_lang
        segments, info = self._model.transcribe(
            pcm,
            language=lang,
            vad_filter=True,
            beam_size=_BEAM_SIZE,
        )
        # Lock the language once we're confident (only while still auto-detecting).
        if lang is None and getattr(info, "language_probability", 0.0) >= _LANG_LOCK_PROB:
            self._locked_lang = info.language
            log.info(
                "Whisper language locked: %s (p=%.2f)",
                info.language, info.language_probability,
            )

        kept: list[str] = []
        for seg in segments:
            if seg.no_speech_prob > _NO_SPEECH_MAX and seg.avg_logprob < _LOGPROB_MIN:
                continue                                   # likely silence
            if seg.compression_ratio > _COMPRESSION_MAX:
                continue                                   # repetition loop
            text = seg.text.strip()
            if not text or _is_hallucination(text):
                continue
            kept.append(text)
        return " ".join(kept).strip()
