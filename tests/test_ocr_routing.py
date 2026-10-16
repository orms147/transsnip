"""OCR language routing — RapidOCR rec-model picker + pipeline lang match."""
from transsnip.ocr.models import rec_for_lang
from transsnip.ocr.registry import _lang_matches


def test_rec_for_lang_multi_family():
    # PP-OCRv6 multilingual model spans Chinese + Japanese + English + Latin.
    for lang in ("ja", "zh-Hant", "en", "vi", "fr"):
        assert rec_for_lang(lang).family == "multi", lang


def test_rec_for_lang_korean_stays_on_v5():
    # v6 has no Korean — the v5 Korean recognizer must keep serving it.
    rec = rec_for_lang("ko")
    assert (rec.family, rec.ocr_version) == ("korean", "PP-OCRv5")
    assert rec.dict_file


def test_rec_for_lang_auto_defaults_multi():
    assert rec_for_lang(None).family == "multi"
    assert rec_for_lang("unknown-xx").family == "multi"


def test_lang_matches_primary_subtag():
    assert _lang_matches("en", {"en-US"}) is True
    assert _lang_matches("zh-Hans", {"zh-CN"}) is True   # match by primary "zh"
    assert _lang_matches("ja", {"ja"}) is True


def test_lang_matches_negative():
    assert _lang_matches("ko", {"en-US", "ja"}) is False


class _Engine:
    def __init__(self, name, langs, available=True):
        from transsnip.ocr.base import OCRResult
        self.name, self._langs, self._available = name, langs, available
        self.warmed: list[str | None] = []
        self._result = OCRResult(engine=name)

    def is_available(self):
        return self._available

    def supported_languages(self):
        return self._langs

    def warm_up(self, lang=None):
        self.warmed.append(lang)


def _pipeline(*engines):
    from transsnip.ocr.registry import OCRPipeline
    return OCRPipeline(list(engines))


def test_warm_up_targets_first_engine_that_serves_the_language():
    win = _Engine("windows", {"en-US", "ja"})
    rapid = _Engine("rapid", {"zh", "ko", "en", "ja"})
    p = _pipeline(win, rapid)
    p.warm_up("ko")          # no Windows pack → fallback is what runs
    p.warm_up("en")          # Windows serves it → only Windows "warms" (a no-op there)
    assert rapid.warmed == ["ko"]
    assert win.warmed == ["en"]


def test_warm_up_skips_unavailable_and_swallows_errors():
    broken = _Engine("rapid", {"ko"})
    broken.warm_up = lambda lang=None: (_ for _ in ()).throw(RuntimeError("boom"))
    _pipeline(_Engine("windows", {"ko"}, available=False), broken).warm_up("ko")
