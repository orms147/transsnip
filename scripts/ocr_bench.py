"""OCR benchmark — latency + character error rate per engine on screen-like images.

Renders synthetic captures that mimic what TransSnip actually OCRs — the app's
target source languages are Chinese, English and Japanese: UI labels (light
and dark mode), dense paragraphs, Traditional Chinese, CJK/Latin mixed lines,
game UI, video subtitles (outlined, yellow, shadow-only, over bright frames,
bilingual), a tall narrow region and a full 1080p page — and runs each engine
(or the app's real Windows → RapidOCR pipeline) on them. Used to validate OCR
changes with numbers instead of
eyeballing single screenshots:

    python scripts/ocr_bench.py                 # all engines, all cases
    python scripts/ocr_bench.py --engine rapid --case subtitle_ja --runs 10
    python scripts/ocr_bench.py --engine pipeline --auto   # source lang = auto

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
JA_BOLD = "meiryob.ttc|YuGothB.ttc"
ZH = "msyh.ttc|simsun.ttc"
ZH_SERIF = "simsun.ttc|msyh.ttc"
ZH_TRAD = "msjh.ttc|mingliub.ttc"


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


def _frame(size: tuple[int, int], *, bright: bool = False, seed: int = 7) -> Image.Image:
    """A blurred noisy 'video frame' background (bright = sky/snow scene)."""
    rng = random.Random(seed)
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            base = (x * 255 // size[0] + y * 2) % 255
            if bright:
                px[x, y] = (200 + base % 55, 205 + rng.randint(0, 50), 210 + rng.randint(0, 45))
            else:
                px[x, y] = (base, (base * 3 + rng.randint(0, 60)) % 255,
                            120 + rng.randint(-40, 40))
    return img.filter(ImageFilter.GaussianBlur(2))


def _subtitle(
    lines: str | list[str], font: ImageFont.FreeTypeFont, size=(900, 90), *,
    fill=(255, 255, 255), stroke: int = 3, shadow: bool = False, bright: bool = False,
    fonts: list[ImageFont.FreeTypeFont] | None = None,
) -> Image.Image:
    """Centered subtitle line(s) over a video frame. Default: white + black outline."""
    lines = [lines] if isinstance(lines, str) else lines
    fonts = fonts or [font] * len(lines)
    img = _frame(size, bright=bright)
    d = ImageDraw.Draw(img)
    total_h = sum(int(f.size * 1.3) for f in fonts)
    y = (size[1] - total_h) / 2
    for text, f in zip(lines, fonts, strict=True):
        x = (size[0] - f.getlength(text)) / 2
        if shadow:
            d.text((x + 2, y + 2), text, font=f, fill=(0, 0, 0))
        d.text((x, y), text, font=f, fill=fill,
               stroke_width=stroke, stroke_fill=(0, 0, 0) if stroke else None)
        y += int(f.size * 1.3)
    return img


def _game_ui(text: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    """Bold light text with a dark outline on a gradient panel."""
    w, h = int(font.getlength(text)) + 40, int(font.size * 2.2)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (40 + x * 120 // w, 30 + y * 60 // h, 90 + x * 80 // w)
    ImageDraw.Draw(img).text((20, (h - font.size) / 2 - 3), text, font=font,
                             fill=(255, 245, 200), stroke_width=2, stroke_fill=(20, 10, 0))
    return img


def build_cases() -> list[Case]:
    en_para = [
        "The quick brown fox jumps over the lazy dog. Screen text is usually",
        "rendered with ClearType anti-aliasing at 14 to 16 pixels, which makes",
        "thin strokes and punctuation easy for an OCR engine to drop.",
    ]
    page_lines = [f"{i:02d}. Settings → Display → Scale is set to 125% on this monitor."
                  for i in range(1, 31)]
    zh_para = [
        "近日，国家统计局发布了最新的经济数据，显示今年前三季度",
        "国内生产总值同比增长百分之五点二，消费市场持续回暖，",
        "其中服务业增加值占比进一步提高。",
    ]
    ja_para = [
        "本サービスをご利用いただくには、事前にアカウント登録が必要です。",
        "登録後、確認メールに記載されたリンクをクリックしてください。",
        "詳しくはヘルプページをご覧ください。",
    ]
    t_mixed_ja = "Pythonで画像を読み込む方法（OpenCV 4.9対応）"
    t_mixed_zh = "使用 Docker Compose 部署 Redis 7.2 集群"
    t_game = "クエスト完了！報酬：ゴールド×500"
    cases = [
        # -- UI / documents ------------------------------------------------
        Case("ui_en_small", _text_image(["File  Edit  View  Selection  Help"],
                                        _font(LATIN, 13)), "File Edit View Selection Help", "en"),
        Case("para_en", _text_image(en_para, _font(LATIN, 15)), " ".join(en_para), "en"),
        Case("lowcontrast_en", _text_image(["Disabled: Sync settings across devices"],
                                           _font(LATIN, 13), fg=(158, 158, 158)),
             "Disabled: Sync settings across devices", "en"),
        Case("line_ja", _text_image(["受講の申し込みは来週の月曜日までにお願いします。"],
                                    _font(JA, 16)),
             "受講の申し込みは来週の月曜日までにお願いします。", "ja", cjk=True),
        Case("para_ja_12px", _text_image(ja_para, _font(JA, 12)), "".join(ja_para), "ja",
             cjk=True),
        Case("mixed_ja_en", _text_image([t_mixed_ja], _font(JA, 16)), t_mixed_ja, "ja", cjk=True),
        Case("line_zh", _text_image(["今天的会议改到下午三点，请大家准时参加。"], _font(ZH, 16)),
             "今天的会议改到下午三点，请大家准时参加。", "zh-Hans", cjk=True),
        Case("para_zh_serif", _text_image(zh_para, _font(ZH_SERIF, 15)), "".join(zh_para),
             "zh-Hans", cjk=True),
        Case("dark_ui_zh", _text_image(["设置已保存，重启后生效。是否立即重启？"], _font(ZH, 14),
                                       fg=(220, 220, 220), bg=(30, 30, 30)),
             "设置已保存，重启后生效。是否立即重启？", "zh-Hans", cjk=True),
        Case("trad_zh", _text_image(["這個功能目前還在測試中，請稍後再試。"], _font(ZH_TRAD, 16)),
             "這個功能目前還在測試中，請稍後再試。", "zh-Hant", cjk=True),
        Case("mixed_zh_en", _text_image([t_mixed_zh], _font(ZH, 16)), t_mixed_zh, "zh-Hans",
             cjk=True),
        Case("game_ui_ja", _game_ui(t_game, _font(JA_BOLD, 22)), t_game, "ja", cjk=True),
        # -- Video subtitles -----------------------------------------------
        Case("subtitle_en", _subtitle("I never said she stole my money.", _font(LATIN, 34)),
             "I never said she stole my money.", "en"),
        Case("subtitle_ja", _subtitle("それは本当に君のせいじゃないよ", _font(JA, 34)),
             "それは本当に君のせいじゃないよ", "ja", cjk=True),
        Case("subtitle_zh", _subtitle("我们明天早上八点在机场见面", _font(ZH, 34)),
             "我们明天早上八点在机场见面", "zh-Hans", cjk=True),
        Case("sub_yellow_en", _subtitle("Where did you put the keys?", _font(LATIN, 32),
                                        fill=(255, 230, 40), stroke=0, shadow=True),
             "Where did you put the keys?", "en"),
        Case("sub_shadow_ja", _subtitle("ちょっと待って、まだ終わってない", _font(JA, 32),
                                        stroke=0, shadow=True),
             "ちょっと待って、まだ終わってない", "ja", cjk=True),
        Case("sub_bright_zh", _subtitle("外面下雪了，快来看", _font(ZH, 34), bright=True),
             "外面下雪了，快来看", "zh-Hans", cjk=True),
        Case("sub_bilingual", _subtitle(["你到底想要什么", "What do you really want"],
                                        _font(ZH, 30), size=(900, 120),
                                        fonts=[_font(ZH, 30), _font(LATIN, 24)]),
             "你到底想要什么 What do you really want", "zh-Hans", cjk=True),
        # -- Geometry stress -----------------------------------------------
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
    from transsnip.ocr.registry import default_pipeline
    from transsnip.ocr.windows_ocr import WindowsOCR

    out = {}
    if which in ("all", "windows"):
        out["windows"] = WindowsOCR()
    if which in ("all", "rapid"):
        out["rapid"] = RapidOCREngine()
    if which in ("all", "pipeline"):
        out["pipeline"] = default_pipeline()  # what the app actually runs
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="all",
                    choices=["all", "windows", "rapid", "pipeline"])
    ap.add_argument("--auto", action="store_true",
                    help="pass lang=None (Settings source language = auto-detect)")
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
        if hasattr(engine, "is_available") and not engine.is_available():
            print(f"{ename:8} (unavailable)")
            continue
        for c in cases:
            lang = None if args.auto else c.lang
            size = f"{c.image.width}x{c.image.height}"
            t0 = time.perf_counter()
            try:
                result = engine.recognize(c.image, lang)
            except OCRError as exc:
                print(f"{ename:8} {c.name:18} {size:>10} {'-':>8} {'-':>8} {'ERR':>6}  {exc}"[:160])
                continue
            cold = (time.perf_counter() - t0) * 1000
            times = []
            for _ in range(args.runs):
                t0 = time.perf_counter()
                result = engine.recognize(c.image, lang)
                times.append((time.perf_counter() - t0) * 1000)
            hyp = result.text
            score = cer(c.ref, hyp, c.cjk)
            shown = hyp.replace("\n", " / ")[:60]
            print(f"{ename:8} {c.name:18} {size:>10} {cold:8.0f} "
                  f"{statistics.median(times):8.0f} {score:6.1%}  {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
