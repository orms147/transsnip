"""Offline TTS fallback via the Windows built-in speech synthesizer (WinRT).

Edge-TTS needs internet. When it fails (offline, CDN hiccup), we fall back to
`Windows.Media.SpeechSynthesis.SpeechSynthesizer` — the same WinRT stack that
powers Narrator. It's fully offline, uses voices already installed on the box,
and reuses the `winsdk` dependency we already ship for Windows OCR (no new dep).

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
        import winsdk.windows.media.speechsynthesis  # noqa: F401
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
        from winsdk.windows.media.speechsynthesis import SpeechSynthesizer
        from winsdk.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        # Returns a SpeechSynthesisStream of WAV (PCM) bytes.
        stream = await synth.synthesize_text_to_stream_async(self._text)
        size = stream.size
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(size)
        data = bytes(reader.read_bytes(size))
        Path(self._out_path).write_bytes(data)
