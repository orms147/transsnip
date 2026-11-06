"""Per-user data locations — one place that knows where TransSnip writes.

Everything the app persists (settings, history, translation cache, logs,
downloaded Whisper models) lives under `%APPDATA%\\transsnip`. Resolved on
every call (not at import) so tests can point `APPDATA` at a temp dir.
"""
from __future__ import annotations

import os
from pathlib import Path


def app_data_dir(*parts: str) -> Path:
    """`%APPDATA%\\transsnip[\\parts…]`, created if missing.

    Falls back to `~/.transsnip/transsnip` off-Windows (dev boxes, CI).
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.transsnip")
    path = Path(base, "transsnip", *parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
