# -*- coding: utf-8 -*-
"""Typography system for Padiz Studio.

Owner directive (2026-09-30): "فونت‌ها خیلی به روز و شیک باشند" - fonts must look modern
and stylish. The old defaults (DejaVuSans / Arial Bold) looked dated, so display fonts
are now bundled under assets/fonts/ and used for hooks, titles and numbers, with a clean
humanist sans for body copy.

Fonts are committed to the repo so GitHub Actions renders pixel-identical to Windows.
Every lookup degrades gracefully to the previous fonts if a file is missing.
"""
import os
from functools import lru_cache

from PIL import ImageFont

import pipeline as P

FONT_DIR = os.path.join(P.BASE_DIR, "assets", "fonts")

# Display = punchy face for hooks/titles. Body = clean readable sans. Num = tabular.
_FILES = {
    # lang key -> (display, body, numeric)
    "en": (
        [("BebasNeue-Regular.ttf", None), ("Poppins-Black.ttf", None),
         ("Poppins-Bold.ttf", None)],
        [("Inter-Variable.ttf", 600), ("Poppins-Bold.ttf", None),
         ("Inter-Variable.ttf", 400)],
        [("Inter-Variable.ttf", 700), ("BebasNeue-Regular.ttf", None)],
    ),
    "fa": (
        [("Vazirmatn-Variable.ttf", 900), ("Vazirmatn-Variable.ttf", 800)],
        [("Vazirmatn-Variable.ttf", 500), ("Vazirmatn-Variable.ttf", 400)],
        [("Vazirmatn-Variable.ttf", 800)],
    ),
}

_FALLBACK = {
    "en": ["DejaVuSans-Bold.ttf", r"C:\Windows\Fonts\arialbd.ttf"],
    "fa": ["Vazirmatn-Bold.ttf", r"C:\Windows\Fonts\tahomabd.ttf"],
}


def _is_fa(text):
    try:
        return P.is_fa_text(text)
    except Exception:
        return False


def _exists(name):
    return os.path.exists(os.path.join(FONT_DIR, name))


@lru_cache(maxsize=512)
def _resized(name, size, variation):
    """Load a bundled font at `size`, pinning every variation axis to `variation`."""
    font = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    if variation is not None:
        try:
            values = []
            for axis in font.get_variation_axes():
                lo, hi = axis.get("minimum", 0), axis.get("maximum", 1000)
                values.append(max(lo, min(hi, variation)))
            font.set_variation_by_axes(values)
        except Exception:
            pass
    return font


@lru_cache(maxsize=512)
def font(size, kind="body", text=""):
    """Return a PIL font. kind: display | body | num. Language follows `text` (fa/en)."""
    lang = "fa" if _is_fa(text) else "en"
    for name, variation in _FILES[lang][{"display": 0, "body": 1, "num": 2}[kind]]:
        if _exists(name):
            try:
                return _resized(name, size, variation)
            except Exception as e:  # pragma: no cover - defensive
                print(f"[fonts] could not load {name}: {e}")
    # Fall back to whatever the pipeline used before.
    return P.font_for(text or "x", size)


def display(size, text=""):
    return font(size, "display", text)


def body(size, text=""):
    return font(size, "body", text)


def number(size, text="1"):
    return font(size, "num", text)
