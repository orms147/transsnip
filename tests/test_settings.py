"""Settings model — defaults, JSON round-trip, preset fallback."""
from transsnip.config.settings import Settings, get_preset


def test_defaults():
    s = Settings()
    assert s.translate.provider == "google_free"
    assert s.translate.target_lang == "vi"
    assert s.translate.display_mode == "simple"
    assert len(s.presets) >= 1


def test_json_round_trip():
    s = Settings()
    s.translate.display_mode = "learning"
    s.translate.target_lang = "ja"
    restored = Settings.model_validate_json(s.model_dump_json())
    assert restored.translate.display_mode == "learning"
    assert restored.translate.target_lang == "ja"


def test_extra_keys_ignored():
    # Old settings.json with removed fields must still load (forward/back compat).
    raw = '{"translate": {"provider": "gemini", "overlay_style": "gone"}}'
    s = Settings.model_validate_json(raw)
    assert s.translate.provider == "gemini"


def test_get_preset_fallback():
    s = Settings()
    p = get_preset(s, "does-not-exist")
    assert p.name == "does-not-exist"  # blank fallback, not a crash
    assert p.system_prompt == ""


def test_get_preset_known():
    s = Settings()
    p = get_preset(s, "programming")
    assert p.name == "programming"
    assert p.system_prompt  # built-in preset has a prompt
