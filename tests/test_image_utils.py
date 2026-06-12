"""frame_difference + text_similarity — the video-subtitle loop gates."""
from PIL import Image, ImageDraw

from transsnip.utils.image import frame_difference, text_similarity


def test_identical_frames_zero_diff():
    a = Image.new("RGB", (200, 60), "white")
    b = Image.new("RGB", (200, 60), "white")
    assert frame_difference(a, b) < 0.005


def test_changed_frame_high_diff():
    a = Image.new("RGB", (200, 60), "white")
    b = Image.new("RGB", (200, 60), "white")
    ImageDraw.Draw(b).rectangle([10, 10, 180, 50], fill="black")
    assert frame_difference(a, b) > 0.05


def test_text_similarity_identical():
    assert text_similarity("Hello world", "Hello world") == 1.0


def test_text_similarity_jitter_high():
    # One-character OCR jitter should still read as "same line".
    assert text_similarity("Hello world", "Hello worId") >= 0.85


def test_text_similarity_different_low():
    assert text_similarity("Hello world", "Bonjour le monde") < 0.6


def test_text_similarity_empty_both():
    assert text_similarity("", "") == 1.0
    assert text_similarity("a", "") == 0.0
