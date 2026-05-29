"""Design tokens — colors, fonts, radii, shadows — for the Cobalt theme.

Two palettes shipped: dark (default) + light. A Palette dataclass is the
single source of truth — `theme.py` interpolates these values into Qt
stylesheets at app startup and again on theme switch.

Why a dataclass instead of CSS-vars:
- Qt doesn't have cascading custom properties; every QSS rule needs literal
  values. Centralising tokens here means stylesheets read like the design
  CSS (`color: var(--text-1)` ↔ `f"color: {palette.text_1}"`) without us
  hand-typing the same hex 30× across widget modules.
- A typed Palette catches drift: if the design adds `accent_strong`, mypy /
  IDE points at every widget that needs to consume it.

When the design tokens change (designer updates Cobalt), only this file +
`theme.py` need to be touched.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ThemeMode(str, Enum):
    DARK = "dark"
    LIGHT = "light"
    # AUTO follows Windows ColorPrevalence / WallpaperLightTheme via theme.py.
    AUTO = "auto"


@dataclass(frozen=True)
class Palette:
    """Color, font, geometry tokens for one theme mode.

    Field names mirror the design CSS variables so a designer looking at
    `styles.css` can match every `--text-1` here to `text_1`. Underscores
    instead of dashes for Python conventions, otherwise identical.
    """

    # Surface depth — bg_0 deepest, bg_3 most raised. Designer's intent:
    # bg_0 = root background (artboard), bg_1 = popup base, bg_2 = sections,
    # bg_3 = hover / pressed.
    bg_0: str
    bg_1: str
    bg_2: str
    bg_3: str
    bg_elev: str  # elevated surfaces with subtle alpha (toolbar, sticky bars)

    border_1: str  # subtle (hairline section dividers)
    border_2: str  # default (around inputs, cards)
    border_strong: str  # focused / hovered border

    text_1: str   # primary
    text_2: str   # secondary / dim
    text_3: str   # tertiary / footer hints
    text_mute: str  # disabled

    accent: str
    accent_hover: str
    accent_soft: str  # tinted accent backgrounds (selected rows, tags)
    accent_strong: str
    accent_on: str  # text color on accent (white in both themes)

    success: str
    warning: str
    danger: str

    # Shadows — pre-baked QGraphicsDropShadowEffect equivalent for popups
    # & cards. Format mirrors CSS box-shadow stacks; theme.py parses them
    # for QGraphicsEffect or uses them inline in QSS where supported.
    shadow_popup: str
    shadow_card: str

    # Fonts — Inter for UI, JetBrains Mono for code/keys. Theme.py loads
    # these from bundled .ttf if available, falls back to system stack.
    font_ui: str
    font_mono: str

    # Geometry — corner radii in px. r_popup is the main popup outer radius,
    # r_card for sections, r_btn / r_input for controls.
    r_popup: int
    r_card: int
    r_btn: int
    r_input: int
    r_pill: int

    # Typography subtleties from the design (matches `--letter-*` vars).
    letter_tight: str = "-0.01em"
    letter_caps: str = "0.06em"


# ── Cobalt Dark (default) ──────────────────────────────────────────────────
DARK = Palette(
    bg_0="#0b0c10",
    bg_1="#131519",
    bg_2="#1a1d24",
    bg_3="#232730",
    bg_elev="rgba(20, 22, 28, 0.92)",
    border_1="rgba(255, 255, 255, 0.07)",
    border_2="rgba(255, 255, 255, 0.12)",
    border_strong="rgba(255, 255, 255, 0.20)",
    text_1="#ecedef",
    text_2="#a4a9b3",
    text_3="#6b717c",
    text_mute="#4a4f59",
    accent="#818cf8",
    accent_hover="#a5b4fc",
    accent_soft="rgba(129, 140, 248, 0.13)",
    accent_strong="#6366f1",
    accent_on="#ffffff",
    success="#34d399",
    warning="#fbbf24",
    danger="#f87171",
    shadow_popup=(
        "0 32px 60px -20px rgba(0, 0, 0, 0.65), "
        "0 12px 28px -10px rgba(0, 0, 0, 0.45)"
    ),
    shadow_card="0 8px 24px -12px rgba(0, 0, 0, 0.55)",
    font_ui="Inter, system-ui, -apple-system, sans-serif",
    font_mono="JetBrains Mono, ui-monospace, Consolas, monospace",
    r_popup=12,
    r_card=8,
    r_btn=7,
    r_input=7,
    r_pill=999,
)


# ── Cobalt Light ───────────────────────────────────────────────────────────
LIGHT = Palette(
    bg_0="#f6f7fa",
    bg_1="#ffffff",
    bg_2="#f1f3f8",
    bg_3="#e6e9f0",
    bg_elev="rgba(255, 255, 255, 0.96)",
    border_1="rgba(15, 23, 42, 0.06)",
    border_2="rgba(15, 23, 42, 0.11)",
    border_strong="rgba(15, 23, 42, 0.20)",
    text_1="#0f1320",
    text_2="#4c5365",
    text_3="#7a8294",
    text_mute="#b5bbc7",
    accent="#4f59e6",
    accent_hover="#6b75f5",
    accent_soft="rgba(79, 89, 230, 0.10)",
    accent_strong="#3941d1",
    accent_on="#ffffff",
    success="#059669",
    warning="#b45309",
    danger="#dc2626",
    shadow_popup=(
        "0 28px 60px -22px rgba(20, 30, 60, 0.30), "
        "0 10px 24px -8px rgba(20, 30, 60, 0.14)"
    ),
    shadow_card="0 6px 18px -10px rgba(20, 30, 60, 0.20)",
    font_ui="Inter, system-ui, -apple-system, sans-serif",
    font_mono="JetBrains Mono, ui-monospace, Consolas, monospace",
    r_popup=12,
    r_card=8,
    r_btn=7,
    r_input=7,
    r_pill=999,
)


def palette_for(mode: ThemeMode) -> Palette:
    """Resolve a Palette for a given mode. AUTO is resolved upstream in
    `theme.py` (it needs Windows registry access); calling this with AUTO
    returns DARK as a safe fallback.
    """
    if mode == ThemeMode.LIGHT:
        return LIGHT
    return DARK
