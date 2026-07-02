"""Phase-0 probe for the 'audio subtitle' feature (translate video with no subtitles).

Standalone — NOT imported by the app. Measures whether faster-whisper is fast/light
enough on THIS machine's CPU before we commit to building the full audio mode.

Two modes:
  --bench  (default)  Measure model download size, cold load time, transcribe
                      latency for 3s & 5s chunks, and peak RAM — using synthetic
                      audio (no need to play anything). Answers the go/no-go gate.
  --live              Capture real system audio via WASAPI loopback and transcribe
                      it live (play a foreign-language video first). Sanity-checks
                      capture + real-speech quality.

Setup (one-off):
  pip install faster-whisper pyaudiowpatch numpy scipy psutil

Usage:
  python scripts/audio_asr_probe.py                  # bench, tier=small int8
  python scripts/audio_asr_probe.py --tier base
  python scripts/audio_asr_probe.py --live --seconds 30
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

TARGET_SR = 16000


def _cache_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.transsnip")
    p = Path(base) / "transsnip" / "whisper-models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dir_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def _rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return -1.0


def _load_model(tier: str, compute: str):
    from faster_whisper import WhisperModel
    return WhisperModel(tier, device="cpu", compute_type=compute, download_root=str(_cache_dir()))


def bench(tier: str, compute: str) -> int:
    import numpy as np

    cache = _cache_dir()
    before_size = _dir_size_mb(cache)
    print(f"== BENCH  tier={tier}  compute={compute}  device=cpu ==")
    print(f"cache dir: {cache}")
    print(f"RAM baseline: {_rss_mb():.0f} MB")

    print("loading model (first run downloads from HuggingFace)…", flush=True)
    t0 = time.perf_counter()
    model = _load_model(tier, compute)
    load_s = time.perf_counter() - t0
    after_size = _dir_size_mb(cache)
    print(f"  model load: {load_s:.1f}s")
    print(f"  model on-disk: {after_size:.0f} MB (downloaded this run: {after_size - before_size:.0f} MB)")
    print(f"  RAM after load: {_rss_mb():.0f} MB")

    # Synthetic audio: low-amplitude noise so the model actually runs the full
    # encoder/decoder (pure silence + VAD would short-circuit). Latency is
    # content-independent for a given length, so this measures real compute cost.
    rng = np.random.default_rng(0)
    peak_rss = _rss_mb()
    for secs in (3.0, 5.0):
        pcm = (rng.standard_normal(int(TARGET_SR * secs)) * 0.02).astype("float32")
        # warm + timed runs
        for label in ("warm-up", "timed-1", "timed-2"):
            t = time.perf_counter()
            segs, info = model.transcribe(pcm, language=None, vad_filter=False, beam_size=1)
            text = " ".join(s.text for s in segs).strip()
            dt = time.perf_counter() - t
            peak_rss = max(peak_rss, _rss_mb())
            if label != "warm-up":
                rtf = dt / secs
                verdict = "OK (faster than realtime)" if dt < secs else "SLOW (>= chunk!)"
                print(f"  chunk {secs:.0f}s [{label}]: transcribe {dt:.2f}s  "
                      f"(RTF {rtf:.2f}, {verdict})  lang={info.language}")
    print(f"  peak RAM during transcribe: {peak_rss:.0f} MB")

    print("\n== GATE ==")
    print("  PASS nếu: transcribe < chunk (RTF<1), peak RAM <= ~1500MB.")
    print("  (Chất lượng tiếng Việt + capture thật → chạy: --live với video tiếng Việt/Nhật.)")
    return 0


def live(tier: str, compute: str, seconds: int, chunk_s: float) -> int:
    import numpy as np
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        print("pyaudiowpatch chưa cài → không test được loopback. pip install pyaudiowpatch")
        return 1
    try:
        from scipy.signal import resample_poly
        def _resample(x, sr):
            from math import gcd
            g = gcd(int(sr), TARGET_SR)
            return resample_poly(x, TARGET_SR // g, int(sr) // g).astype("float32")
    except ImportError:
        def _resample(x, sr):
            n = int(len(x) * TARGET_SR / sr)
            return np.interp(np.linspace(0, len(x), n, endpoint=False),
                             np.arange(len(x)), x).astype("float32")

    print(f"== LIVE  tier={tier}  compute={compute}  (Ctrl+C để dừng) ==")
    model = _load_model(tier, compute)
    print("model loaded. Hãy PHÁT một video tiếng nước ngoài…\n")

    pa = pyaudio.PyAudio()
    dev = pa.get_default_wasapi_loopback()
    sr = int(dev["defaultSampleRate"])
    ch = int(dev["maxInputChannels"])
    print(f"loopback: {dev['name']}  sr={sr} ch={ch}")
    stream = pa.open(format=pyaudio.paInt16, channels=ch, rate=sr, input=True,
                     input_device_index=dev["index"], frames_per_buffer=int(sr * 0.1))

    buf = np.zeros(0, dtype="float32")
    need = int(TARGET_SR * chunk_s)
    t_end = time.perf_counter() + seconds
    try:
        while time.perf_counter() < t_end:
            raw = np.frombuffer(stream.read(int(sr * 0.1), exception_on_overflow=False), dtype="int16")
            if ch > 1:
                raw = raw.reshape(-1, ch).mean(axis=1)
            mono = (raw.astype("float32") / 32768.0)
            buf = np.concatenate([buf, _resample(mono, sr)])
            if len(buf) >= need:
                chunk, buf = buf[:need], buf[need - int(TARGET_SR * 0.5):]
                t = time.perf_counter()
                segs, info = model.transcribe(chunk, language=None, vad_filter=True, beam_size=1)
                text = " ".join(s.text for s in segs).strip()
                dt = time.perf_counter() - t
                if text:
                    print(f"[{info.language} {dt:.1f}s] {text}")
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream(); stream.close(); pa.terminate()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="capture real system audio")
    ap.add_argument("--tier", default="small", help="tiny|base|small|medium")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--seconds", type=int, default=30, help="live capture duration")
    ap.add_argument("--chunk", type=float, default=4.0, help="live chunk seconds")
    args = ap.parse_args()
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("faster-whisper chưa cài. pip install faster-whisper pyaudiowpatch numpy scipy psutil")
        return 1
    return live(args.tier, args.compute, args.seconds, args.chunk) if args.live \
        else bench(args.tier, args.compute)


if __name__ == "__main__":
    raise SystemExit(main())
