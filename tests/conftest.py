import os

import pytest

# Widgets in tests render offscreen (no window flashes, works headless/CI).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (Qt allows only one per process,
    and a QCoreApplication created first would block widget tests)."""
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
