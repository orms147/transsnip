"""FloatingPopup — Cobalt redesign.

The popup is a state machine with four states matching the design's
`<FloatingPopup state>` prop in `surface-popup.jsx`:
    - "loading"  — skeleton lines while OCR/translate is running
    - "learning" — English source with IPA furigana + 🔊 button
    - "ja-vi"    — generic translated state (any source/target lang)
    - "error"    — failure with inline retry / switch-provider actions

The chrome stays identical across states (brand · drag · status · actions);
only the body content changes. PhoneticSource handles the two-row IPA layout
with per-word click → Edge TTS. Drag is restricted to the dedicated drag
area in the header; selecting text in the body never starts a window move.

`PinnedPopup` is a separate 280×80 widget — same module so they share the
TTS player and theme refresh wiring.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpacerItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from transsnip.linguistic.ipa import get_ipa
from transsnip.translate.base import TranslationResult
from transsnip.tts.edge_tts_player import EdgeTTSPlayer
from transsnip.ui import icons
from transsnip.ui.atoms import (
    IconButton,
    KbdSeq,
    LangChip,
    PillBadge,
    Spinner,
)
from transsnip.ui.theme import get_theme

log = logging.getLogger(__name__)

# Default size from design (`POPUP_W = 460`). Height grows with content,
# clamped between _MIN_HEIGHT and the available screen height.
_DEFAULT_WIDTH = 460
_DEFAULT_HEIGHT = 360
_MIN_WIDTH = 320
_MIN_HEIGHT = 140
_MARGIN_FROM_EDGE = 16
_GAP_FROM_REGION = 12
_RESIZE_MARGIN = 6

# Font scaling — base point sizes at _DEFAULT_WIDTH, multiplied by width/default
# (clamped) so a user dragging the popup wider gets larger reading text.
_FONT_SOURCE_PT = 11
_FONT_TRANSLATION_PT = 12
_FONT_IPA_PT = 9
_FONT_MIN_SCALE = 1.0
_FONT_MAX_SCALE = 2.0

_SPEAK_LINK_PREFIX = "speak:"
_IPA_TOKEN_RE = re.compile(r"\S+|\s+")


# ── DragBar ────────────────────────────────────────────────────────────────
class _DragBar(QWidget):
    """The middle of the header — empty drag handle for moving the popup.

    Text body stays drag-free so selection works naturally; only this strip
    moves the window. Mirrors the design's `popup-drag` element.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMinimumHeight(28)
        self._press_global: Optional[QPoint] = None
        self._press_frame_topleft: Optional[QPoint] = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_frame_topleft = self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._press_global is not None
            and self._press_frame_topleft is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.globalPosition().toPoint() - self._press_global
            self.window().move(self._press_frame_topleft + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_global = None
        self._press_frame_topleft = None
        super().mouseReleaseEvent(event)


# ── AppGlyph (header brand mark) ──────────────────────────────────────────
class _AppGlyph(QWidget):
    """The small TransSnip glyph painted into the popup header.

    Two paths: outer crop brackets in accent, inner chevron in text_1.
    Paints with current theme palette colors via QPainter so theme switches
    recolor without re-importing assets.
    """

    def __init__(self, size: int = 14, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Scale 16×16 design viewBox to the requested widget size.
        scale = self._size / 16
        painter.scale(scale, scale)

        # Outer crop brackets (accent).
        pen = QPen(QColor(p.accent), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for path_d in [
            ((2.5, 4.5), (2.5, 3), (3.2, 2.3), (4.5, 2.3)),  # top-left bracket
            ((11.5, 2.3), (13, 2.3), (13.7, 3), (13.7, 4.5)),
            ((13.7, 11.5), (13.7, 13), (13, 13.7), (11.5, 13.7)),
            ((4.5, 13.7), (3, 13.7), (2.3, 13), (2.3, 11.5)),
        ]:
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(*path_d[0])
            for pt in path_d[1:]:
                path.lineTo(*pt)
            painter.drawPath(path)

        # Inner chevron (text_1).
        pen2 = QPen(QColor(p.text_1), 1.6)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen2)
        from PySide6.QtGui import QPainterPath
        bar = QPainterPath()
        bar.moveTo(6, 8)
        bar.lineTo(10, 8)
        painter.drawPath(bar)
        chev = QPainterPath()
        chev.moveTo(8.5, 6.5)
        chev.lineTo(10, 8)
        chev.lineTo(8.5, 9.5)
        painter.drawPath(chev)
        painter.end()


# ── PopupHeader (one chrome strip for all states) ─────────────────────────
class _PopupHeader(QWidget):
    """Header bar: brand + drag + status + actions.

    `status` is a state string ("ocr", "translating", "done", "error") —
    the header swaps its center widget accordingly. Actions emit signals
    that the parent popup connects to its own slots.
    """

    speak_requested = Signal()
    copy_requested = Signal()
    pin_toggled = Signal(bool)
    settings_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._status: str = "ocr"
        self._show_voice = False
        self._pinned = False
        self._provider = ""
        self._cached = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 8, 10)
        layout.setSpacing(8)

        # Brand
        brand = QWidget()
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(6)
        self._glyph = _AppGlyph(14)
        brand_row.addWidget(self._glyph)
        self._brand_label = QLabel("TransSnip")
        brand_row.addWidget(self._brand_label)
        layout.addWidget(brand)

        # Drag (stretch)
        self._drag = _DragBar(self)
        layout.addWidget(self._drag, stretch=1)

        # Status area — replaced when status changes.
        self._status_wrap = QWidget()
        self._status_layout = QHBoxLayout(self._status_wrap)
        self._status_layout.setContentsMargins(0, 0, 0, 0)
        self._status_layout.setSpacing(6)
        layout.addWidget(self._status_wrap)

        # Actions
        actions = QWidget()
        actions_row = QHBoxLayout(actions)
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(2)
        self._voice_btn = IconButton("volume", kind="accent", tooltip="Phát âm nguồn")
        self._voice_btn.clicked.connect(self.speak_requested.emit)
        self._voice_btn.hide()
        actions_row.addWidget(self._voice_btn)

        self._copy_btn = IconButton("copy", tooltip="Copy translation")
        self._copy_btn.clicked.connect(self.copy_requested.emit)
        actions_row.addWidget(self._copy_btn)

        self._pin_btn = IconButton("pin", tooltip="Pin (always on top)")
        self._pin_btn.clicked.connect(self._on_pin_clicked)
        actions_row.addWidget(self._pin_btn)

        self._settings_btn = IconButton("settings", tooltip="Settings")
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        actions_row.addWidget(self._settings_btn)

        # Subtle divider before close.
        self._divider = QFrame()
        self._divider.setFixedSize(1, 16)
        self._divider.setStyleSheet("background: rgba(255,255,255,0.10);")
        actions_row.addWidget(self._divider)

        self._close_btn = IconButton("close", kind="close", tooltip="Close (Esc)")
        self._close_btn.clicked.connect(self.close_requested.emit)
        actions_row.addWidget(self._close_btn)
        layout.addWidget(actions)

        self._apply_style()
        self.set_status("ocr")
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    # ── Public API ────────────────────────────────────────────────────────
    def set_status(self, status: str, *, provider: str = "", cached: bool = False) -> None:
        self._status = status
        self._provider = provider
        self._cached = cached
        self._rebuild_status()

    def set_voice_available(self, available: bool) -> None:
        self._show_voice = available
        self._voice_btn.setVisible(available)

    def is_pinned(self) -> bool:
        return self._pinned

    # ── Internals ─────────────────────────────────────────────────────────
    def _on_pin_clicked(self) -> None:
        self._pinned = not self._pinned
        self.pin_toggled.emit(self._pinned)

    def _rebuild_status(self) -> None:
        # Clear existing widgets in status_layout.
        while self._status_layout.count():
            item = self._status_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        p = get_theme().palette
        if self._status in ("ocr", "translating"):
            spin = Spinner(11)
            spin.start()
            self._status_layout.addWidget(spin)
            label = QLabel("Đang OCR…" if self._status == "ocr" else "Đang dịch…")
            label.setStyleSheet(f"color: {p.text_2}; font-size: 11px;")
            self._status_layout.addWidget(label)
        elif self._status == "done":
            if self._provider:
                prov = QLabel(self._provider)
                prov.setStyleSheet(
                    f"color: {p.text_2}; font-family: {p.font_mono}; "
                    f"font-size: 10.5px; padding: 1px 6px; "
                    f"background: {p.bg_2}; border-radius: 4px;"
                )
                self._status_layout.addWidget(prov)
            if self._cached:
                badge = PillBadge("cached", icon_name="cached", tone="muted")
                self._status_layout.addWidget(badge)
        elif self._status == "error":
            badge = PillBadge("error", icon_name="alert", tone="warn")
            self._status_layout.addWidget(badge)

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._brand_label.setStyleSheet(
            f"color: {p.text_1}; font-size: 12px; font-weight: 600; "
            f"letter-spacing: {p.letter_tight};"
        )
        self._divider.setStyleSheet(f"background: {p.border_1};")
        self._rebuild_status()


# ── PhoneticSource (2-row English source + IPA, click-to-speak) ───────────
class _PhoneticSource(QWidget):
    """English source rendered as two stacked rows: words on top, IPA below.

    Each word + its IPA share a `speak:<word>` anchor → click either to
    fire `speak_requested(word)` which the parent popup wires to TTS.

    Implemented as a single rich-text QLabel for now (HTML two-row layout
    with `<div>` blocks). A future iteration could move to per-word
    QPushButtons for keyboard navigation, but the QLabel approach mirrors
    the React component's behavior closely and stays lightweight.
    """

    speak_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._label.setOpenExternalLinks(False)
        self._label.linkActivated.connect(self._on_link)
        layout.addWidget(self._label)
        self._text = ""
        self._scale = 1.0
        get_theme().mode_changed.connect(lambda _p: self._render())

    def set_text(self, text: str, *, scale: float = 1.0) -> None:
        self._text = text
        self._scale = scale
        self._render()

    def _on_link(self, href: str) -> None:
        if href.startswith(_SPEAK_LINK_PREFIX):
            word = href[len(_SPEAK_LINK_PREFIX):].strip()
            if word:
                self.speak_requested.emit(word)

    def _render(self) -> None:
        p = get_theme().palette
        word_color = p.text_1
        ipa_color = p.accent
        dash_color = p.text_mute
        source_pt = max(8, round(_FONT_SOURCE_PT * self._scale))
        ipa_pt = max(7, round(_FONT_IPA_PT * self._scale))

        out: list[str] = []
        for raw_line in (self._text or "").splitlines() or [self._text or ""]:
            tokens = _IPA_TOKEN_RE.findall(raw_line)
            source_html: list[str] = []
            ipa_html: list[str] = []
            any_ipa = False
            for token in tokens:
                if token.isspace():
                    source_html.append(token.replace(" ", "&nbsp;"))
                    ipa_html.append("&nbsp;")
                    continue
                ipa = get_ipa(token)
                esc = html.escape(token)
                if ipa:
                    any_ipa = True
                    href = f"{_SPEAK_LINK_PREFIX}{esc}"
                    source_html.append(
                        f"<a href='{href}' "
                        f"style='color: {word_color}; text-decoration: none;'>"
                        f"{esc}</a>"
                    )
                    ipa_html.append(
                        f"<a href='{href}' "
                        f"style='color: {ipa_color}; text-decoration: none;'>"
                        f"/{html.escape(ipa)}/</a>"
                    )
                else:
                    source_html.append(
                        f"<span style='color: {word_color};'>{esc}</span>"
                    )
                    ipa_html.append(
                        f"<span style='color: {dash_color};'>—</span>"
                    )
            block = f"<div style='font-size: {source_pt}pt; line-height: 1.5;'>{''.join(source_html)}</div>"
            if any_ipa:
                block += (
                    f"<div style='font-size: {ipa_pt}pt; line-height: 1.3; "
                    f"margin-top: 1px; margin-bottom: 6px;'>{''.join(ipa_html)}</div>"
                )
            out.append(block)
        self._label.setText("".join(out))


# ── Skeleton placeholder (loading state) ──────────────────────────────────
class _Skeleton(QWidget):
    """Animated horizontal bars for loading state.

    Matches design `.popup-skeleton-line` (4 lines, 2 default + 2 accent).
    Uses paintEvent with a shimmer effect — repaints every 50ms while visible.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 18, 8, 18)
        layout.setSpacing(10)
        # Width ratios from the design: 85% / 60% / 75% / 50%.
        self._bars = [
            (0.85, False),
            (0.60, False),
            (0.75, True),
            (0.50, True),
        ]
        for _w, _a in self._bars:
            placeholder = QFrame()
            placeholder.setFixedHeight(12)
            layout.addWidget(placeholder)
        self._frames = [layout.itemAt(i).widget() for i in range(layout.count())]
        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def _apply_style(self) -> None:
        p = get_theme().palette
        for frame, (width_ratio, is_accent) in zip(self._frames, self._bars):
            color = p.accent_soft if is_accent else p.bg_2
            frame.setStyleSheet(
                f"background: {color}; border-radius: 6px;"
            )
            frame.setMaximumWidth(int(440 * width_ratio))


# ── ErrorPanel (error state body) ─────────────────────────────────────────
class _ErrorPanel(QWidget):
    """Inline error display: alert icon + title + msg + action buttons.

    `retry_requested` / `switch_provider_requested` fire when the user
    clicks the corresponding ghost button; popup wires them up.
    """

    retry_requested = Signal()
    switch_provider_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Icon column
        self._icon = QLabel()
        self._icon.setFixedSize(36, 36)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignTop)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        self._title = QLabel("Không thể dịch")
        self._msg = QLabel()
        self._msg.setWordWrap(True)
        text_col.addWidget(self._title)
        text_col.addWidget(self._msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._switch_btn = QPushButton("Đổi provider")
        self._switch_btn.setProperty("soft", True)
        self._switch_btn.clicked.connect(self.switch_provider_requested.emit)
        self._retry_btn = QPushButton("Thử lại")
        self._retry_btn.setProperty("soft", True)
        self._retry_btn.clicked.connect(self.retry_requested.emit)
        btn_row.addWidget(self._switch_btn)
        btn_row.addWidget(self._retry_btn)
        btn_row.addStretch(1)
        text_col.addLayout(btn_row)
        layout.addLayout(text_col, stretch=1)

        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self._apply_style())

    def set_error(self, message: str) -> None:
        self._msg.setText(message)

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._icon.setPixmap(icons.get_pixmap("alert", color=p.danger, size=22))
        self._icon.setStyleSheet(
            f"background: {p.accent_soft}; border-radius: 18px;"
        )
        self._title.setStyleSheet(
            f"color: {p.text_1}; font-size: 13px; font-weight: 600;"
        )
        self._msg.setStyleSheet(
            f"color: {p.text_2}; font-size: 12px; line-height: 1.5;"
        )


# ── FloatingPopup (main widget) ───────────────────────────────────────────
class FloatingPopup(QWidget):
    """Region-translate result popup. State machine: loading / source-known /
    translation-done / error. Same widget instance reused across hotkey
    invocations — `show_for_region` resets state.

    See module docstring for the four states and what each renders.
    """

    closed = Signal()
    settings_requested = Signal()
    retry_requested = Signal()
    switch_provider_requested = Signal()
    pin_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("FloatingPopupRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        # Session state
        self._last_region: Optional[QRect] = None
        self._last_translation: str = ""
        self._last_source_text: str = ""
        self._last_source_lang: Optional[str] = None
        self._show_phonetic_active: bool = False
        self._filter_installed = False
        self._user_resized = False
        self._current_state = "loading"
        self._current_font_scale = 1.0

        # Resize state
        self._resize_edges = 0
        self._resize_start_geom: Optional[QRect] = None
        self._resize_start_global: Optional[QPoint] = None

        self._tts_player = EdgeTTSPlayer(self)

        self._build_ui()
        get_theme().mode_changed.connect(lambda _p: self.update())  # re-paint frame

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)  # 1px so paintEvent border doesn't get clipped
        root.setSpacing(0)

        # Header
        self._header = _PopupHeader(self)
        self._header.speak_requested.connect(self._on_speak_sentence)
        self._header.copy_requested.connect(self._on_copy)
        self._header.pin_toggled.connect(self.pin_changed.emit)
        self._header.settings_requested.connect(self.settings_requested.emit)
        self._header.close_requested.connect(self.hide_popup)
        root.addWidget(self._header)

        # Body in scroll area (so long translations scroll)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("popupScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._body = QWidget()
        self._body.setObjectName("popupBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 12, 14, 12)
        self._body_layout.setSpacing(12)

        # Body sub-widgets (lazy-built per state).
        self._source_chip = LangChip("", "")
        self._source_chip.hide()
        self._learning_tag = QLabel("Learning mode")
        self._learning_tag.hide()
        self._source_label = QLabel()  # plain (JA-VI) source
        self._source_label.setWordWrap(True)
        self._source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._source_label.hide()
        self._phonetic = _PhoneticSource()
        self._phonetic.speak_requested.connect(self._on_speak_word)
        self._phonetic.hide()
        self._divider = QFrame()
        self._divider.setFixedHeight(1)
        self._divider.hide()

        self._target_chip = LangChip("VI", "Tiếng Việt")
        self._target_chip.hide()
        self._translation_label = QLabel()
        self._translation_label.setWordWrap(True)
        self._translation_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._footer_hint = QWidget()
        self._build_footer_hint()
        self._footer_hint.hide()

        self._skeleton = _Skeleton()
        self._skeleton.hide()
        self._error_panel = _ErrorPanel()
        self._error_panel.retry_requested.connect(self.retry_requested.emit)
        self._error_panel.switch_provider_requested.connect(self.switch_provider_requested.emit)
        self._error_panel.hide()

        # Initial layout: source-section + divider + translation-section
        src_section = QWidget()
        src_layout = QVBoxLayout(src_section)
        src_layout.setContentsMargins(0, 0, 0, 0)
        src_layout.setSpacing(6)
        src_head = QHBoxLayout()
        src_head.setSpacing(6)
        src_head.addWidget(self._source_chip)
        src_head.addWidget(self._learning_tag)
        src_head.addStretch(1)
        src_layout.addLayout(src_head)
        src_layout.addWidget(self._source_label)
        src_layout.addWidget(self._phonetic)

        tx_section = QWidget()
        tx_layout = QVBoxLayout(tx_section)
        tx_layout.setContentsMargins(0, 0, 0, 0)
        tx_layout.setSpacing(6)
        tx_layout.addWidget(self._target_chip)
        tx_layout.addWidget(self._translation_label)

        self._body_layout.addWidget(src_section)
        self._body_layout.addWidget(self._divider)
        self._body_layout.addWidget(tx_section)
        self._body_layout.addWidget(self._skeleton)
        self._body_layout.addWidget(self._error_panel)
        self._body_layout.addStretch(1)
        self._body_layout.addWidget(self._footer_hint)

        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, stretch=1)

        self.setMinimumSize(_MIN_WIDTH, _MIN_HEIGHT)
        self._apply_style()
        self._apply_fonts(force=True)

    def _build_footer_hint(self) -> None:
        layout = QHBoxLayout(self._footer_hint)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        self._hint_esc = KbdSeq(["Esc"])
        layout.addWidget(self._hint_esc)
        lbl_esc = QLabel("đóng ·")
        lbl_esc.setProperty("hint", True)
        layout.addWidget(lbl_esc)
        self._hint_ctrl_c = KbdSeq(["Ctrl", "C"])
        layout.addWidget(self._hint_ctrl_c)
        lbl_ctrl_c = QLabel("copy · click vào từ để nghe phát âm")
        lbl_ctrl_c.setProperty("hint", True)
        layout.addWidget(lbl_ctrl_c, stretch=1)
        get_theme().mode_changed.connect(lambda _p: self._apply_footer_style())
        self._footer_hint_labels = [lbl_esc, lbl_ctrl_c]
        self._apply_footer_style()

    def _apply_footer_style(self) -> None:
        p = get_theme().palette
        for lbl in self._footer_hint_labels:
            lbl.setStyleSheet(f"color: {p.text_3}; font-size: 10.5px;")

    # ── Public state API ──────────────────────────────────────────────────

    def show_for_region(self, region: QRect) -> None:
        """Open the popup for a fresh OCR/translate cycle. Resets state."""
        self._last_region = region
        self._last_translation = ""
        self._last_source_text = ""
        self._last_source_lang = None
        self._show_phonetic_active = False
        self._user_resized = False
        self._tts_player.stop()
        self._set_state("loading")
        self._header.set_status("ocr")
        self._header.set_voice_available(False)
        self._position_near(region)
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self._install_event_filter()

    def update_status(self, status: str) -> None:
        """Map old status strings to new state codes."""
        if "OCR" in status:
            self._header.set_status("ocr")
        elif "dịch" in status.lower() or "vision" in status.lower():
            self._header.set_status("translating")

    def update_source(
        self,
        source_text: str,
        *,
        source_lang: Optional[str] = None,
        show_phonetic: bool = False,
    ) -> None:
        """OCR done — display source text with optional IPA furigana."""
        self._last_source_text = source_text
        self._last_source_lang = source_lang
        self._show_phonetic_active = show_phonetic and source_lang == "en"
        self._header.set_status("translating")
        truncated = _truncate(source_text)
        self._render_source_block(truncated, source_lang)
        self._set_state("source-known")

    def update_translation(self, result: TranslationResult) -> None:
        """Translation done — populate the target section + footer."""
        if result.source_text and result.source_text != self._last_source_text:
            # Vision provider may produce a different source than OCR; honor it.
            self._last_source_text = result.source_text
            self._render_source_block(
                _truncate(result.source_text), result.source_lang or self._last_source_lang
            )

        self._last_translation = result.translated_text
        self._translation_label.setText(result.translated_text)
        target_code = (result.target_lang or "vi").upper()
        self._target_chip.show()
        self._header.set_status(
            "done",
            provider=result.provider,
            cached=result.cached,
        )
        self._set_state("translation-done")
        self._fit_height_to_content()

    def show_error(self, message: str) -> None:
        self._header.set_status("error")
        self._error_panel.set_error(message)
        self._set_state("error")

    def hide_popup(self) -> None:
        self._remove_event_filter()
        self._tts_player.stop()
        self.hide()
        self.closed.emit()

    # ── State machine helpers ─────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        self._current_state = state
        # Show/hide elements based on state.
        is_loading = state == "loading"
        is_error = state == "error"
        is_source_known = state == "source-known"
        is_done = state == "translation-done"

        self._skeleton.setVisible(is_loading)
        self._error_panel.setVisible(is_error)

        # Source section visible whenever we have content.
        source_visible = (is_source_known or is_done) and bool(self._last_source_text)
        self._source_chip.setVisible(source_visible)
        if source_visible and self._show_phonetic_active:
            self._learning_tag.setVisible(True)
            self._phonetic.setVisible(True)
            self._source_label.setVisible(False)
            self._header.set_voice_available(True)
        elif source_visible:
            self._learning_tag.setVisible(False)
            self._phonetic.setVisible(False)
            self._source_label.setVisible(True)
            self._header.set_voice_available(False)
        else:
            self._learning_tag.setVisible(False)
            self._phonetic.setVisible(False)
            self._source_label.setVisible(False)

        # Divider + target section only on done state.
        self._divider.setVisible(is_done and source_visible)
        self._target_chip.setVisible(is_done)
        self._translation_label.setVisible(is_done)

        # Footer hint only when done and English source.
        self._footer_hint.setVisible(is_done and self._show_phonetic_active)

    def _render_source_block(self, text: str, source_lang: Optional[str]) -> None:
        # Update chip in place (LangChip.set_lang) — avoids re-parenting which
        # fights with the layout we already placed the chip into.
        code = (source_lang or "??").upper()
        name = _lang_display_name(source_lang)
        self._source_chip.set_lang(code, name)
        if self._show_phonetic_active:
            self._phonetic.set_text(text, scale=self._current_font_scale)
        else:
            self._source_label.setText(text)

    # ── TTS handlers ──────────────────────────────────────────────────────

    def _on_speak_sentence(self) -> None:
        text = (self._last_source_text or "").strip()
        if text:
            self._tts_player.speak(text, voice="en-US-AriaNeural")

    def _on_speak_word(self, word: str) -> None:
        if word.strip():
            self._tts_player.speak(word.strip(), voice="en-US-AriaNeural")

    def _on_copy(self) -> None:
        if not self._last_translation:
            return
        QGuiApplication.clipboard().setText(self._last_translation)

    # ── Positioning + sizing ──────────────────────────────────────────────

    def _position_near(self, region: QRect) -> None:
        """Place popup near region, anti-clip against screen bounds.

        Region comes from RegionSelector in logical coords — no DPI math here.
        See doc 90 in mentor docs for the bug that taught us never to /dpr.
        """
        screen = QGuiApplication.screenAt(region.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        cur_w = self.width()
        cur_h = self.height()
        w = cur_w if cur_w >= _MIN_WIDTH else _DEFAULT_WIDTH
        h = cur_h if cur_h >= _MIN_HEIGHT else _DEFAULT_HEIGHT
        w = min(w, available.width() - 2 * _MARGIN_FROM_EDGE)
        h = min(h, available.height() - 2 * _MARGIN_FROM_EDGE)

        x = region.left()
        y = region.bottom() + _GAP_FROM_REGION
        if y + h > available.bottom() - _MARGIN_FROM_EDGE:
            flipped_y = region.top() - h - _GAP_FROM_REGION
            if flipped_y >= available.top() + _MARGIN_FROM_EDGE:
                y = flipped_y
            else:
                y = max(
                    available.top() + _MARGIN_FROM_EDGE,
                    available.bottom() - h - _MARGIN_FROM_EDGE,
                )
        if x + w > available.right() - _MARGIN_FROM_EDGE:
            x = available.right() - w - _MARGIN_FROM_EDGE
        if x < available.left() + _MARGIN_FROM_EDGE:
            x = available.left() + _MARGIN_FROM_EDGE

        self.setGeometry(x, y, w, h)

    def _fit_height_to_content(self) -> None:
        if self._user_resized:
            return
        self._body.adjustSize()
        chrome = self.height() - self._scroll.viewport().height() + 12
        desired = self._body.sizeHint().height() + chrome
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) \
            or QGuiApplication.primaryScreen()
        max_h = (screen.availableGeometry().height() - 2 * _MARGIN_FROM_EDGE) if screen else desired
        new_h = max(_MIN_HEIGHT, min(desired, max_h))
        if abs(new_h - self.height()) <= 2:
            return
        self.resize(self.width(), new_h)

    def _apply_fonts(self, *, force: bool = False) -> None:
        ratio = self.width() / _DEFAULT_WIDTH
        scale = max(_FONT_MIN_SCALE, min(ratio, _FONT_MAX_SCALE))
        if not force and abs(scale - self._current_font_scale) < 0.05:
            return
        self._current_font_scale = scale
        src_pt = max(8, round(_FONT_SOURCE_PT * scale))
        tx_pt = max(9, round(_FONT_TRANSLATION_PT * scale))
        sf = QFont(self._source_label.font())
        sf.setPointSize(src_pt)
        self._source_label.setFont(sf)
        tf = QFont(self._translation_label.font())
        tf.setPointSize(tx_pt)
        tf.setBold(True)
        self._translation_label.setFont(tf)
        if self._show_phonetic_active and self._last_source_text:
            self._phonetic.set_text(_truncate(self._last_source_text), scale=scale)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_fonts()

    # ── Apply style (text colors, divider, learning tag) ──────────────────

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._divider.setStyleSheet(f"background: {p.border_1};")
        self._source_label.setStyleSheet(f"color: {p.text_2}; line-height: 1.55;")
        self._translation_label.setStyleSheet(f"color: {p.text_1}; line-height: 1.6; font-weight: 600;")
        self._learning_tag.setStyleSheet(
            f"color: {p.accent}; background: {p.accent_soft}; "
            f"padding: 1px 8px; border-radius: 999px; "
            f"font-size: 10px; font-weight: 600; letter-spacing: {p.letter_caps};"
        )

    # ── Paint, drag-from-edge resize, event filter, key handlers ──────────

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QBrush(QColor(p.bg_1)))
        painter.setPen(QPen(QColor(p.border_2), 1))
        painter.drawRoundedRect(rect, p.r_popup, p.r_popup)

    def _install_event_filter(self) -> None:
        if self._filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._filter_installed = True

    def _remove_event_filter(self) -> None:
        if not self._filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._filter_installed = False

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            # Walk ancestor chain — if watched is the popup or any descendant,
            # let the click through (text selection, button click, etc.).
            w = watched if isinstance(watched, QWidget) else None
            while w is not None:
                if w is self:
                    return super().eventFilter(watched, event)
                w = w.parentWidget()
            try:
                global_pos = event.globalPosition().toPoint()
            except AttributeError:
                return super().eventFilter(watched, event)
            if not self.geometry().contains(global_pos):
                self.hide_popup()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_popup()
            return
        if event.matches(Qt.MatchFlag.MatchExactly) if False else (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_C
        ):
            self._on_copy()
            return
        if event.key() == Qt.Key.Key_Space and self._show_phonetic_active:
            self._on_speak_sentence()
            return
        super().keyPressEvent(event)

    # ── Edge-drag resize ──────────────────────────────────────────────────

    def _edges_at(self, pos: QPoint) -> int:
        m = _RESIZE_MARGIN
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        edges = 0
        if x <= m:
            edges |= 1
        elif x >= w - m:
            edges |= 2
        if y <= m:
            edges |= 4
        elif y >= h - m:
            edges |= 8
        return edges

    @staticmethod
    def _cursor_for_edges(edges: int) -> Qt.CursorShape:
        if edges in (1 | 4, 2 | 8):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (2 | 4, 1 | 8):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (1 | 2):
            return Qt.CursorShape.SizeHorCursor
        if edges & (4 | 8):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self._resize_edges = edges
                self._resize_start_geom = self.geometry()
                self._resize_start_global = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._resize_edges and self._resize_start_geom and self._resize_start_global:
            delta = event.globalPosition().toPoint() - self._resize_start_global
            g = QRect(self._resize_start_geom)
            screen = QGuiApplication.screenAt(self.frameGeometry().center()) \
                or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None

            if self._resize_edges & 1:
                new_left = g.left() + delta.x()
                if g.right() - new_left + 1 < _MIN_WIDTH:
                    new_left = g.right() - _MIN_WIDTH + 1
                if avail and new_left < avail.left():
                    new_left = avail.left()
                g.setLeft(new_left)
            if self._resize_edges & 2:
                new_right = g.right() + delta.x()
                if new_right - g.left() + 1 < _MIN_WIDTH:
                    new_right = g.left() + _MIN_WIDTH - 1
                if avail and new_right > avail.right():
                    new_right = avail.right()
                g.setRight(new_right)
            if self._resize_edges & 4:
                new_top = g.top() + delta.y()
                if g.bottom() - new_top + 1 < _MIN_HEIGHT:
                    new_top = g.bottom() - _MIN_HEIGHT + 1
                if avail and new_top < avail.top():
                    new_top = avail.top()
                g.setTop(new_top)
            if self._resize_edges & 8:
                new_bottom = g.bottom() + delta.y()
                if new_bottom - g.top() + 1 < _MIN_HEIGHT:
                    new_bottom = g.top() + _MIN_HEIGHT - 1
                if avail and new_bottom > avail.bottom():
                    new_bottom = avail.bottom()
                g.setBottom(new_bottom)
            self.setGeometry(g)
            self.repaint()
            super().mouseMoveEvent(event)
            return

        edges = self._edges_at(event.position().toPoint())
        if edges:
            self.setCursor(self._cursor_for_edges(edges))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._resize_start_geom is not None:
            self._user_resized = True
        self._resize_edges = 0
        self._resize_start_geom = None
        self._resize_start_global = None
        super().mouseReleaseEvent(event)


# ── PinnedPopup (compact mode) ────────────────────────────────────────────
class PinnedPopup(QWidget):
    """280×80 minimized popup that floats top-right corner of the active screen.

    Shows the last translation truncated to one line + tiny action buttons.
    Click anywhere on the body fires `expand_requested` so AppController can
    swap back to the full FloatingPopup.
    """

    expand_requested = Signal()
    unpin_requested = Signal()
    closed = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(280, 80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)

        self._glyph = _AppGlyph(14)
        layout.addWidget(self._glyph)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._title_row = QLabel()
        self._text_label = QLabel()
        self._text_label.setWordWrap(False)
        text_col.addWidget(self._title_row)
        text_col.addWidget(self._text_label)
        layout.addLayout(text_col, stretch=1)

        action_col = QVBoxLayout()
        action_col.setSpacing(2)
        self._unpin_btn = IconButton("pin", size=22, icon_size=11, tooltip="Unpin")
        self._unpin_btn.clicked.connect(self.unpin_requested.emit)
        self._close_btn = IconButton("close", kind="close", size=22, icon_size=11, tooltip="Close")
        self._close_btn.clicked.connect(self._on_close)
        action_col.addWidget(self._unpin_btn)
        action_col.addWidget(self._close_btn)
        layout.addLayout(action_col)

        self._last_text = ""
        self._lang_pair = ("", "")
        self._apply_style()
        get_theme().mode_changed.connect(lambda _p: self.update())

    def set_translation(self, text: str, source_lang: str = "JA", target_lang: str = "VI") -> None:
        self._last_text = text
        self._lang_pair = (source_lang.upper(), target_lang.upper())
        self._text_label.setText(_truncate(text, 60))
        s, t = self._lang_pair
        self._title_row.setText(f"<span style='font-family:JetBrains Mono;font-size:10px;color:{get_theme().palette.text_2};'>{s} → {t}</span>")

    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Click on body (not buttons) expands. Buttons consume the event first.
        if event.button() == Qt.MouseButton.LeftButton:
            self.expand_requested.emit()
        super().mousePressEvent(event)

    def _apply_style(self) -> None:
        p = get_theme().palette
        self._text_label.setStyleSheet(f"color: {p.text_1}; font-size: 11px;")

    def paintEvent(self, event: QPaintEvent) -> None:
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QBrush(QColor(p.bg_1)))
        painter.setPen(QPen(QColor(p.border_2), 1))
        painter.drawRoundedRect(rect, p.r_card, p.r_card)


# ── Helpers ───────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int = 800) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _lang_display_name(code: Optional[str]) -> str:
    """Map a BCP-47 primary subtag to a human-readable label.

    Tiny table — covers the languages TransSnip actually shows headers for.
    Anything not listed falls back to the uppercase code.
    """
    if not code:
        return ""
    mapping = {
        "en": "English",
        "ja": "日本語",
        "ko": "한국어",
        "zh": "中文",
        "zh-Hans": "中文 简体",
        "zh-Hant": "中文 繁體",
        "vi": "Tiếng Việt",
        "fr": "Français",
        "de": "Deutsch",
        "es": "Español",
        "ru": "Русский",
        "ar": "العربية",
        "th": "ภาษาไทย",
    }
    return mapping.get(code, code.upper())
