"""Benchmark faster-whisper tiers/decoding knobs on zh/en/ja TTS clips.

Usage:
    python scripts/asr_bench.py --tiers base small large-v3-turbo [--device cpu]
           [--cache DIR] [--out results.json]

Clips are synthesized with edge-tts (online, cached as mp3 in --cache), decoded
to 16 kHz mono float32 via faster_whisper.decode_audio. Variants: clean, noisy
(synthetic music-ish bed @10 dB SNR, seeded), chunked (split at midpoint, two
transcribe calls joined -- a worst-case mid-word cut). Metric: CER after
normalisation. Prints a table; writes raw JSON.

The `app` config runs the app's own WhisperTranscriber.transcribe (phantom
filter, CJK join, zh script normalisation) and adds segmentation variants fed
through the app's real _AudioBuffer:
- `long` / `long_sil600`: two sentences, natural pauses kept, utterances cut at
  the app's silence gap (350 ms) vs a 600 ms gap.
- `nonstop` / `nonstop_hardcap`: three sentences with every pause squashed to
  200 ms, so only the force-cut can split them — quiet-point cut vs a hard cut
  exactly at the cap (the previous behaviour).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

SENTENCES = {
    "zh": [
        "你今天怎么这么晚才回来？",
        "我跟你说，这件事真的不是我干的。",
        "我们先去吃饭吧，我快饿死了。",
        "你还记得那天晚上发生了什么吗？",
        "别担心，一切都会好起来的。",
        "这个计划太冒险了，我不同意。",
        "老板说明天早上九点开会。",
        "你到底想让我怎么做？",
    ],
    "ja": [
        "今日はどうしてこんなに遅かったの？",
        "ちょっと待って、それ本当に言ってるの？",
        "心配しないで、きっと大丈夫だよ。",
        "あの時のこと、まだ覚えてる？",
        "お腹すいたから、何か食べに行こうよ。",
        "明日の朝九時に会議があるって。",
        "そんなこと、私には関係ないでしょう。",
        "ありがとう、本当に助かりました。",
    ],
    "en": [
        "Why did you come home so late tonight?",
        "I'm telling you, I had nothing to do with it.",
        "Let's grab something to eat, I'm starving.",
        "Do you still remember what happened that night?",
        "Don't worry, everything is going to be fine.",
        "This plan is way too risky, I'm not doing it.",
        "The boss wants a meeting at nine tomorrow morning.",
        "What exactly do you want me to do?",
    ],
}
VOICES = {
    "zh": ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"],
    "ja": ["ja-JP-NanamiNeural", "ja-JP-KeitaNeural"],
    "en": ["en-US-AriaNeural", "en-GB-RyanNeural"],
}
PROMPTS = {"zh": "以下是普通话的句子，使用简体中文。", "ja": "以下は日本語の会話です。", "en": None}
TRAD_CHARS = set("這說會們時來國對還點個麼裡後過嗎從開發現讓見際話謝")
SR = 16000

# config name -> (pinned_lang, beam, use_prompt, without_timestamps); "app" is special
CONFIGS = {
    "app": None,
    "pin_b5": (True, 5, False, False),       # current app behaviour
    "pin_b1": (True, 1, False, False),
    "auto_b5": (False, 5, False, False),
    "pin_b5_prompt": (True, 5, True, False),
    "pin_b5_nots": (True, 5, False, True),
    "pin_b1_prompt_nots": (True, 1, True, True),
}


async def _tts(text: str, voice: str, path: Path) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice).save(str(path))


def build_clips(cache: Path) -> list[dict]:
    from faster_whisper import decode_audio
    cache.mkdir(parents=True, exist_ok=True)
    clips = []
    for lang, sents in SENTENCES.items():
        for i, text in enumerate(sents):
            voice = VOICES[lang][i % 2]
            p = cache / f"{lang}_{i}_{voice}.mp3"
            if not p.exists() or p.stat().st_size == 0:
                asyncio.run(_tts(text, voice, p))
            pcm = decode_audio(str(p), sampling_rate=SR).astype(np.float32)
            clips.append({"lang": lang, "text": text, "voice": voice, "pcm": pcm})
    return clips


def music_noise(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for f in rng.choice([110, 147, 196, 220, 262, 330, 392, 440, 523], 5, replace=False):
        env = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.5, 2) * t)
        sig += env * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    spec /= np.sqrt(np.maximum(np.arange(len(spec)), 1))      # 1/f -> pink
    pink = np.fft.irfft(spec, n)
    sig = sig / np.std(sig) + 0.7 * pink / np.std(pink)
    return sig


def add_noise(pcm: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    nz = music_noise(len(pcm), seed)
    ps = np.mean(pcm.astype(np.float64) ** 2)
    nz *= np.sqrt(ps / (10 ** (snr_db / 10)) / np.mean(nz ** 2))
    return np.clip(pcm + nz, -1, 1).astype(np.float32)


SOURCE_TAG = {"zh": "zh-Hans", "ja": "ja", "en": "en"}


def _trim(pcm: np.ndarray, thr: float = 0.01) -> np.ndarray:
    """Drop leading/trailing near-silence so spliced sentences run together."""
    frame = SR // 100
    n = len(pcm) // frame
    rms = np.sqrt(np.mean(pcm[: n * frame].reshape(n, frame) ** 2, axis=1))
    idx = np.flatnonzero(rms > thr)
    if idx.size == 0:
        return pcm
    return pcm[idx[0] * frame:(idx[-1] + 1) * frame]


def _squash_pauses(pcm: np.ndarray, keep_ms: int = 200, thr: float = 0.01) -> np.ndarray:
    """Shorten every quiet run to `keep_ms` — no gap long enough to end an utterance."""
    frame = SR // 100
    n = len(pcm) // frame
    frames = pcm[: n * frame].reshape(n, frame)
    quiet = np.sqrt(np.mean(frames ** 2, axis=1)) < thr
    keep, run = [], 0
    for i in range(n):
        run = run + 1 if quiet[i] else 0
        if run <= keep_ms // 10:
            keep.append(i)
    return frames[keep].reshape(-1)


def _joined(group: list[dict], lang: str, pcm: np.ndarray) -> dict:
    sep = " " if lang == "en" else ""
    return {"lang": lang, "text": sep.join(c["text"] for c in group), "pcm": pcm}


def long_inputs(clips: list[dict]) -> tuple[list[dict], list[dict]]:
    """(two-sentence natural, three-sentence non-stop) inputs per language."""
    pairs, nonstop = [], []
    for lang in SENTENCES:
        cs = [c for c in clips if c["lang"] == lang]
        for i in range(len(cs) - 1):          # sliding: more samples
            g = cs[i:i + 2]
            pairs.append(_joined(g, lang, np.concatenate([_trim(c["pcm"]) for c in g])))
        for i in range(len(cs) - 2):
            g = cs[i:i + 3]
            pcm = _squash_pauses(np.concatenate([_trim(c["pcm"]) for c in g]))
            nonstop.append(_joined(g, lang, pcm))
    return pairs, nonstop


def segment(pcm: np.ndarray, mode: str) -> list[np.ndarray]:
    """Feed pcm through the app's _AudioBuffer like the capture thread does."""
    from transsnip.modes import audio_subtitle as A
    if mode == "hardcap":
        cap = int(A._MAX_UTTERANCE_S * SR)
        return [pcm[i:i + cap] for i in range(0, len(pcm), cap) if pcm[i:i + cap].size]
    saved = A._MIN_SILENCE_MS
    if mode == "sil600":
        A._MIN_SILENCE_MS = 600
    try:
        # Stream it like the app: capture appends small blocks, the ASR loop
        # polls take_utterance() every ~100 ms. A trailing pause closes the tail.
        buf = A._AudioBuffer()
        stream = np.concatenate([pcm, np.zeros(SR, dtype=np.float32)])
        step = SR // 10
        parts = []
        for i in range(0, len(stream), step):
            buf.append(stream[i:i + step])
            while (u := buf.take_utterance(SR)) is not None:
                parts.append(u)
        return parts
    finally:
        A._MIN_SILENCE_MS = saved


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if not (unicodedata.category(c)[0] in "PSZ" or c.isspace()))


