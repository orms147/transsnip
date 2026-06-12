"""Download the bundled PP-OCRv5 ONNX models into resources/models/.

Why this script exists
----------------------
The RapidOCR fallback (`transsnip/ocr/rapid_ocr.py`) reads its models from
`resources/models/` so the frozen .exe is fully offline. Those .onnx files are
~42MB total and are gitignored (binary blobs bloat the repo). Run this once
after a fresh clone, and again on the build machine before `pyinstaller`:

    python scripts/fetch_models.py

Files are fetched from the official RapidAI ModelScope mirror, pinned to a
specific release tag so the dict/model pairing stays consistent. The set here
must match `transsnip/ocr/models.py` (DET_MODEL / CLS_MODEL / the RecModel
entries) — if you add a language there, add its model + dict URL here too.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

# Pin to a release tag (not `main`) so model weights and their character dicts
# never drift out of sync mid-project.
TAG = "v3.8.0"
BASE = f"https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/{TAG}"

# (relative URL under BASE, local filename in resources/models/)
FILES: list[tuple[str, str]] = [
    # Shared, language-agnostic.
    (f"{BASE}/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx", "ch_PP-OCRv5_det_mobile.onnx"),
    (f"{BASE}/onnx/PP-OCRv5/cls/ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx",
     "ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx"),
    # Recognition: ch (= zh + ja + en + pinyin), korean, latin.
    (f"{BASE}/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx", "ch_PP-OCRv5_rec_mobile.onnx"),
    (f"{BASE}/onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx", "korean_PP-OCRv5_rec_mobile.onnx"),
    (f"{BASE}/onnx/PP-OCRv5/rec/latin_PP-OCRv5_rec_mobile.onnx", "latin_PP-OCRv5_rec_mobile.onnx"),
    # Character dictionaries (one per rec model).
    (f"{BASE}/paddle/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile/ppocrv5_dict.txt", "ppocrv5_dict.txt"),
    (f"{BASE}/paddle/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile/ppocrv5_korean_dict.txt",
     "ppocrv5_korean_dict.txt"),
    (f"{BASE}/paddle/PP-OCRv5/rec/latin_PP-OCRv5_rec_mobile/ppocrv5_latin_dict.txt",
     "ppocrv5_latin_dict.txt"),
]


def main() -> int:
    out_dir = Path(__file__).resolve().parents[1] / "resources" / "models"
    out_dir.mkdir(parents=True, exist_ok=True)
    for url, name in FILES:
        dest = out_dir / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  skip   {name} (already present)")
            continue
        print(f"  fetch  {name} ...", end="", flush=True)
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as exc:  # noqa: BLE001
            print(f" FAILED: {exc}")
            return 1
        print(f" {dest.stat().st_size // 1024} KB")
    print(f"Done. Models in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
