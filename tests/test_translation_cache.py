from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from transsnip.translate import cache as cache_mod
from transsnip.translate.base import TranslationContext, TranslationResult, WordInfo
from transsnip.translate.cache import TranslationCache

CTX = TranslationContext(target_lang="vi")


@pytest.fixture(autouse=True)
def _appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def _db(tmp_path: Path) -> Path:
    return tmp_path / "transsnip" / "translate-cache.sqlite3"


def _result(text: str, words: list[WordInfo] | None = None) -> TranslationResult:
    return TranslationResult(
        source_text=text,
        translated_text=f"vi:{text}",
        source_lang="en",
        target_lang="vi",
        provider="p",
        words=words,
    )


def test_roundtrip_words_and_cached_flag() -> None:
    c = TranslationCache()
    words = [WordInfo(token="hi", ipa="haɪ", meaning="chào", pos="intj")]
    c.put("hi", CTX, "p:m", _result("hi", words))
    c.put("bye", CTX, "p:m", _result("bye"))
    got = c.get("hi", CTX, "p:m")
    assert got is not None and got.cached and got.words == words
    got2 = c.get("bye", CTX, "p:m")
    assert got2 is not None and got2.words is None
    assert c.get("nope", CTX, "p:m") is None


def test_persistence_across_instances() -> None:
    words = [WordInfo(token="x")]
    TranslationCache().put("hello", CTX, "p:m", _result("hello", words))
    got = TranslationCache().get("hello", CTX, "p:m")
    assert got is not None
    assert got.cached and got.translated_text == "vi:hello" and got.words == words
    assert TranslationCache().get("hello", CTX, "p:none-words") is None


def test_provider_ids_do_not_collide() -> None:
    c = TranslationCache()
    c.put("t", CTX, "openrouter:a", _result("A"))
    c.put("t", CTX, "openrouter:b", _result("B"))
    c2 = TranslationCache()
    assert c2.get("t", CTX, "openrouter:a").source_text == "A"  # type: ignore[union-attr]
    assert c2.get("t", CTX, "openrouter:b").source_text == "B"  # type: ignore[union-attr]


def test_pruning_keeps_newest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_mod, "_PRUNE_EVERY", 5)
    c = TranslationCache(mem_size=1, max_rows=10)
    for i in range(30):
        c.put(f"t{i}", CTX, "p", _result(f"t{i}"))
    with sqlite3.connect(_db(tmp_path)) as conn:
        (n,) = conn.execute("SELECT COUNT(*) FROM translations").fetchone()
    assert n == 10
    fresh = TranslationCache()
    assert all(fresh.get(f"t{i}", CTX, "p") is not None for i in range(20, 30))
    assert all(fresh.get(f"t{i}", CTX, "p") is None for i in range(20))


def test_corrupt_db_moved_aside(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"this is not a sqlite database" * 200)
    c = TranslationCache()
    assert db.with_name(db.name + ".corrupt").exists()
    c.put("a", CTX, "p", _result("a"))
    assert TranslationCache().get("a", CTX, "p") is not None


def test_legacy_dir_removed(tmp_path: Path) -> None:
    legacy = tmp_path / "transsnip" / "translate-cache"
    legacy.mkdir(parents=True)
    (legacy / "abc.json").write_text("{}", encoding="utf-8")
    TranslationCache()
    assert not legacy.exists()


def test_concurrent_access() -> None:
    c = TranslationCache(mem_size=16, max_rows=50)
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            for i in range(200):
                key = f"{n}-{i % 40}"
                c.put(key, CTX, "p", _result(key))
                c.get(key, CTX, "p")
                c.get(f"{(n + 1) % 8}-{i % 40}", CTX, "p")
        except BaseException as exc:  # noqa: BLE001 - surface anything to the main thread
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert c._conn is not None  # disk layer survived
