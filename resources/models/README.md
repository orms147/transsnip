# Bundled OCR models (PP-OCRv5, ONNX)

These files power the **RapidOCR fallback** (`transsnip/ocr/rapid_ocr.py`) — the
OS-independent engine behind Windows OCR. They are **not committed** (gitignored;
~42MB of binary weights). Fetch them once after cloning:

```bash
python scripts/fetch_models.py
```

Run the same command on the build machine before `pyinstaller` so the .exe
bundles them (see `TransSnip.spec`).

| File | Role | Covers |
|------|------|--------|
| `ch_PP-OCRv5_det_mobile.onnx` | detection (shared) | any script |
| `ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx` | angle classifier (shared, currently unused) | — |
| `ch_PP-OCRv5_rec_mobile.onnx` + `ppocrv5_dict.txt` | recognition | Chinese (simp/trad) + Pinyin + English + **Japanese** |
| `korean_PP-OCRv5_rec_mobile.onnx` + `ppocrv5_korean_dict.txt` | recognition | Korean |
| `latin_PP-OCRv5_rec_mobile.onnx` + `ppocrv5_latin_dict.txt` | recognition | 45+ Latin-script langs (vi, fr, de, es, …) |

Language → model routing lives in `transsnip/ocr/models.py`. To add a script,
add its model + dict URL to `scripts/fetch_models.py` and a `RecModel` entry +
routing in `models.py`.
