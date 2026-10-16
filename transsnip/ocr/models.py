"""Bundled RapidOCR model files + per-language routing.

Why this module exists
----------------------
Windows OCR is the fast primary engine, but it only reads languages whose
OS pack is installed. RapidOCR is the bundled fallback that must work on a
bare machine with no OS configuration — so the ONNX models ship *inside the
app* (repo `resources/models/` in dev, `sys._MEIPASS/resources/models` when
frozen by PyInstaller).

Model choice (measured with scripts/ocr_bench.py, rapidocr 3.10):
- **PP-OCRv6 small** for everything it covers — ONE multilingual recognizer
  spans Chinese (simp/trad) + Japanese + English + ~45 Latin-script languages,
  replacing v5's separate ch + latin models. ~25% faster than v5 mobile on
  larger captures and fixes v5's fullscreen misses (CER 33% → 1% at the same
  detector size on rapidocr 3.10). Its dict also gained ư/ơ, so Vietnamese
  improves (CER 19% → 11%) — still not good: the precomposed tone letters
  (ế, ệ, ạ…) are missing from every PP-OCR dict, so Vietnamese source text
  really wants the Windows "vi" OCR pack.
- **PP-OCRv5 Korean** recognizer: v6 has no Korean at all (CER 100%).
`rec_for_lang()` maps a BCP-47 source tag to one of these families;
`RapidOCREngine` caches one engine per family.
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


# Shared, language-agnostic text detector (also drives the Korean family).
DET_MODEL = "PP-OCRv6_det_small.onnx"
DET_VERSION = "PP-OCRv6"
DET_TYPE = "small"


@dataclass(frozen=True)
class RecModel:
    """One recognition family: model file (+ dict for v5) + rapidocr enum values.

    Enum values are plain strings so this module has no hard dependency on
    the rapidocr package — the engine converts them at construction time.
    """

    family: str            # engine cache key
    model: str
    dict_file: str | None  # v6 embeds its dict in the ONNX metadata
    lang_type: str         # rapidocr LangRec value
    ocr_version: str       # rapidocr OCRVersion value
    model_type: str        # rapidocr ModelType value


_REC_MULTI = RecModel("multi", "PP-OCRv6_rec_small.onnx", None, "ch", "PP-OCRv6", "small")
_REC_KOREAN = RecModel(
    "korean", "korean_PP-OCRv5_rec_mobile.onnx", "ppocrv5_korean_dict.txt",
    "korean", "PP-OCRv5", "mobile",
)

# BCP-47 primary subtag → recognition family. Anything not listed (incl. the
# `None`/auto case) uses the multilingual v6 model.
_LANG_TO_REC: dict[str, RecModel] = {
    "zh": _REC_MULTI,
    "ja": _REC_MULTI,
    "en": _REC_MULTI,
    "ko": _REC_KOREAN,
    # Latin-script languages (v6 covers ~45; these are the ones Settings offers).
    "vi": _REC_MULTI,
    "fr": _REC_MULTI,
    "de": _REC_MULTI,
    "es": _REC_MULTI,
    "it": _REC_MULTI,
    "pt": _REC_MULTI,
    "id": _REC_MULTI,
    "nl": _REC_MULTI,
}

# Every BCP-47 primary subtag the fallback can handle — surfaced via
# `RapidOCREngine.supported_languages()` so the pipeline's language filter
# never skips it.
SUPPORTED_LANGS: frozenset[str] = frozenset(_LANG_TO_REC) | {"zh-Hans", "zh-Hant"}

# Every file the app needs at runtime — TransSnip.spec bundles exactly these
# (not a glob, so stale models from older releases never ship).
BUNDLED_FILES: tuple[str, ...] = (
    DET_MODEL,
    _REC_MULTI.model,
    _REC_KOREAN.model,
    _REC_KOREAN.dict_file or "",
)


def rec_for_lang(lang: str | None) -> RecModel:
    """Pick the recognition family for a source-language tag.

    Matches by primary subtag (`zh-Hant` → `zh`). Unknown tags and auto-detect
    (`None`) route to the multilingual model — the broadest we bundle.
    """
    if not lang:
        return _REC_MULTI
    primary = lang.lower().split("-")[0]
    return _LANG_TO_REC.get(primary, _REC_MULTI)
