"""Stroke-order data store + animated widget (no network)."""
from __future__ import annotations

import hashlib
import json

from PySide6.QtGui import QImage

from transsnip.learning.zh import strokes as st
from transsnip.ui.stroke_widget import StrokeOrderWidget, parse_svg_path

# 永 from Make Me a Hanzi graphics.txt (Arphic Public License) — the classic
# "eight principles" character, so it exercises most stroke shapes.
YONG = {
    "character": "永",
    "strokes": [
        (
            "M 440 788 Q 497 731 535 718 Q 553 717 562 732 Q 569 748 564 767 Q 546 815 477 "
            "828 Q 438 841 421 834 Q 414 831 418 817 Q 421 804 440 788 Z"
        ),
        (
            "M 532 448 Q 532 547 546 570 Q 559 589 546 601 Q 524 620 486 636 Q 462 645 413 "
            "615 Q 371 599 306 589 Q 290 588 299 578 Q 309 568 324 562 Q 343 558 370 565 Q "
            "406 575 441 587 Q 460 594 467 584 Q 473 566 475 538 Q 482 271 470 110 Q 469 80 "
            "459 67 Q 453 61 369 82 Q 342 95 344 79 Q 411 27 450 -13 Q 463 -32 480 -38 Q 490 "
            "-42 499 -32 Q 541 16 540 77 Q 533 207 532 403 L 532 448 Z"
        ),
        (
            "M 117 401 Q 104 401 102 392 Q 101 385 117 377 Q 163 352 192 363 Q 309 397 320 "
            "395 Q 333 392 323 365 Q 280 256 240 205 Q 200 147 126 86 Q 111 73 122 71 Q 132 "
            "70 153 80 Q 220 114 275 172 Q 327 224 394 362 Q 404 384 416 397 Q 431 409 422 "
            "419 Q 412 432 374 445 Q 353 455 305 434 Q 215 412 117 401 Z"
        ),
        (
            "M 567 407 Q 639 452 745 526 Q 767 542 793 552 Q 817 562 806 582 Q 793 601 765 "
            "618 Q 740 634 725 632 Q 712 631 715 616 Q 719 582 641 505 Q 601 465 556 420 C "
            "535 399 542 391 567 407 Z"
        ),
        (
            "M 556 420 Q 543 436 532 448 C 512 470 515 427 532 403 Q 737 114 799 116 Q 871 "
            "126 933 135 Q 960 138 960 145 Q 961 152 930 165 Q 777 217 733 253 Q 678 296 567 "
            "407 L 556 420 Z"
        ),
    ],
    "medians": [
        [[428, 824], [503, 781], [533, 756], [539, 741]],
        [
            [309, 579], [358, 580], [462, 613], [482, 608], [508, 581], [505, 121], [500, 59], [478,
            24], [355, 78]
        ],
        [
            [110, 391], [149, 384], [198, 387], [322, 418], [339, 417], [367, 402], [345, 333],
            [273, 208], [201, 129], [125, 78]
        ],
        [[725, 621], [743, 596], [749, 578], [743, 570], [656, 489], [569, 421], [569, 415]],
        [[532, 441], [551, 399], [568, 378], [678, 259], [750, 194], [801, 163], [954, 145]],
    ],
}


def _fixture(tmp_path):
    one = {"character": "一", "strokes": ["M 100 400 L 900 400 L 900 380 L 100 380 Z"],
           "medians": [[[100, 390], [900, 390]]]}
    text = "\n".join([json.dumps(YONG, ensure_ascii=False), "{not json", json.dumps(one)]) + "\n"
    src = tmp_path / "graphics.txt"
    src.write_text(text, encoding="utf-8")
    return src, hashlib.sha256(src.read_bytes()).hexdigest()


def _data():
    return st.CharStrokes(
        strokes=YONG["strokes"], medians=[[tuple(p) for p in m] for m in YONG["medians"]]
    )


def test_parser_handles_all_commands():
    path = parse_svg_path("M 0 0 L 10 0 Q 20 10 10 20 C 5 25 0 25 0 20 Z")
    assert not path.isEmpty()
    assert path.elementCount() >= 7
    # Y flips: data y=0 sits at screen y=900.
    assert path.boundingRect().bottom() == 900
    for s in YONG["strokes"]:
        assert parse_svg_path(s).boundingRect().width() > 0


def test_download_builds_db(tmp_path):
    src, sha = _fixture(tmp_path)
    dest = tmp_path / "zh-strokes.sqlite3"
    seen = []
    st.download(lambda d, t: seen.append(d), url=src.as_uri(), sha256=sha, dest=dest)
    assert seen and seen[-1] == src.stat().st_size
    assert sorted(p.name for p in tmp_path.iterdir()) == ["graphics.txt", dest.name]
    store = st.StrokeStore(dest)
    assert store.available()
    yong = store.get("永")
    assert yong is not None and len(yong.strokes) == 5
    assert yong.medians[0][0] == tuple(YONG["medians"][0][0])
    assert store.get("一") is not None
    assert store.get("字") is None
    store.remove()
    assert not store.available()


def test_download_rejects_bad_hash(tmp_path):
    src, _ = _fixture(tmp_path)
    dest = tmp_path / "db.sqlite3"
    try:
        st.download(url=src.as_uri(), sha256="0" * 64, dest=dest)
    except st.StrokeDataError:
        pass
    else:
        raise AssertionError("hash mismatch not detected")
    assert not dest.exists()
    assert [p.name for p in tmp_path.iterdir()] == ["graphics.txt"]


def test_default_store_uses_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert st.db_path() == tmp_path / "transsnip" / "zh-strokes.sqlite3"
    assert not st.StrokeStore().available()


def test_widget_animates_and_finishes(qapp):
    w = StrokeOrderWidget()
    w.resize(160, 160)
    w.set_char("永", _data())
    done = []
    w.finished.connect(lambda: done.append(True))
    w.play()
    assert w.is_playing()
    img = QImage(160, 160, QImage.Format.Format_ARGB32)
    for _ in range(2000):
        if done:
            break
        w.step(16)
        w.render(img)
    assert done == [True]
    assert not w.is_playing()
    w.render(img)


def test_widget_no_data_and_hide(qapp):
    w = StrokeOrderWidget()
    w.resize(160, 160)
    w.set_char("字", None)
    w.play()
    assert not w.is_playing()
    w.render(QImage(160, 160, QImage.Format.Format_ARGB32))
    assert w.heightForWidth(200) == 200