def cer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return prev[-1] / len(r)


def run_one(model, pcm, lang, cfg, transcriber=None) -> tuple[str, str]:
    if cfg is None:                     # "app": the app's own transcribe()
        return transcriber[lang].transcribe(pcm), lang
    pinned, beam, use_prompt, nots = cfg
    segs, info = model.transcribe(
        pcm, language=lang if pinned else None, vad_filter=True, beam_size=beam,
        initial_prompt=PROMPTS[lang] if use_prompt else None,
        without_timestamps=nots, condition_on_previous_text=False,
    )
    return "".join(s.text for s in segs).strip(), info.language


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", nargs="+", default=["base", "small"])
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute", default=None)
    ap.add_argument("--configs", nargs="+", default=list(CONFIGS))
    ap.add_argument("--cache", default=os.path.join(os.environ.get("TEMP", "."), "asr_clips"))
    ap.add_argument("--out", default="asr_bench_results.json")
    a = ap.parse_args()

    import psutil
    from faster_whisper import WhisperModel
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from transsnip.asr.whisper import WhisperTranscriber, whisper_cache_dir

    clips = build_clips(Path(a.cache))
    print(f"{len(clips)} clips, durations {min(len(c['pcm']) for c in clips)/SR:.1f}-"
          f"{max(len(c['pcm']) for c in clips)/SR:.1f}s", flush=True)
    for k, c in enumerate(clips):
        c["noisy"] = add_noise(c["pcm"], 10.0, seed=k)

    proc = psutil.Process()
    results = []
    for tier in a.tiers:
        t0 = time.time()
        model = WhisperModel(tier, device=a.device,
                             compute_type=a.compute or ("int8" if a.device == "cpu" else "float16"),
                             download_root=str(whisper_cache_dir()))
        print(f"[{tier}] load {time.time()-t0:.1f}s", flush=True)
        run_one(model, clips[0]["pcm"], "zh", CONFIGS["pin_b5"])     # warm-up
        peak = proc.memory_info().rss
        trans = {}
        for lang in SENTENCES:
            t = WhisperTranscriber(tier=tier, source_lang=SOURCE_TAG[lang])
            t._model = model                  # share the loaded model
            trans[lang] = t
        pairs, nonstop = long_inputs(clips)
        seg_mode = {"long": "app", "long_sil600": "sil600",
                    "nonstop": "app", "nonstop_hardcap": "hardcap"}
        for cname in a.configs:
            cfg = CONFIGS[cname]
            jobs = [(c, v) for c in clips for v in ("clean", "noisy", "chunked")]
            if cfg is None:
                jobs += [(c, v) for c in pairs for v in ("long", "long_sil600")]
                jobs += [(c, v) for c in nonstop for v in ("nonstop", "nonstop_hardcap")]
            for c, var in jobs:
                pcm = c["noisy"] if var == "noisy" else c["pcm"]
                sep = " " if c["lang"] == "en" else ""
                t1 = time.perf_counter()
                if var in seg_mode:
                    parts = segment(pcm, seg_mode[var])
                    hyp = sep.join(run_one(model, p, c["lang"], cfg, trans)[0] for p in parts)
                    dl = c["lang"]
                elif var == "chunked":
                    m = len(pcm) // 2
                    h1, l1 = run_one(model, pcm[:m], c["lang"], cfg, trans)
                    h2, _ = run_one(model, pcm[m:], c["lang"], cfg, trans)
                    hyp, dl = (h1 + sep + h2), l1
                else:
                    hyp, dl = run_one(model, pcm, c["lang"], cfg, trans)
                dt = time.perf_counter() - t1
                peak = max(peak, proc.memory_info().rss)
                results.append({
                    "tier": tier, "cfg": cname, "lang": c["lang"], "var": var,
                    "ref": c["text"], "hyp": hyp, "det_lang": dl,
                    "cer": cer(c["text"], hyp), "rtf": dt / (len(pcm) / SR),
                    "trad": sum(ch in TRAD_CHARS for ch in hyp),
                })
            sub = [r for r in results if r["tier"] == tier and r["cfg"] == cname]
            vars_ = ["clean", "noisy", "chunked"]
            if cfg is None:
                vars_ += ["long", "long_sil600", "nonstop", "nonstop_hardcap"]
            print(f"  {cname:20s} " + " ".join(
                f"{L}/{V}:{np.mean([r['cer'] for r in sub if r['lang']==L and r['var']==V]):.3f}"
                for L in ("zh", "ja", "en") for V in vars_)
                + f" rtf={np.mean([r['rtf'] for r in sub]):.3f}", flush=True)
        print(f"[{tier}] peak RSS {peak/2**20:.0f} MB", flush=True)
        del model
        Path(a.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
