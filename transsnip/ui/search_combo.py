"""Combo boxes for Settings: a scroll-safe base, and a type-to-search variant.

`SearchCombo` replaces the old editable-combo + QCompleter recipe, which had
three UX problems on long lists (≈110 languages, ≈470 OpenRouter models):
- matching was a raw case-insensitive substring of the label, so "viet" never
  found "Tiếng Việt", and ids/codes ("ja", "qwen3.7") weren't searchable;
- results came back in list order, not by relevance;
- half-typed text stayed in the box after focus left, while the real value was
  still the old item — the field showed something that wasn't selected.
"""
from __future__ import annotations

import unicodedata

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QComboBox, QCompleter, QWidget


class ComboBox(QComboBox):
    """QComboBox that (1) doesn't change value on scroll-wheel and (2) paints
    its own down-chevron.

    Scroll: default Qt combos cycle their value when you scroll the wheel over
    them — easy to change a setting by accident while scrolling the page. We
    pass the wheel event up to the parent (so the panel scrolls), consuming it
    only when the dropdown popup is open.

    Arrow: Qt's QSS `::down-arrow { image: url(...) }` renders blank for these
    (esp. editable combos), so we draw the chevron ourselves in paintEvent —
    reliable in both themes.
    """

    _ARROW_W = 26  # must match QComboBox::drop-down width in theme.py

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.view().isVisible():
            super().wheelEvent(event)  # popup open → normal scroll inside it
        else:
            event.ignore()  # bubble up so the scroll area scrolls instead

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        from transsnip.ui.theme import get_theme
        p = get_theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(p.text_1), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - self._ARROW_W / 2
        cy = self.height() / 2
        painter.drawLine(int(cx - 4), int(cy - 2), int(cx), int(cy + 2))  # ⌄
        painter.drawLine(int(cx), int(cy + 2), int(cx + 4), int(cy - 2))
        painter.end()


def fold(text: str) -> str:
    """Case- and accent-insensitive search key: "Tiếng Việt" → "tieng viet"."""
    text = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    return "".join(c for c in text if not unicodedata.combining(c))


class _RankedFilter(QSortFilterProxyModel):
    """Keeps rows whose label+id contain EVERY query word; best matches first.

    Rank: exact label/id > label/id starts with the query > a word starts with
    it > contains it; ties keep the source order (stable).
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._words: list[str] = []
        self._query = ""

    def set_query(self, text: str) -> None:
        self._query = fold(text.strip())
        self._words = self._query.split()
        self.invalidate()
        self.sort(0)

    def _haystack(self, row: int) -> tuple[str, str]:
        idx = self.sourceModel().index(row, 0)
        label = fold(str(idx.data(Qt.ItemDataRole.DisplayRole) or ""))
        key = fold(str(idx.data(Qt.ItemDataRole.UserRole) or ""))
        return label, key

    def filterAcceptsRow(self, row: int, parent: QModelIndex | QPersistentModelIndex) -> bool:
        if not self._words:
            return True
        label, key = self._haystack(row)
        hay = f"{label} {key}"
        return all(w in hay for w in self._words)

    def _score(self, row: int) -> int:
        label, key = self._haystack(row)
        q = self._query
        if q in (label, key):
            return 0
        if label.startswith(q) or key.startswith(q):
            return 1
        if any(part.startswith(q) for part in f"{label} {key}".replace("/", " ").split()):
            return 2
        return 3

    def lessThan(self, a: QModelIndex | QPersistentModelIndex,
                 b: QModelIndex | QPersistentModelIndex) -> bool:
        sa, sb = self._score(a.row()), self._score(b.row())
        return sa < sb if sa != sb else a.row() < b.row()


class SearchCombo(ComboBox):
    """Dropdown you can also type into to search (see module docstring).

    Behaviour:
    - typing filters a suggestion popup (accent/case-insensitive, all words,
      label or id, ranked); Enter takes the top suggestion;
    - Esc, or leaving the field without picking, restores the current item —
      the box never shows text that isn't the selected value;
    - focusing the field selects its text, so you just start typing;
    - no match → the field is flagged (`nomatch` property, red border in theme).
    """

    def __init__(self, parent: QWidget | None = None, *, placeholder: str = "Gõ để tìm…") -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        edit = self.lineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        edit.installEventFilter(self)

        self._filter = _RankedFilter(self)
        self._filter.setSourceModel(self.model())
        completer = QCompleter(self._filter, self)
        # We filter ourselves (accent folding, ranking) — the completer only shows.
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setMaxVisibleItems(12)
        completer.activated[QModelIndex].connect(self._on_pick)
        self.setCompleter(completer)
        self._completer = completer

        edit.textEdited.connect(self._on_edited)
        edit.returnPressed.connect(self._on_return)
        edit.editingFinished.connect(self._restore_soon)
        self.currentIndexChanged.connect(lambda _i: self._set_nomatch(False))

    # ── typing ───────────────────────────────────────────────────────────

    def _on_edited(self, text: str) -> None:
        self._filter.set_query(text)
        has = self._filter.rowCount() > 0
        self._set_nomatch(bool(text.strip()) and not has)
        if text.strip() and has:
            self._completer.complete()
        else:
            self._completer.popup().hide()

    def _on_pick(self, proxy_index: QModelIndex) -> None:
        src = self._filter.mapToSource(proxy_index)
        if src.isValid():
            self.setCurrentIndex(src.row())
        self._show_current()

    def _on_return(self) -> None:
        popup = self._completer.popup()
        sel = popup.currentIndex() if popup.isVisible() else QModelIndex()
        if not sel.isValid() and self._filter.rowCount() > 0 and self._typed_differs():
            sel = self._filter.index(0, 0)
        if sel.isValid():
            self._on_pick(sel)
        popup.hide()
        self._show_current()

    # ── keeping the box honest ───────────────────────────────────────────

    def _selected_label(self) -> str:
        # NOT currentText(): on an editable combo that returns whatever is
        # typed in the line edit, not the selected item.
        return self.itemText(self.currentIndex())

    def _typed_differs(self) -> bool:
        return self.lineEdit().text() != self._selected_label()

    def _restore_soon(self) -> None:
        # Deferred: a click on a suggestion fires editingFinished first.
        QTimer.singleShot(0, self._show_current)

    def _show_current(self) -> None:
        if self._completer.popup().isVisible():
            return
        if self._typed_differs():
            self.lineEdit().setText(self._selected_label())
        self._filter.set_query("")
        self._set_nomatch(False)

    def _set_nomatch(self, on: bool) -> None:
        if self.property("nomatch") != on:
            self.setProperty("nomatch", on)
            self.style().unpolish(self)
            self.style().polish(self)

    def focusInEvent(self, event) -> None:
        # Focus lands on the combo (the line edit is only its focus proxy), so
        # this — not an event filter on the line edit — sees it. Deferred: the
        # click that focused us places the cursor first and would undo it.
        super().focusInEvent(event)
        QTimer.singleShot(0, self.lineEdit().selectAll)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # Esc with no popup open → drop the typed text, show the selection again.
        # (With the popup open, Esc first closes the popup — Qt's default.)
        if (obj is self.lineEdit() and event.type() == QEvent.Type.KeyPress
                and isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape
                and not self._completer.popup().isVisible()):
            self._show_current()
            return True
        return super().eventFilter(obj, event)

