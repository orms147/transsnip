"""OCR benchmark — latency + character error rate per engine on screen-like images.

Renders synthetic captures that mimic what TransSnip actually OCRs (UI labels,
wrapped paragraphs, CJK lines, Vietnamese diacritics, video subtitles over a
busy frame, a tall narrow region, a full 1080p page of small text) and runs
each engine on them. Used to validate OCR changes with numbers instead of
eyeballing single screenshots:

    python scripts/ocr_bench.py                 # all engines, all cases
    python scripts/ocr_bench.py --engine rapid --case subtitle_ja --runs 10

CER = Levenshtein(ref, hyp) / len(ref) after whitespace normalisation
(whitespace is removed entirely for CJK, where it isn't meaningful).
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FONTS = Path("C:/Windows/Fonts")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in name.split("|"):
        path = _FONTS / candidate
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise SystemExit(f"font not found: {name}")


LATIN = "segoeui.ttf|arial.ttf"
JA = "YuGothM.ttc|meiryo.ttc|msgothic.ttc"
ZH = "msyh.ttc|simsun.ttc"
KO = "malgun.ttf"


@dataclass
class Case:
    name: str
    image: Image.Image
    ref: str
    lang: str | None
    cjk: bool = False


def _text_image(
    lines: list[str], font: ImageFont.FreeTypeFont, *, width: int | None = None,
    pad: int = 12, spacing: float = 1.45, fg=(20, 20, 20), bg=(255, 255, 255),
) -> Image.Image:
    line_h = int(font.size * spacing)
    w = width or max(int(font.getlength(t)) for t in lines) + 2 * pad
    img = Image.new("RGB", (w, line_h * len(lines) + 2 * pad), bg)
    d = ImageDraw.Draw(img)
    for i, t in enumerate(lines):
        d.text((pad, pad + i * line_h), t, font=font, fill=fg)
    return img


def _subtitle(text: str, font: ImageFont.FreeTypeFont, size=(900, 90)) -> Image.Image:
    """White text, black outline, over a noisy 'video frame' background."""
    rng = random.Random(7)
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            base = (x * 255 // size[0] + y * 2) % 255
            px[x, y] = (base, (base * 3 + rng.randint(0, 60)) % 255, 120 + rng.randint(-40, 40))
    img = img.filter(ImageFilter.GaussianBlur(2))
    d = ImageDraw.Draw(img)
    tw = font.getlength(text)
    d.text(((size[0] - tw) / 2, (size[1] - font.size) / 2 - 4), text, font=font,
           fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    return img


def build_cases() -> list[Case]:
    en_para = [
        "The quick brown fox jumps over the lazy dog. Screen text is usually",
        "rendered with ClearType anti-aliasing at 14 to 16 pixels, which makes",
        "thin strokes and punctuation easy for an OCR engine to drop.",
    ]
    page_lines = [f"{i:02d}. Settings → Display → Scale is set to 125% on this monitor."
                  for i in range(1, 31)]
    cases = [
        Case("ui_en_small", _text_image(["File  Edit  View  Selection  Help"],
                                        _font(LATIN, 13)), "File Edit View Selection Help", "en"),
        Case("para_en", _text_image(en_para, _font(LATIN, 15)), " ".join(en_para), "en"),
        Case("line_ja", _text_image(["受講の申し込みは来週の月曜日までにお願いします。"],
                                    _font(JA, 16)),
             "受講の申し込みは来週の月曜日までにお願いします。", "ja", cjk=True),
        Case("line_zh", _text_image(["今天的会议改到下午三点，请大家准时参加。"], _font(ZH, 16)),
             "今天的会议改到下午三点，请大家准时参加。", "zh-Hans", cjk=True),
        Case("line_ko", _text_image(["오늘 회의는 오후 세 시로 변경되었습니다."], _font(KO, 16)),
             "오늘 회의는 오후 세 시로 변경되었습니다.", "ko", cjk=True),
        Case("line_vi", _text_image(["Tiếng Việt có dấu: những người đồng hành đáng tin cậy."],
                                    _font(LATIN, 16)),
             "Tiếng Việt có dấu: những người đồng hành đáng tin cậy.", "vi"),
        Case("subtitle_en", _subtitle("I never said she stole my money.", _font(LATIN, 34)),
             "I never said she stole my money.", "en"),
        Case("subtitle_ja", _subtitle("それは本当に君のせいじゃないよ", _font(JA, 34)),
             "それは本当に君のせいじゃないよ", "ja", cjk=True),
        Case("tall_narrow_en", _text_image(
            [f"Item {i}: open the file and save it" for i in range(1, 25)],
            _font(LATIN, 14), width=330),
             " ".join(f"Item {i}: open the file and save it" for i in range(1, 25)), "en"),
        Case("fullscreen_1080p", _text_image(page_lines, _font(LATIN, 13), width=1920),
             " ".join(page_lines), "en"),
    ]
    # Pad the 1080p page to a real monitor size so detection sees the full frame.
    fs = next(c for c in cases if c.name == "fullscreen_1080p")
    canvas = Image.new("RGB", (1920, 1080), (255, 255, 255))
    canvas.paste(fs.image, (0, 0))
    fs.image = canvas
    return cases


def _normalise(s: str, cjk: bool) -> str:
    s = " ".join(s.split())
    return s.replace(" ", "") if cjk else s


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str, cjk: bool) -> float:
    r, h = _normalise(ref, cjk), _normalise(hyp, cjk)
    return _levenshtein(r, h) / max(1, len(r))


def _engines(which: str):
    from transsnip.ocr.rapid_ocr import RapidOCREngine
    from transsnip.ocr.windows_ocr import WindowsOCR

    out = {}
    if which in ("all", "windows"):
        out["windows"] = WindowsOCR()
    if which in ("all", "rapid"):
        out["rapid"] = RapidOCREngine()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="all", choices=["all", "windows", "rapid"])
    ap.add_argument("--case", default=None, help="substring filter on case name")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--save", type=Path, default=None, help="dump case images here")
    args = ap.parse_args()

    from transsnip.ocr.base import OCRError

    cases = [c for c in build_cases() if not args.case or args.case in c.name]
    if args.save:
        args.save.mkdir(parents=True, exist_ok=True)
        for c in cases:
            c.image.save(args.save / f"{c.name}.png")

    print(f"{'engine':8} {'case':18} {'size':>10} {'cold ms':>8} {'warm ms':>8} {'CER':>6}  text")
    for ename, engine in _engines(args.engine).items():
        if not engine.is_available():
            print(f"{ename:8} (unavailable)")
            continue
        for c in cases:
            size = f"{c.image.width}x{c.image.height}"
            t0 = time.perf_counter()
            try:
                result = engine.recognize(c.image, c.lang)
            except OCRError as exc:
                print(f"{ename:8} {c.name:18} {size:>10} {'-':>8} {'-':>8} {'ERR':>6}  {exc}"[:160])
                continue
            cold = (time.perf_counter() - t0) * 1000
            times = []
            for _ in range(args.runs):
                t0 = time.perf_counter()
                result = engine.recognize(c.image, c.lang)
                times.append((time.perf_counter() - t0) * 1000)
            hyp = result.text
            score = cer(c.ref, hyp, c.cjk)
            shown = hyp.replace("\n", " / ")[:60]
            print(f"{ename:8} {c.name:18} {size:>10} {cold:8.0f} "
                  f"{statistics.median(times):8.0f} {score:6.1%}  {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
