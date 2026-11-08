"""Whisper model loading: cached on disk → no network; loaded once per process;
a failed GPU is never retried (a second CUDA attempt can hang)."""
from __future__ import annotations

import sys
import types

import pytest

from transsnip.asr import whisper


@pytest.fixture
def fake_fw(monkeypatch):
    """Fake faster_whisper: records model builds and download calls."""
    calls = {"built": [], "download": [], "warmup_fail": False}

    class FakeModel:
        def __init__(self, path, device, compute_type, cpu_threads):
            calls["built"].append((path, device, compute_type))
            self.device = device

        def transcribe(self, *a, **k):
            if self.device != "cpu" and calls["warmup_fail"]:
                raise RuntimeError("Library cublas64_12.dll is not found")
            return iter(()), None

    def download_model(tier, cache_dir=None, local_files_only=False):
        calls["download"].append((tier, local_files_only))
        if local_files_only and tier not in calls.setdefault("cached", set()):
            raise FileNotFoundError(tier)
        calls["cached"].add(tier)
        return f"/models/{tier}"

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeModel
    utils = types.ModuleType("faster_whisper.utils")
    utils.download_model = download_model
    fw.utils = utils
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    monkeypatch.setattr(whisper, "_MODELS", {})
    monkeypatch.setattr(whisper, "_GPU_FAILED", False)
    monkeypatch.setattr(whisper, "whisper_cache_dir", lambda: "/cache")
    return calls


def _force_device(monkeypatch, device):
    monkeypatch.setattr(whisper.WhisperTranscriber, "_resolve_device",
                        lambda self: (device, "float16" if device == "cuda" else "int8"))


def test_cached_model_loads_without_network(fake_fw, monkeypatch):
    _force_device(monkeypatch, "cpu")
    fake_fw["cached"] = {"small"}
    whisper.WhisperTranscriber("small").load()
    assert fake_fw["download"] == [("small", True)]   # local lookup only


def test_first_use_downloads_once(fake_fw, monkeypatch):
    _force_device(monkeypatch, "cpu")
    whisper.WhisperTranscriber("small").load()
    assert fake_fw["download"] == [("small", True), ("small", False)]
    assert whisper.is_model_cached("small")


def test_new_transcriber_reuses_loaded_model(fake_fw, monkeypatch):
    """Settings reload builds a new transcriber — the model must not reload."""
    _force_device(monkeypatch, "cpu")
    fake_fw["cached"] = {"small"}
    whisper.WhisperTranscriber("small", source_lang="zh-Hans").load()
    whisper.WhisperTranscriber("small", source_lang="ja").load()
    assert len(fake_fw["built"]) == 1


def test_failed_gpu_is_not_retried(fake_fw, monkeypatch):
    _force_device(monkeypatch, "cuda")
    fake_fw["cached"] = {"small"}
    fake_fw["warmup_fail"] = True
    whisper.WhisperTranscriber("small").load()
    assert [b[1] for b in fake_fw["built"]] == ["cuda", "cpu"]
    # Next session (new transcriber after a Settings save): straight to CPU,
    # and the CPU model already loaded is reused.
    whisper.WhisperTranscriber("small").load()
    assert [b[1] for b in fake_fw["built"]] == ["cuda", "cpu"]


def test_changing_tier_loads_the_new_one(fake_fw, monkeypatch):
    _force_device(monkeypatch, "cpu")
    fake_fw["cached"] = {"small", "base"}
    whisper.WhisperTranscriber("small").load()
    whisper.WhisperTranscriber("base").load()
    assert [b[0] for b in fake_fw["built"]] == ["/models/small", "/models/base"]
    assert len(whisper._MODELS) == 1   # only the latest kept in RAM
