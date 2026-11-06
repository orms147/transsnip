"""Real WinRT speech synthesis round-trip (Windows only, no audio playback)."""
from __future__ import annotations

import asyncio
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="WinRT is Windows-only")

pytest.importorskip("winrt.windows.media.speechsynthesis")
pytest.importorskip("winrt.windows.storage.streams")

from transsnip.tts.sapi import SapiGenRunnable, sapi_available  # noqa: E402


def test_sapi_available() -> None:
    assert sapi_available()


def test_synthesize_to_wav(tmp_path) -> None:
    out = tmp_path / "hello.wav"
    runnable = SapiGenRunnable("Hello world.", str(out))
    asyncio.run(runnable._generate())
    data = out.read_bytes()
    assert len(data) > 44
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
