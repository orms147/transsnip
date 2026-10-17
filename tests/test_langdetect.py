import pytest

from transsnip.linguistic.langdetect import detect_lang, effective_source


@pytest.mark.parametrize(("text", "lang", "confident"), [
    ("受講の申し込みは来週の月曜日までにお願いします。", "ja", True),
    ("Pythonで画像を読み込む方法（OpenCV 4.9対応）", "ja", True),
    ("クエスト完了！報酬：ゴールド×500", "ja", True),
    ("今天的会议改到下午三点，请大家准时参加。", "zh-Hans", False),
    ("使用 Docker Compose 部署 Redis 7.2 集群", "zh-Hans", False),
    ("你到底想要什么 What do you really want", "zh-Hans", False),
    ("I never said she stole my money.", "en", True),
    ("File  Edit  View  Selection  Help", "en", True),
    ("오늘 회의는 오후 세 시로 변경되었습니다.", "ko", True),
    ("Tiếng Việt có dấu", None, False),
    ("12:30 — 45%", None, False),
])
def test_detect_lang(text, lang, confident):
    d = detect_lang(text)
    assert (d.lang, d.confident) == (lang, confident)


def test_kanji_only_japanese_is_never_pinned():
    # Indistinguishable from Chinese by script — must not force a source.
    d = detect_lang("東京都知事選挙")
    assert d.lang and d.lang.startswith("zh") and not d.confident


def test_traditional_chinese_detected():
    pytest.importorskip("zhconv")
    assert detect_lang("這個功能目前還在測試中，請稍後再試。").lang == "zh-Hant"


def test_setting_always_wins():
    assert effective_source("ja", "I am English") == ("ja", True)
    assert effective_source(None, "I am English") == ("en", True)
