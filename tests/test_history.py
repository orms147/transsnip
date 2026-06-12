"""HistoryStore — add (newest-first), dedup, cap, persistence round-trip."""
from transsnip.config.history import HistoryEntry, HistoryStore


def _entry(src, dst="x"):
    return HistoryEntry(source_text=src, translated_text=dst, provider="t")


def test_add_newest_first(tmp_path):
    s = HistoryStore(tmp_path / "h.json")
    s.add(_entry("one"))
    s.add(_entry("two"))
    assert [e.source_text for e in s.recent()] == ["two", "one"]


def test_consecutive_duplicate_collapsed(tmp_path):
    s = HistoryStore(tmp_path / "h.json")
    s.add(_entry("same", "same-tr"))
    s.add(_entry("same", "same-tr"))
    assert len(s.recent()) == 1


def test_cap(tmp_path):
    s = HistoryStore(tmp_path / "h.json", max_entries=3)
    for i in range(5):
        s.add(_entry(f"n{i}"))
    got = [e.source_text for e in s.recent()]
    assert got == ["n4", "n3", "n2"]  # oldest fell off


def test_persistence_round_trip(tmp_path):
    p = tmp_path / "h.json"
    s1 = HistoryStore(p)
    s1.add(_entry("persisted"))
    s2 = HistoryStore(p)  # fresh instance reads the file
    assert [e.source_text for e in s2.recent()] == ["persisted"]


def test_clear(tmp_path):
    s = HistoryStore(tmp_path / "h.json")
    s.add(_entry("a"))
    s.clear()
    assert s.recent() == []
