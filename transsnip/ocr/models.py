"""PP-OCRv5 model files + per-language routing for the RapidOCR fallback.

Why this module exists
----------------------
Windows OCR is the fast primary engine, but it only reads languages whose
OS pack is installed. RapidOCR is the bundled fallback that must work on a
bare machine with no OS configuration — so the ONNX models ship *inside the
app* (repo `resources/models/` in dev, `sys._MEIPASS/resources/models` when
frozen by PyInstaller).

PP-OCRv5 splits recognition by script family: ONE `ch` model already covers
Simplified/Traditional Chinese + Pinyin + English + Japanese, and separate
small models cover Korean and the 45+ Latin-script languages. The detection
and angle-classifier models are language-agnostic and shared across families.
`rec_for_lang()` maps a BCP-47 source tag to the right (model, dict, enum)
triple; `RapidOCREngine` caches one engine per family.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


def models_dir() -> Path:
    """Absolute path to the bundled `resources/models` directory.

    PyInstaller unpacks bundled data under `sys._MEIPASS` at runtime; in a
    normal checkout the files live at `<repo>/resources/models`. Resolving
    both here keeps every caller from re-deriving the path.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "resources" / "models"
    # ocr/models.py → ocr → transsnip → <repo root>
    return Path(__file__).resolve().parents[2] / "resources" / "models"


# Shared, language-agnostic models (one detection + one angle classifier for
# every script family). Mobile variants — small + fast, accuracy is plenty for
# screen text.
DET_MODEL = "ch_PP-OCRv5_det_mobile.onnx"
CLS_MODEL = "ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx"


@dataclass(frozen=True)
class RecModel:
    """A PP-OCRv5 recognition model + its character dictionary + lang enum.

    `lang_type` is the string value of rapidocr's `LangRec` enum (kept as a
    plain str so this module has no hard dependency on the rapidocr package —
    the engine converts it to the enum at construction time).
    """

    model: str
    dict_file: str
    lang_type: str  # rapidocr LangRec value: "ch" / "korean" / "latin"


# The three families we bundle. `ch` is the workhorse (zh + ja + en + pinyin).
_REC_CH = RecModel("ch_PP-OCRv5_rec_mobile.onnx", "ppocrv5_dict.txt", "ch")
_REC_KOREAN = RecModel("korean_PP-OCRv5_rec_mobile.onnx", "ppocrv5_korean_dict.txt", "korean")
_REC_LATIN = RecModel("latin_PP-OCRv5_rec_mobile.onnx", "ppocrv5_latin_dict.txt", "latin")

# BCP-47 primary subtag → recognition family. Anything not listed (incl. the
# `None`/auto case) falls back to `_REC_CH`, whose model spans the three
# scripts most common in this app's captures (Chinese, Japanese, English).
_LANG_TO_REC: dict[str, RecModel] = {
    "zh": _REC_CH,
    "ja": _REC_CH,
    "en": _REC_CH,
    "ko": _REC_KOREAN,
    # Latin-script languages share one model. Vietnamese (with diacritics),
    # French, German, Spanish, Italian, Portuguese, Indonesian, etc.
    "vi": _REC_LATIN,
    "fr": _REC_LATIN,
    "de": _REC_LATIN,
    "es": _REC_LATIN,
    "it": _REC_LATIN,
    "pt": _REC_LATIN,
    "id": _REC_LATIN,
    "nl": _REC_LATIN,
}

# Every BCP-47 primary subtag the fallback can handle — surfaced via
# `RapidOCREngine.supported_languages()` so the pipeline's language filter
# never skips it. (The `ch` model also reads Traditional Chinese / pinyin.)
SUPPORTED_LANGS: frozenset[str] = frozenset(_LANG_TO_REC) | {"zh-Hans", "zh-Hant"}


def rec_for_lang(lang: str | None) -> RecModel:
    """Pick the recognition family for a source-language tag.

    Matches by primary subtag (`zh-Hant` → `zh`). Unknown tags and auto-detect
    (`None`) route to the `ch` model — the broadest single model we bundle.
    """
    if not lang:
        return _REC_CH
    primary = lang.lower().split("-")[0]
    return _LANG_TO_REC.get(primary, _REC_CH)
