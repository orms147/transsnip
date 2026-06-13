"""Line-stroke 16×16 SVG icon set, painted into QIcon on demand.

Ported from the Cobalt design's `ICON_PATHS` (tokens.jsx). Same 1.5px stroke,
round caps & joins; we substitute the stroke color at paint time so the icon
recolors with theme switches without re-importing assets.

Why SVG instead of Unicode emoji (⚙ 🔊 ⧉ ×):
- Emoji rendering depends on the user's installed font; same character draws
  differently on different machines (esp. Win10 vs Win11). Designed icons
  stay pixel-identical.
- Stroke color follows the theme palette via Python interpolation —
  emoji can't change color.

The QIcon cache is keyed by (name, color, size) so the same button asking
for the same icon twice doesn't repaint. Color and size keys keep variants
distinct (e.g. small dim chevron vs large accent chevron).
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


# ── SVG path table ─────────────────────────────────────────────────────────
# Inner-`<path>` / `<g>` payload only; the wrapper `<svg viewBox="0 0 16 16">`
# is added at paint time so we can swap stroke color per call. Every entry is
# verbatim from the Cobalt design's `tokens.jsx`.
_ICON_BODIES: dict[str, str] = {
    # Gear/cog: toothed outline + center hole. The previous "circle + 8 thin
    # spokes" read as a sun, not a settings gear — this is unambiguous.
    "settings": (
        '<circle cx="8" cy="8" r="2.1" />'
        '<path d="M8 1.4l.9 1.7 1.9-.5.3 2 1.9.7-.7 1.8 1.3 1.5-1.5 1.3'
        '.2 1.9-1.9.4-.7 1.8H8h-1.6l-.7-1.8-1.9-.4.2-1.9-1.5-1.3 1.3-1.5'
        '-.7-1.8 1.9-.7.3-2 1.9.5z" />'
    ),
    "volume": (
        '<path d="M3 6h2l3-2.5v9L5 10H3z" />'
        '<path d="M10.5 5.5a3.5 3.5 0 0 1 0 5" />'
        '<path d="M12.5 3.5a6 6 0 0 1 0 9" />'
    ),
    "volume-mute": (
        '<path d="M3 6h2l3-2.5v9L5 10H3z" />'
        '<path d="M10 6l3 3M13 6l-3 3" />'
    ),
    "copy": (
        '<rect x="5" y="5" width="8" height="8" rx="1.3" />'
        '<path d="M3 11V4a1.3 1.3 0 0 1 1.3-1.3H11" />'
    ),
    "check": '<path d="M3 8.5l3 3 7-7" />',
    "close": '<path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />',
    "pin": (
        '<path d="M8 1.8l-2 4-3 1 3.5 3.5L3 14l4.2-3.5L10.7 14'
        'l-1-3 3.5-3.5-3-1z" />'
    ),
    "chevron": '<path d="M4 6l4 4 4-4" />',
    "chevron-right": '<path d="M6 4l4 4-4 4" />',
    "refresh": (
        '<path d="M13.5 8a5.5 5.5 0 1 1-1.7-4" />'
        '<path d="M13.5 2v3.5h-3.5" />'
    ),
    "plus": '<path d="M8 3v10M3 8h10" />',
    "minus": '<path d="M3 8h10" />',
    # Font-size controls: an "A" with a small +/− at upper-right. Drawn as
    # strokes so they recolor with the theme (no Unicode glyph reliance).
    "font-larger": (
        '<path d="M2 13l3.2-8 3.2 8M3.1 10.2h4.2" />'
        '<path d="M11.5 3.5v4M9.5 5.5h4" />'
    ),
    "font-smaller": (
        '<path d="M2 13l3.2-8 3.2 8M3.1 10.2h4.2" />'
        '<path d="M9.5 5.5h4" />'
    ),
    "trash": (
        '<path d="M2.5 4h11M5.5 4V2.7A.7.7 0 0 1 6.2 2h3.6'
        'a.7.7 0 0 1 .7.7V4M4 4l.7 9a.7.7 0 0 0 .7.7h5.2'
        'a.7.7 0 0 0 .7-.7L12 4" />'
        '<path d="M6.5 7v4M9.5 7v4" />'
    ),
    "crop": (
        '<path d="M4 2v9.3a.7.7 0 0 0 .7.7H14" />'
        '<path d="M2 4h9.3a.7.7 0 0 1 .7.7V14" />'
    ),
    "fullscreen": (
        '<path d="M2 5V3a1 1 0 0 1 1-1h2" />'
        '<path d="M14 5V3a1 1 0 0 0-1-1h-2" />'
        '<path d="M2 11v2a1 1 0 0 0 1 1h2" />'
        '<path d="M14 11v2a1 1 0 0 1-1 1h-2" />'
    ),
    "subtitles": (
        '<rect x="1.8" y="3.5" width="12.4" height="9" rx="1.3" />'
        '<path d="M4 8h3M8 8h4M4 10.5h2M7 10.5h5" />'
    ),
    "keyboard": (
        '<rect x="1.5" y="4" width="13" height="8" rx="1.3" />'
        '<path d="M4 7h.01M6.5 7h.01M9 7h.01M11.5 7h.01'
        'M4 9.5h.01M6.5 9.5h3M12 9.5h.01" />'
    ),
    "globe": (
        '<circle cx="8" cy="8" r="6.2" />'
        '<path d="M2 8h12M8 1.8c2 2 2 10.4 0 12.4M8 1.8c-2 2-2 10.4 0 12.4" />'
    ),
    "info": (
        '<circle cx="8" cy="8" r="6.2" />'
        '<path d="M8 7.5v3.5M8 5.2v.3" />'
    ),
    "alert": (
        '<path d="M8 2L1.5 13.5h13z" />'
        '<path d="M8 6.5v3M8 11.5v.3" />'
    ),
    "power": (
        '<path d="M5 3.5a5.5 5.5 0 1 0 6 0" />'
        '<path d="M8 1.5v6" />'
    ),
    "search": (
        '<circle cx="7" cy="7" r="4.2" />'
        '<path d="M10 10l3.2 3.2" />'
    ),
    "edit": '<path d="M11.5 2.5l2 2L5 13l-3 1 1-3z" />',
    "eye": (
        '<path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" />'
        '<circle cx="8" cy="8" r="1.8" />'
    ),
    "cached": (
        '<circle cx="8" cy="8" r="6.2" />'
        '<path d="M5 8l2.2 2.2L11.5 6" />'
    ),
    "brain": (
        '<path d="M5.5 3.5A2 2 0 0 0 4 7v2a2 2 0 0 0 1.5 2.5v1'
        'A1.5 1.5 0 0 0 7 14V3a1.5 1.5 0 0 0-1.5-1.5'
        'A2 2 0 0 0 5.5 3.5z" />'
        '<path d="M10.5 3.5A2 2 0 0 1 12 7v2a2 2 0 0 1-1.5 2.5v1'
        'A1.5 1.5 0 0 1 9 14V3a1.5 1.5 0 0 1 1.5-1.5'
        'A2 2 0 0 1 10.5 3.5z" />'
    ),
    "link": (
        '<path d="M6.5 9.5l3-3M7 4.5l.8-.8a2.5 2.5 0 0 1 3.5 3.5l-.8.8'
        'M9 11.5l-.8.8a2.5 2.5 0 0 1-3.5-3.5l.8-.8" />'
    ),
    "external": (
        '<path d="M9 3h4v4M13 3l-6 6" />'
        '<path d="M11 9.5V12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6'
        'a1 1 0 0 1 1-1h2.5" />'
    ),
    "mail": (
        '<rect x="2" y="3.5" width="12" height="9" rx="1.3" />'
        '<path d="M2.5 4.5l5.5 4 5.5-4" />'
    ),
    "clipboard": (
        '<rect x="3.5" y="3" width="9" height="11" rx="1.2" />'
        '<path d="M6 3V2.3A.8.8 0 0 1 6.8 1.5h2.4'
        'a.8.8 0 0 1 .8.8V3" />'
    ),
    "play": '<path d="M5 3.5l7 4.5-7 4.5z" />',
    "arrow": '<path d="M2.5 8h11M9.5 4l4 4-4 4" />',
    "monitor": (
        '<rect x="1.8" y="2.8" width="12.4" height="8.4" rx="1.2" />'
        '<path d="M5.5 14h5M8 11.2V14" />'
    ),
    "download": (
        '<path d="M8 2v8M5 7l3 3 3-3" />'
        '<path d="M2.5 12.5h11" />'
    ),
    "user": (
        '<circle cx="8" cy="5.5" r="2.8" />'
        '<path d="M2.8 13.5a5.2 5.2 0 0 1 10.4 0" />'
    ),
}


def _build_svg(body: str, color: str, stroke: float = 1.5) -> bytes:
    """Wrap an inner path body with <svg viewBox="0 0 16 16"> + stroke setup.

    `play` is the only icon that uses fill (it's a filled triangle), so we
    treat it specially. Everything else is stroke-only with `fill=none`.
    """
    fill = color if body.strip().startswith('<path d="M5 3.5l7') else "none"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="{fill}" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )
    return svg.encode("utf-8")


@lru_cache(maxsize=256)
def get_icon(name: str, color: str = "#ecedef", size: int = 16) -> QIcon:
    """Return a QIcon for `name` with the requested stroke color.

    Cached: identical (name, color, size) requests reuse the QIcon. Color
    string is whatever QSvgRenderer accepts (hex `#RRGGBB`, `rgba(...)`,
    or a named color); palette tokens from `tokens.py` work directly.
    """
    body = _ICON_BODIES.get(name)
    if body is None:
        return QIcon()
    svg = _build_svg(body, color)
    renderer = QSvgRenderer(QByteArray(svg))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def get_pixmap(name: str, color: str = "#ecedef", size: int = 16) -> QPixmap:
    """Same as `get_icon` but returns the underlying QPixmap directly.

    Use this when placing an icon inside a QLabel (label-based icon in a
    custom widget) — QLabels take QPixmap, not QIcon.
    """
    body = _ICON_BODIES.get(name)
    if body is None:
        return QPixmap(QSize(size, size))
    svg = _build_svg(body, color)
    renderer = QSvgRenderer(QByteArray(svg))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


# ── Spinner: animated separately ───────────────────────────────────────────
# The static frame for the spinner is the same arc-on-circle pattern as the
# design (12 o'clock → 3 o'clock arc). For animation, widgets use
# `QPropertyAnimation` rotating the QLabel/QPixmap directly — building a
# proper spinner widget happens in atoms.py.
_SPINNER_FRAME = (
    '<circle cx="8" cy="8" r="6" stroke-opacity="0.18" />'
    '<path d="M14 8a6 6 0 0 0-6-6" />'
)


@lru_cache(maxsize=32)
def get_spinner_pixmap(color: str, size: int) -> QPixmap:
    """Single still frame of the spinner arc. Caller animates the rotation."""
    svg = _build_svg(_SPINNER_FRAME, color)
    renderer = QSvgRenderer(QByteArray(svg))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def available_icons() -> list[str]:
    """All icon names known to this module. Useful for tooling / debug."""
    return sorted(_ICON_BODIES.keys())
