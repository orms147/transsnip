"""Centralised theme controller.

Owns the *current* `Palette`, detects Windows's preferred theme when in
AUTO mode, and emits a Qt signal so widgets that build their own dynamic
stylesheets (FloatingPopup paints its frame manually, for example) can
re-style on switch without an app restart.

Three modes:
- DARK: always cobalt-dark
- LIGHT: always cobalt-light
- AUTO: follow Windows `AppsUseLightTheme` registry key, fall back to DARK
  if the key is missing (Win10 sometimes) or we're not on Windows.

Apps wire this up at startup:

    theme = get_theme()
    theme.apply(QApplication.instance())   # installs global stylesheet
    theme.mode_changed.connect(my_popup.refresh_styles)
    theme.set_mode(ThemeMode.LIGHT)         # switches everything

QSS generation lives in `_build_app_stylesheet()` — that's the place the
tokens (`bg_1`, `accent`, etc.) get baked into literal Qt CSS rules.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from transsnip.ui.tokens import DARK, LIGHT, Palette, ThemeMode, palette_for

log = logging.getLogger(__name__)


class Theme(QObject):
    """Singleton-style theme controller. Get via `get_theme()`."""

    # Emitted whenever the active mode (and therefore palette) changes.
    # Widgets that paint their own surfaces (manual paintEvent on
    # FloatingPopup) subscribe to refresh their cached colors.
    mode_changed = Signal(object)  # Palette

    def __init__(self) -> None:
        super().__init__()
        self._mode: ThemeMode = ThemeMode.DARK
        self._palette: Palette = DARK
        self._app: Optional[QApplication] = None

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def palette(self) -> Palette:
        """Current resolved palette (never returns AUTO — always DARK/LIGHT)."""
        return self._palette

    def set_mode(self, mode: ThemeMode) -> None:
        """Switch theme. AUTO triggers Windows auto-detection."""
        self._mode = mode
        new_palette = self._resolve_palette(mode)
        if new_palette is self._palette:
            return  # no actual change → skip stylesheet rebuild
        self._palette = new_palette
        if self._app is not None:
            self._app.setStyleSheet(_build_app_stylesheet(new_palette))
            # Force re-polish: Qt's CSS engine doesn't automatically reapply
            # the global stylesheet to widgets that already inherited from it.
            # Without unpolish+polish, raw QFormLayout labels and other
            # widgets that have no local setStyleSheet keep their old text
            # color from the previous palette → invisible on the new
            # background. Walks every widget once per theme change which is
            # cheap (a few hundred widgets in TransSnip).
            for widget in self._app.allWidgets():
                style = widget.style()
                if style is None:
                    continue
                style.unpolish(widget)
                style.polish(widget)
                widget.update()
        log.info("Theme switched to %s", mode.value)
        self.mode_changed.emit(new_palette)

    def apply(self, app: QApplication) -> None:
        """Install the current stylesheet onto the QApplication. Call once
        at startup; subsequent `set_mode` calls refresh automatically."""
        self._app = app
        app.setStyleSheet(_build_app_stylesheet(self._palette))

    # ── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_palette(mode: ThemeMode) -> Palette:
        if mode == ThemeMode.AUTO:
            return _detect_windows_palette() or DARK
        return palette_for(mode)


_instance: Optional[Theme] = None


def get_theme() -> Theme:
    """Lazy singleton getter — survives multiple imports."""
    global _instance
    if _instance is None:
        _instance = Theme()
    return _instance


# ── Windows auto-detect ────────────────────────────────────────────────────
def _detect_windows_palette() -> Optional[Palette]:
    """Read Windows's `AppsUseLightTheme` to choose dark/light.

    Registry path: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\
    Themes\\Personalize → AppsUseLightTheme (DWORD: 0 = dark, 1 = light).

    Returns None when we can't read it (non-Windows host, key missing on
    older Win10 builds, perms denied). Caller falls back to DARK.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return LIGHT if int(value) == 1 else DARK
    except (FileNotFoundError, OSError, ValueError) as exc:
        log.debug("Windows theme detect failed: %s", exc)
        return None


