# Bundled OCR models (ONNX)

These files power the **RapidOCR fallback** (`transsnip/ocr/rapid_ocr.py`) — the
OS-independent engine behind Windows OCR. They are **not committed** (gitignored;
~45MB of binary weights). Fetch them once after cloning (SHA-256 verified):

```bash
python scripts/fetch_models.py
```

Run the same command on the build machine before `pyinstaller`; `TransSnip.spec`
bundles exactly `transsnip.ocr.models.BUNDLED_FILES` (stale files here are ignored).

| File | Role | Covers |
|------|------|--------|
| `PP-OCRv6_det_small.onnx` | text detection (shared) | any script |
| `PP-OCRv6_rec_small.onnx` | recognition (dict embedded) | Chinese (simp/trad) + Japanese + English + ~45 Latin-script langs |
| `korean_PP-OCRv5_rec_mobile.onnx` + `ppocrv5_korean_dict.txt` | recognition | Korean (PP-OCRv6 has none) |

Vietnamese caveat: no PP-OCR dict has the precomposed tone letters (ế, ệ, ạ…),
so Vietnamese source text reads far better with the Windows "vi" OCR pack.

Language → model routing (and the benchmark numbers behind the choice) lives
in `transsnip/ocr/models.py`. Old `*PP-OCRv5*` ch/latin/det files from earlier
releases can be deleted.
