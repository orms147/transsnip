"""Download the bundled OCR models (PP-OCRv6 + PP-OCRv5 Korean) into resources/models/.

Why this script exists
----------------------
The RapidOCR fallback (`transsnip/ocr/rapid_ocr.py`) reads its models from
`resources/models/` so the frozen .exe is fully offline. Those .onnx files are
binary blobs (~45 MB) and are gitignored. Run this once after a fresh clone,
and again on the build machine before `pyinstaller`:

    python scripts/fetch_models.py

Files come from the official RapidAI ModelScope mirror, pinned to a release
tag, and are SHA-256 verified (a truncated/poisoned download fails loudly
instead of shipping). The set here must match `transsnip/ocr/models.py`.
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

_BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve"

# (url, local filename, sha256 or None). sha256 from rapidocr's
# default_models.yaml for the pinned tag; None = not published there.
FILES: list[tuple[str, str, str | None]] = [
    # PP-OCRv6 small — one multilingual det + rec covering zh/ja/en + ~45 Latin
    # languages (dict embedded in the ONNX metadata, no .txt).
    (f"{_BASE}/v3.10.0/onnx/PP-OCRv6/det/PP-OCRv6_det_small.onnx", "PP-OCRv6_det_small.onnx",
     "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    (f"{_BASE}/v3.10.0/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx", "PP-OCRv6_rec_small.onnx",
     "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
    # v6 has no Korean — keep the PP-OCRv5 Korean recognizer + its dict.
    (f"{_BASE}/v3.8.0/onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx",
     "korean_PP-OCRv5_rec_mobile.onnx", None),
    (f"{_BASE}/v3.8.0/paddle/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile/ppocrv5_korean_dict.txt",
     "ppocrv5_korean_dict.txt", None),
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out_dir = Path(__file__).resolve().parents[1] / "resources" / "models"
    out_dir.mkdir(parents=True, exist_ok=True)
    for url, name, sha in FILES:
        dest = out_dir / name
        if dest.exists() and dest.stat().st_size > 0 and (sha is None or _sha256(dest) == sha):
            print(f"  skip   {name} (already present)")
            continue
        print(f"  fetch  {name} ...", end="", flush=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, tmp)
        except Exception as exc:  # noqa: BLE001
            print(f" FAILED: {exc}")
            tmp.unlink(missing_ok=True)
            return 1
        if sha is not None and _sha256(tmp) != sha:
            print(" FAILED: sha256 mismatch")
            tmp.unlink(missing_ok=True)
            return 1
        tmp.replace(dest)
        print(f" {dest.stat().st_size // 1024} KB")
    print(f"Done. Models in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
