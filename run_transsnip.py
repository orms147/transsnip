"""Frozen-app entry point.

PyInstaller analyses this top-level script (repo root on sys.path) so the
`transsnip` package resolves cleanly. Mirrors `python -m transsnip`.
"""
from transsnip.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
