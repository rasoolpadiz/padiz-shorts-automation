# -*- coding: utf-8 -*-
"""
Diagnostic renderer: draws sample slides with the exact same code path used by the
publishing pipeline and prints the text-shaping environment, so that the rendering
can be verified on any machine (locally and on the GitHub Actions runner).

Usage:
    python render_check.py            # writes PNGs to ./render_check/
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont
import PIL

try:  # make sure Persian sample text is printable on cp1252 Windows consoles too
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pipeline
from topics_pool import FACTS_POOL

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "render_check")


def print_environment():
    print("=" * 60)
    print("Pillow version      :", PIL.__version__)
    print("libraqm available   :", pipeline.HAS_RAQM)
    print("raqm version        :", pipeline.pil_features.version("raqm"))
    print("harfbuzz available  :", pipeline.pil_features.check("harfbuzz"))
    print("fribidi available   :", pipeline.pil_features.check("fribidi"))
    print("text mode           :",
          "Pillow/Raqm shapes the text (no pre-processing)"
          if pipeline.HAS_RAQM else
          "arabic_reshaper + python-bidi pre-processing")
    print("=" * 60)


def print_sample_order(sample: str):
    """Show what is actually handed to Pillow (first characters, codepoints)."""
    prepared = pipeline.prepare_bidi_text(sample)
    print(f"raw      : {sample}")
    print("prepared : " + " ".join(f"{c}(U+{ord(c):04X})" for c in prepared[:12]))
    print()


def render_samples():
    os.makedirs(OUT_DIR, exist_ok=True)

    topic = FACTS_POOL[0]
    slides = topic["slides"]
    print(f"Topic: {topic['title']}  (category: {topic['category']})")
    print()

    for idx, slide in enumerate(slides, start=1):
        out_png = os.path.join(OUT_DIR, f"slide_{idx}.png")
        pipeline.create_slide_image(
            topic["category"], slide["title"], slide["text"], idx, len(slides), out_png
        )
        print(f"rendered -> {out_png}")

    print_sample_order(slides[0]["title"])
    print_sample_order(slides[0]["text"])
    print_sample_order(f"نکته 1 از {len(slides)}")

    # Extra samples that historically broke: ZWNJ, Persian digits, mixed Latin,
    # emoji (stripped because Vazirmatn has no emoji glyphs).
    mixed = os.path.join(OUT_DIR, "mixed_samples.png")
    width, height = 1080, 700
    img = Image.new("RGB", (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(pipeline.FONT_PATH, 46)
    samples = [
        "Padiz Studio | روان‌شناسی رابطه",
        "۳ راز شگفت‌انگیز که مغزت را منفجر می‌کند!",
        "نکته 1 از 3",
        "سلام دنیا 123 ABC",
    ]
    y = 60
    for sample in samples:
        pipeline.draw_persian(draw, (width // 2, y), sample, font, (241, 245, 249))
        y += 120
    img.save(mixed)
    print(f"rendered -> {mixed}")


if __name__ == "__main__":
    print_environment()
    render_samples()
    print("RENDER CHECK DONE (exit 0)")
    sys.exit(0)