# ── Stylesheet builder ─────────────────────────────────────────────────────
def _build_app_stylesheet(p: Palette) -> str:
    """Compose the app-wide Qt stylesheet from a palette.

    Why one big string instead of per-widget QSS:
    - Most controls (`QPushButton`, `QLineEdit`, `QComboBox`, `QScrollBar`)
      use class selectors that benefit from being defined once at app level.
    - When the theme switches, `app.setStyleSheet(new)` replaces this in
      a single shot — no per-widget walk needed for stock controls.

    Widget-specific stylesheets (popup chrome, settings titlebar) still live
    next to those widgets; this is the shared baseline.
    """
    # Inter / JetBrains Mono fall through to system stack — Qt picks the
    # first installed family in the list, so users without Inter installed
    # still get a sensible default rendering.
    return f"""
* {{ font-family: {p.font_ui}; outline: none; }}

QWidget {{
    color: {p.text_1};
    background: transparent;
    font-size: 12px;
}}

QToolTip {{
    color: {p.text_1};
    background: {p.bg_2};
    border: 1px solid {p.border_2};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}}

QPushButton {{
    color: {p.text_1};
    background: {p.bg_2};
    border: 1px solid {p.border_2};
    border-radius: {p.r_btn}px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {p.bg_3}; border-color: {p.border_strong}; }}
QPushButton:pressed {{ background: {p.bg_1}; }}
QPushButton:disabled {{ color: {p.text_mute}; background: {p.bg_1}; border-color: {p.border_1}; }}

QPushButton[primary="true"] {{
    background: {p.accent};
    color: {p.accent_on};
    border-color: {p.accent};
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}

QPushButton[ghost="true"] {{
    background: transparent;
    border: none;
    color: {p.text_2};
    padding: 6px 10px;
}}
QPushButton[ghost="true"]:hover {{ background: {p.bg_2}; color: {p.text_1}; }}

QPushButton[soft="true"] {{
    background: {p.bg_2};
    border-color: {p.border_1};
    color: {p.text_2};
    font-size: 11.5px;
    padding: 5px 10px;
}}
QPushButton[soft="true"]:hover {{ color: {p.text_1}; border-color: {p.border_2}; }}

QLineEdit, QPlainTextEdit, QTextEdit {{
    color: {p.text_1};
    background: {p.bg_2};
    border: 1px solid {p.border_2};
    border-radius: {p.r_input}px;
    padding: 7px 10px;
    selection-background-color: {p.accent_strong};
    selection-color: {p.accent_on};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {p.accent};
}}
QLineEdit:disabled {{ color: {p.text_mute}; background: {p.bg_1}; }}

QComboBox {{
    color: {p.text_1};
    background: {p.bg_2};
    border: 1px solid {p.border_2};
    border-radius: {p.r_input}px;
    padding: 6px 10px;
    min-height: 22px;
}}
QComboBox:hover {{ border-color: {p.border_strong}; }}
QComboBox:focus {{ border-color: {p.accent}; }}
QComboBox::drop-down {{
    /* Reserve the right gutter; the chevron is painted by _ComboBox.paintEvent
       (QSS ::down-arrow image rendering is unreliable, esp. for editable
       combos — it came out blank). width must match _ComboBox._ARROW_W. */
    subcontrol-origin: padding;
    subcontrol-position: right center;
    width: 26px;
    border-left: 1px solid {p.border_2};
}}
QComboBox::drop-down:hover {{ background: {p.bg_3}; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background: {p.bg_2};
    color: {p.text_1};
    border: 1px solid {p.border_2};
    selection-background-color: {p.accent_soft};
    selection-color: {p.text_1};
    padding: 4px;
}}

QMenu {{
    background: {p.bg_1};
    color: {p.text_1};
    border: 1px solid {p.border_2};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    color: {p.text_1};
    background: transparent;
    padding: 6px 24px 6px 14px;
    border-radius: 4px;
    margin: 1px 2px;
}}
QMenu::item:selected {{
    background: {p.accent_soft};
    color: {p.text_1};
}}
QMenu::item:disabled {{
    color: {p.text_mute};
}}
QMenu::separator {{
    height: 1px;
    background: {p.border_1};
    margin: 4px 8px;
}}

QCheckBox {{ color: {p.text_1}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1.5px solid {p.border_strong};
    border-radius: 4px;
    background: {p.bg_2};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
    /* check mark drawn via subcontrol on Windows; users still see fill */
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_3}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent; height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p.text_3}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent; width: 0;
}}

QTabWidget::pane {{
    border: 1px solid {p.border_1};
    border-radius: {p.r_card}px;
    background: {p.bg_1};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {p.text_2};
    padding: 8px 14px;
    border: none;
    margin-right: 2px;
    font-size: 12px;
    font-weight: 500;
}}
QTabBar::tab:hover {{ color: {p.text_1}; }}
QTabBar::tab:selected {{
    color: {p.accent};
    border-bottom: 2px solid {p.accent};
    background: {p.accent_soft};
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}

QGroupBox {{
    border: 1px solid {p.border_1};
    border-radius: {p.r_card}px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 600;
    color: {p.text_1};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: {p.text_1};
}}

QFrame[separator="true"] {{ background: {p.border_1}; }}

QListWidget {{
    background: {p.bg_1};
    border: 1px solid {p.border_1};
    border-radius: {p.r_card}px;
    padding: 4px;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 4px;
    color: {p.text_1};
}}
QListWidget::item:hover {{ background: {p.bg_2}; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text_1}; }}

QTableWidget {{
    background: {p.bg_1};
    border: 1px solid {p.border_1};
    border-radius: {p.r_card}px;
    gridline-color: {p.border_1};
    color: {p.text_1};
}}
QHeaderView::section {{
    background: {p.bg_2};
    color: {p.text_2};
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {p.border_1};
    font-size: 11px;
    font-weight: 600;
}}

QLabel {{ color: {p.text_1}; }}
QLabel[muted="true"] {{ color: {p.text_2}; }}
QLabel[hint="true"] {{ color: {p.text_3}; font-size: 11px; }}
QLabel[mono="true"] {{ font-family: {p.font_mono}; }}
"""
