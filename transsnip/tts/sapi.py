"""Offline TTS fallback via the Windows built-in speech synthesizer (WinRT).

Edge-TTS needs internet. When it fails (offline, CDN hiccup), we fall back to
`Windows.Media.SpeechSynthesis.SpeechSynthesizer` — the same WinRT stack that
powers Narrator. It's fully offline, uses voices already installed on the box,
and uses the same pywinrt (`winrt-*`) projection we ship for Windows OCR.

Quality is below Edge's neural voices, but "works with no internet" beats "no
audio at all" for a learner checking pronunciation on a flaky connection.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

log = logging.getLogger(__name__)


def sapi_available() -> bool:
    """True if the WinRT speech-synthesis projection can be imported (Windows)."""
    if sys.platform != "win32":
        return False
    try:
        from transsnip.utils.win_dll import preload_msvcp140
        preload_msvcp140()  # before any winrt import — see utils/win_dll.py
        import winrt.windows.media.speechsynthesis
        import winrt.windows.storage.streams  # noqa: F401
        return True
    except ImportError:
        return False


class _SapiSignals(QObject):
    ready = Signal(str)   # path to generated wav
    failed = Signal(str)


class SapiGenRunnable(QRunnable):
    """Synthesize `text` to a WAV file off the main thread, WinRT (offline)."""

    def __init__(self, text: str, out_path: str) -> None:
        super().__init__()
        self._text = text
        self._out_path = out_path
        self.signals = _SapiSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            asyncio.run(self._generate())
        except Exception as exc:  # noqa: BLE001 — worker must not raise
            log.warning("SAPI synthesis failed: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        self.signals.ready.emit(self._out_path)

    async def _generate(self) -> None:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        # Returns a SpeechSynthesisStream of WAV (PCM) bytes.
        stream = await synth.synthesize_text_to_stream_async(self._text)
        size = stream.size
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(size)
        # winrt 3.x: read_bytes fills a caller-supplied writable buffer.
        data = bytearray(size)
        reader.read_bytes(data)
        Path(self._out_path).write_bytes(data)
