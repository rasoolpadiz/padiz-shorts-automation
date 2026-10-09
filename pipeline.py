import os
import sys
import json
import asyncio
import shutil
import subprocess
import pickle
import re
import tempfile
from PIL import Image, ImageDraw, ImageFont
from PIL import features as pil_features
import arabic_reshaper
from bidi.algorithm import get_display
import edge_tts
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GENAI = True

    # The SDK logs a "direct use of automatic function calling is not recommended"
    # warning for plain generate_content calls even though we never register tools;
    # raise the level so the automation logs stay readable.
    import logging
    logging.getLogger("google_genai.models").setLevel(logging.ERROR)
except ImportError:
    genai = None
    genai_types = None
    HAS_GENAI = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(BASE_DIR, "Vazirmatn-Bold.ttf")
FONT_EN_CANDIDATES = [
    os.path.join(BASE_DIR, "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "C:\\Windows\\Fonts\\Arial.ttf",
]
FONT_EN_PATH = next((p for p in FONT_EN_CANDIDATES if os.path.exists(p)), FONT_PATH)
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")

FA_CHAR_RE = re.compile(r'[\u0600-\u06FF]')


def is_fa_text(text: str) -> bool:
    return bool(FA_CHAR_RE.search(text or ""))


def font_for(text: str, size: int):
    """Latin font for English, Vazirmatn for Persian."""
    path = FONT_PATH if is_fa_text(text) else FONT_EN_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.truetype(FONT_PATH, size)


def draw_smart(draw, xy, text: str, font, fill, anchor: str = "mm", max_width: int = None):
    """RTL shaping for Persian, plain LTR for English.

    SIDE_PAD=90: x is clamped so centre-anchored text can never be cut off
    at the left/right edges (canvas width inferred as 2*x for mm anchors).
    When max_width is given and the line is too wide, it is truncated with
    an ellipsis instead of overflowing.
    """
    SIDE_PAD = 90
    x, y = xy
    try:
        canvas_w = draw.im.size[0] if hasattr(draw, "im") else 1080
    except Exception:
        canvas_w = 1080
    if anchor.endswith("m") or anchor.endswith("a"):
        # centre/middle anchors: keep centre inside the safe zone
        lo = SIDE_PAD if "m" in anchor or "a" in anchor else SIDE_PAD
        x = max(lo, min(canvas_w - SIDE_PAD, x))
    if is_fa_text(text):
        if max_width is not None:
            text = _fit_line(draw, text, font, max_width)
        draw_persian(draw, (x, y), text, font, fill, anchor=anchor)
    else:
        clean = re.sub(r'[\U00010000-\U0010ffff]', '', text or '').strip()
        if max_width is not None:
            clean = _fit_line(draw, clean, font, max_width)
        draw.text((x, y), clean, font=font, fill=fill, anchor=anchor)

# Pillow builds that ship libraqm already run HarfBuzz (letter joining) and
# FriBidi (right-to-left reordering) internally, so feeding them text that was
# pre-processed by arabic_reshaper + python-bidi applies BOTH steps twice and the
# Persian text comes out mirrored/reversed. Builds without libraqm (most local
# Windows installs) cannot shape at all and *require* that pre-processing.
# The GitHub Actions runner (ubuntu-latest + pip wheel) DOES have libraqm, the
# local machine does not, so the decision must be made at runtime.
HAS_RAQM = bool(pil_features.check("raqm"))

def prepare_bidi_text(text: str) -> str:
    """Return text in the form Pillow can draw correctly on THIS build."""
    cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    cleaned = cleaned.replace('\u0643', 'ک').replace('\u064a', 'ی').replace('\u0649', 'ی')
    cleaned = cleaned.strip()

    if HAS_RAQM:
        # Let Pillow/Raqm do the joining + bidi reordering itself.
        return cleaned

    reshaped = arabic_reshaper.reshape(cleaned)
    return get_display(reshaped)

def draw_persian(draw, xy, text: str, font, fill, anchor: str = "mm"):
    """Draw a Persian string correctly regardless of the Pillow build in use."""
    kwargs = {"font": font, "fill": fill, "anchor": anchor}
    if HAS_RAQM:
        # Explicit RTL paragraph direction so mixed lines (Persian + Latin)
        # are always laid out from right to left.
        kwargs["direction"] = "rtl"
        kwargs["language"] = "fa"
    draw.text(xy, prepare_bidi_text(text), **kwargs)

# --- Measured wrap / fit helpers (same idea as longform._wrap_to_width) ----
def _measure(draw, s, font):
    try:
        return draw.textlength(s, font=font)
    except Exception:
        return float(len(s or "") * getattr(font, "size", 40) * 0.6)


def _fit_line(draw, s, font, max_width):
    """Truncate one line with ellipsis so it fits max_width (measured)."""
    if _measure(draw, s, font) <= max_width:
        return s
    ell = " ..."
    while s and _measure(draw, s + ell, font) > max_width:
        s = s[:-1].rstrip()
    return (s + ell) if s else ell.strip()


def _wrap_to_width(draw, text, font, max_width, max_lines=4):
    """Real measured word-wrap (char-count wrapping clipped Persian)."""
    words = (text or "").split()
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if _measure(draw, trial, font) <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(" ".join(cur))
    if len(lines) == max_lines and len(words) > sum(len(l.split()) for l in lines):
        lines[-1] = _fit_line(draw, lines[-1], font, max_width)
    return lines


# --- Mood palettes for SHORTS (mirrors longform._MOOD_PALETTES) ------------
_SHORTS_MOODS = {
    "money":   {"accent": (240, 180, 41),  "topbar": (198, 138, 20)},
    "mystery": {"accent": (168, 85, 247),  "topbar": (126, 58, 196)},
    "science": {"accent": (56, 189, 248),   "topbar": (14, 116, 190)},
    "history": {"accent": (214, 158, 84),  "topbar": (154, 103, 46)},
    "dark":    {"accent": (220, 38, 38),   "topbar": (153, 27, 27)},
    "nature":  {"accent": (52, 211, 153),   "topbar": (5, 150, 105)},
}
_SHORTS_MOOD_WORDS = {
    "money": ["money", "finance", "invest", "wealth", "econom", "business", "crypto",
              "startup", "entrepreneur", "ثروت", "پول", "مالی", "سرمایه", "اقتصاد", "کسب"],
    "mystery": ["mystery", "unsolved", "conspiracy", "crime", "horror", "secret",
                "vanished", "enigma", "occult", "راز", "معما", "جنایت", "ترسناک", "مخوف"],
    "science": ["science", "space", "ai", "tech", "robot", "medical", "physics", "future",
                "software", "cyber", "علم", "فضا", "هوش", "تکنولوژی", "ربات", "مغز", "دانشمند"],
    "history": ["history", "ancient", "civilization", "archaeolog", "empire", "medieval",
                "heritage", "تاریخ", "باستان", "تمدن", "امپراتور", "جنگ", "ایران"],
    "dark": ["dark", "war", "death", "danger", "killer", "مرگ", "جنگ", "خطر", "قتل", "تاریک"],
    "nature": ["nature", "animal", "food", "health", "fitness", "earth", "ocean", "climate",
               "طبیعت", "حیوان", "سلامت", "غذا", "اقیانوس", "زمین"],
}


def detect_shorts_mood(category: str, title: str = "", text: str = "") -> str:
    hay = f"{category or ''} {title or ''} {text or ''}".lower()
    for mood, words in _SHORTS_MOOD_WORDS.items():
        if any(w in hay for w in words):
            return mood
    return "science"

def create_slide_image(category: str, title: str, text: str, slide_num: int, total_slides: int, output_path: str, lang: str = None):
    # Theme per language: FA keeps the EXACT legacy look, EN gets its own
    # identity so viewers instantly tell them apart on the channel grid.
    lang_pinned = (lang or "").strip().lower()
    if lang_pinned.startswith("en"):
        en_mode = True
    elif lang_pinned.startswith("fa"):
        en_mode = False
    else:
        en_mode = not is_fa_text(f"{title} {text}")

    if en_mode:
        # EN identity: deep ocean-teal + cyan accent (vs FA navy + gold/red).
        THEME = {
            "bg": (4, 26, 34),
            "topbar": (34, 211, 238),
            "card_fill": (8, 47, 60),
            "card_outline": (14, 116, 144),
            "title": (103, 232, 249),
            "divider": (21, 100, 120),
            "body": (236, 253, 255),
            "badge": (125, 211, 252),
            "progress": (125, 211, 252),
            "btn": (6, 182, 212),
            "btn_text": (255, 255, 255),
        }
    else:
        # FA legacy theme - DO NOT TOUCH (Persian look stays pixel-identical).
        THEME = {
            "bg": (15, 23, 42),
            "topbar": (239, 68, 68),
            "card_fill": (30, 41, 59),
            "card_outline": (51, 65, 85),
            "title": (250, 204, 21),
            "divider": (71, 85, 105),
            "body": (241, 245, 249),
            "badge": (148, 163, 184),
            "progress": (148, 163, 184),
            "btn": (220, 38, 38),
            "btn_text": (255, 255, 255),
        }

    mood = detect_shorts_mood(category, title, text)
    _mood = _SHORTS_MOODS.get(mood, _SHORTS_MOODS["science"])
    # Mood varies ONLY the accent/topbar/title: FA keeps navy bg + gold title
    # base, EN keeps teal bg base. Mood tints the topbar + divider + progress
    # so every niche feels different without losing language identity.
    THEME["topbar"] = _mood["topbar"]
    THEME["progress"] = _mood["accent"]
    THEME["divider"] = _mood["accent"]
    THEME["_mood"] = mood

    width, height = 1080, 1920
    img = Image.new("RGB", (width, height), color=THEME["bg"])
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (width, 24)], fill=THEME["topbar"])

    badge_label = f"{category} | Padiz Studio" if category else "Padiz Studio"
    badge_font = font_for(badge_label, 38)
    draw_smart(draw, (width // 2, 220), badge_label, badge_font, THEME["badge"])

    card_margin = 70
    card_top = 400
    card_bottom = 1500
    draw.rounded_rectangle([(card_margin, card_top), (width - card_margin, card_bottom)], radius=40, fill=THEME["card_fill"], outline=THEME["card_outline"], width=4)

    SAFE_W = width - 90 * 2  # 90px side padding: nothing may touch the edges

    title_font = font_for(title, 64)
    # Auto-shrink the title until it fits (measured, not char-counted),
    # then wrap to max 2 lines like longform.
    while title_font.size > 40 and _measure(
            ImageDraw.Draw(Image.new("RGB", (8, 8))), title, title_font) > SAFE_W * 2:
        title_font = font_for(title, title_font.size - 4)
    title_lines = _wrap_to_width(draw, title, title_font, SAFE_W, max_lines=2)
    ty = card_top + 100
    for tl in title_lines:
        draw_smart(draw, (width // 2, ty), tl, title_font, THEME["title"],
                   max_width=SAFE_W)
        ty += int(title_font.size * 1.25)

    draw.line([(card_margin + 60, card_top + 210), (width - card_margin - 60, card_top + 210)], fill=THEME["divider"], width=2)

    content_font = font_for(text, 46)
    body_lines = _wrap_to_width(draw, text, content_font, SAFE_W, max_lines=3)
    # Auto-shrink body if 3 lines still overflow vertically.
    while len(body_lines) >= 3 and content_font.size > 34:
        probe = _wrap_to_width(draw, text, font_for(text, content_font.size - 4),
                               SAFE_W, max_lines=3)
        if sum(1 for _ in probe) < 4:
            content_font = font_for(text, content_font.size - 4)
            body_lines = probe
            if len(body_lines) <= 3:
                break
        else:
            break
        if content_font.size <= 34:
            break
    lines = body_lines

    line_height = 80
    total_h = len(lines) * line_height
    start_y = card_top + 340 + ((card_bottom - card_top - 420 - total_h) // 2)

    for i, line in enumerate(lines):
        y = start_y + (i * line_height)
        draw_smart(draw, (width // 2, y), line, content_font, THEME["body"],
                   max_width=SAFE_W)

    # Mood accent bar under the body block (shorts "designed detail").
    bar_w = min(int(max((_measure(draw, l, content_font) for l in lines),
                        default=0)) + 60, SAFE_W)
    draw.rounded_rectangle(
        [(width / 2 - bar_w / 2, start_y + len(lines) * line_height + 18),
         (width / 2 + bar_w / 2, start_y + len(lines) * line_height + 30)],
        radius=6, fill=THEME["divider"])

    progress_font = font_for("test", 34)
    sub_font = font_for("Subscribe", 42)
    draw.rounded_rectangle([(140, 1620), (width - 140, 1740)], radius=30, fill=THEME["btn"])
    sub_txt = "SUBSCRIBE for daily videos" if en_mode else 'کانال رو SUBSCRIBE کنید'
    draw_smart(draw, (width // 2, 1680), sub_txt, sub_font, THEME["btn_text"])
    progress_txt = f"Fact {slide_num} of {total_slides}" if en_mode else f"نکته {slide_num} از {total_slides}"
    draw_smart(draw, (width // 2, card_bottom - 70), progress_txt, progress_font, THEME["progress"])

    img.save(output_path, quality=95)
    return output_path


def create_shorts_thumbnail(topic: dict, out_path: str) -> str:
    """1080x1920 Shorts cover: hard scrim + 2-4 word display hook + accent bar.

    Mirrors longform.create_thumbnail language at vertical aspect so the
    Shorts shelf cover matches the video design.
    """
    try:
        import fonts as F
    except Exception:
        F = None
    W, H = 1080, 1920
    lang = (topic.get("lang") or ("en" if not is_fa_text(
        str(topic.get("title", ""))) else "fa")).lower()
    mood = detect_shorts_mood(str(topic.get("category", "")),
                              str(topic.get("title", "")))
    accent = _SHORTS_MOODS.get(mood, _SHORTS_MOODS["science"])["accent"]
    base_bg = (4, 26, 34) if lang.startswith("en") else (15, 23, 42)
    img = Image.new("RGB", (W, H), color=base_bg)
    draw = ImageDraw.Draw(img, "RGBA")
    # Hard scrim: dark bottom 2/3 where the hook sits.
    for y in range(H):
        t = y / max(H - 1, 1)
        a = int(40 + (215 - 40) * (t ** 1.6))
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, min(225, a)))
    # Mood topbar + accent bar identity.
    draw.rectangle([(0, 0), (W, 26)],
                   fill=_SHORTS_MOODS.get(mood)["topbar"])
    hook = str(topic.get("thumbnail_text") or topic.get("title", "") or "")
    hook = re.sub(r"#shorts", "", hook, flags=re.I).strip()
    words = hook.split()
    if len(words) > 4:
        hook = " ".join(words[:4])
    SAFE_W = W - 180
    size, lines, font = 150, [hook], None
    while size >= 120:
        f = (F.display(size, hook) if F else font_for(hook, size))
        trial = _wrap_to_width(draw, hook, f, SAFE_W, max_lines=3)
        widest = max((_measure(draw, l, f) for l in trial), default=0)
        if len(trial) <= 3 and widest <= SAFE_W:
            lines, font, size_used = trial, f, size
            break
        size -= 6
    else:
        font = (F.display(120, hook) if F else font_for(hook, 120))
        lines = _wrap_to_width(draw, hook, font, SAFE_W, max_lines=3)
        size_used = 120
    line_h = int(size_used * 1.16)
    y0 = (H - line_h * len(lines)) // 2
    for i, line in enumerate(lines):
        yy = y0 + i * line_h
        # hard shadow for readability at small sizes
        try:
            draw.text((W / 2 + 7, yy + 7), line, font=font,
                      fill=(0, 0, 0, 220), anchor="ma")
        except Exception:
            pass
        draw_smart(draw, (W / 2, yy), line, font, (255, 255, 255),
                   anchor="ma", max_width=SAFE_W)
    bar_y = y0 + len(lines) * line_h + 24
    bar_w = min(int(max((_measure(draw, l, font) for l in lines),
                        default=0)) + 60, SAFE_W)
    draw.rounded_rectangle([(W / 2 - bar_w / 2, bar_y),
                            (W / 2 + bar_w / 2, bar_y + 14)],
                           radius=7, fill=accent)
    bf = (F.display(40, "Padiz") if F else font_for("Padiz", 40))
    draw_smart(draw, (W / 2, H - 140), "PADIZ STUDIO", bf,
               (255, 255, 255))
    img.save(out_path, quality=95)
    return out_path

async def generate_voice_edge(text: str, voice: str, output_path: str):
    """Fallback narration using edge-tts.

    A fast rate plus unpunctuated text is what makes a synthetic voice sound
    robotic, so we slow the delivery down and let sentence punctuation create
    real breaths instead of a flat wall of words.
    """
    fa = not is_fa_text(text)
    # Persian is vowel-heavy and needs a slower cadence to sound unhurried.
    rate = "+0%" if fa else "-8%"
    pitch = "+0Hz" if fa else "-2Hz"
    body = _add_natural_pauses(text)
    communicator = edge_tts.Communicate(body, voice, rate=rate, pitch=pitch)
    await communicator.save(output_path)


def _add_natural_pauses(text: str) -> str:
    """Give the TTS engine real breathing room without changing the wording.

    Full stops already produce a pause, so we only add commas to the interior of
    very long sentences - that is where a real narrator would take a breath.
    """
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t:
        return t
    comma = "،" if is_fa_text(t) else ","
    out = []
    for part in re.split(r"(?<=[.!?؟])\s+", t):
        words = part.split()
        if len(words) > 26:
            # Break on the comma closest to the middle, else mid-phrase.
            target = len(words) // 2
            commas = [i for i, w in enumerate(words[:-1]) if w.endswith(comma) or w.endswith(",")]
            cut = min(commas, key=lambda i: abs(i - target)) if commas else target
            cut = max(8, min(cut, len(words) - 8))
            head = " ".join(words[:cut]).rstrip(",، ")
            out.append(head + comma + " ")
            out.append(" ".join(words[cut:]).lstrip(",، "))
        else:
            out.append(part)
    joined = re.sub(r"([.!?؟])\s*[,،]\s*", r"\1 ", " ".join(out))
    return re.sub(r"[,،]\s*[,،]", comma, re.sub(r"\s{2,}", " ", joined))

# Gemini reads whatever text it is given out loud, so the narration must be sent
# verbatim (wrapping it in "read this aloud: ..." can make the instruction end up
# in the audio). Delivery is steered with the speech style metadata instead.
GEMINI_STYLE_FA = (
    "Native Iranian Persian (Farsi) narration for a long-form documentary video. "
    "You are an educated, thoughtful Iranian man in his 30s, passionate about this topic, "
    "speaking warmly and naturally to a close friend over tea. Your voice should be: "
    "\n"
    "- Warm and genuine, never robotic or staged - like you're sharing real wisdom"
    "- Conversational with natural cadence, actual Tehrani Persian accent"
    "- Vary your delivery: let important facts drop your tone, curiosities lift your pitch"
    "- Take real human pauses (0.3-0.5s) where you'd breathe between thoughts"
    "- Emphasize key phrases with natural vocal color, not artificial stress"
    "- Speed up slightly on lists to sound engaged, slow down on profound insights"
    "- Use vocal filler occasionally ('خب', 'ببین') to sound human, not perfect"
    "- Never sound like textbook Persian, advertisement, or AI voice synthesis"
    "- Pronounce every Persian word with authentic Tehran dialect, no Arabic/English accent"
    "- Let numbers and names flow naturally as if you say them daily"
)

GEMINI_STYLE_EN = (
    "Natural, authentic American English narration for educational content. "
    "You are a curious, intelligent person explaining something you genuinely care about "
    "to someone you respect. Your voice should be: "
    "\n"
    "- Warm, human, conversational - never over-enthusiastic or sales-pitchy"
    "- Authentic American accent with natural regional characteristics"
    "- Vary your tone dramatically: whisper on intrigue, firm on authority, lift on discovery"
    "- Take real human pauses (0.2-0.4s) where a real person would breathe"
    "- Emphasize key insights with vocal color and intention, not artificial stress"
    "- Speed up on lists and build-ups, slow down for profound moments"
    "- Let your voice crack slightly with emotion on powerful ideas"
    "- Use authentic filler words ('so', 'really', 'honestly') to sound human"
    "- Never sound like a voiceover artist, podcast host, or AI synthesis"
    "- Pronounce every word with clear American diction, no artificial accent"
    "- Sound like you've lived the experiences you're describing"
)

# Dedicated TTS models first (most natural Persian delivery), then general models
# that also accept the AUDIO response modality. The first model that answers wins;
# unsupported ones raise and are skipped. Override with GEMINI_TTS_MODEL.
#
# For non-TTS (script generation), use the latest available models that support
# content generation. Older models are deprecated, so we try newest first.
# Verified live 2026-10-09 (GET /v1beta/models + generateContent/TTS probes):
# TTS OK: gemini-2.5-flash-preview-tts (127KB), gemini-3.8-flash-tts present.
# gemini-2.0-flash is DEAD (404) and is removed from both lists.
GEMINI_TTS_MODELS = [
    os.environ.get("GEMINI_TTS_MODEL", "").strip(),
    "gemini-3.8-flash-tts",             # newest free-tier TTS, best fidelity
    "gemini-2.5-flash-preview-tts",     # stable free-tier TTS (verified OK)
]

GEMINI_CONTENT_MODELS = [
    os.environ.get("GEMINI_CONTENT_MODEL", "").strip(),
    "gemini-3.8-flash",                 # verified OK 2026-10-09 (200) - PRIMARY
    "gemini-flash-latest",              # stable alias, always current
    # NOTE: gemini-2.5-flash / gemini-2.0-flash return 404 for new API keys
    # ("no longer available to new users"), so they are NOT listed as fallbacks.
]

# Male voice for Farid-style slides, female voice for Dilara-style slides.
# Persian narration uses Gemini voices that render Farsi most naturally; English
# uses the classic upbeat pair. Override the Persian ones with GEMINI_FA_VOICE.
GEMINI_FA_VOICE = os.environ.get("GEMINI_FA_VOICE", "").strip() or "Orus"
GEMINI_FA_VOICE_ALT = os.environ.get("GEMINI_FA_VOICE_ALT", "").strip() or "Orus"
GEMINI_VOICE_BY_EDGE = {
    "fa-IR-FaridNeural": GEMINI_FA_VOICE,
    "fa-IR-DilaraNeural": GEMINI_FA_VOICE_ALT,
    "en-US-GuyNeural": "Puck",
    "en-US-JennyNeural": "Kore",
    "en-US-AriaNeural": "Kore",
}
GEMINI_DEFAULT_VOICE = os.environ.get("GEMINI_TTS_VOICE", "").strip() or "Puck"

# Edge voices: Persian default + English (kept separate so FA stays untouched).
VOICES_FA = ["fa-IR-FaridNeural", "fa-IR-DilaraNeural"]
VOICES_EN = ["en-US-GuyNeural", "en-US-JennyNeural"]
VOICES = VOICES_FA  # legacy alias


def voices_for(topic_data: dict) -> list:
    lang = (topic_data.get("lang") or ("en" if not is_fa_text(
        (topic_data.get("title") or "") + " " + str(
            (topic_data.get("slides") or [{}])[0].get("speech", ""))) else "fa")).lower()
    if lang.startswith("en"):
        return VOICES_EN
    return VOICES_FA

R_PH = None

def _text_w(draw, s, font):
    try:
        l, t, r, b = draw.textbbox((0, 0), s, font=font)
        return r - l
    except Exception:
        return int(len(s or "") * font.size * 0.6)

def draw_cta_pill(draw, W, H, is_en):
    if is_en:
        cta = "SUBSCRIBE for daily videos"
        font = font_for("test", 40)
        pad_x, pill_h = 46, 84
        tw = _text_w(draw, cta, font)
        pill_w = tw + pad_x * 2 + 26
        x0 = (W - pill_w) // 2
        y0 = H - 175
        draw.rounded_rectangle([x0, y0, x0 + pill_w, y0 + pill_h], radius=pill_h // 2, fill=(18, 18, 22, 235), outline=(255, 255, 255, 70), width=2)
        dcy = y0 + pill_h // 2
        draw.ellipse([x0 + pad_x - 9, dcy - 9, x0 + pad_x + 9, dcy + 9], fill=(255, 45, 85, 255))
        draw.text((x0 + pill_w // 2 + 10, y0 + pill_h // 2 - 2), cta, font=font, fill=(255, 255, 255, 255), anchor="mm")
        return
    txt = 'کانال رو SUBSCRIBE کنید'
    font = font_for(txt, 40)
    tw = _text_w(draw, __import__("pipeline").prepare_bidi_text(txt) if False else txt, font)
    pad_x, pill_h = 44, 86
    pill_w = tw + pad_x * 2 + 52
    if pill_w > W - 120:
        pill_w = W - 120
    x0 = (W - pill_w) // 2
    y0 = H - 178
    cy = y0 + pill_h // 2
    draw.rounded_rectangle([x0, y0, x0 + pill_w, y0 + pill_h], radius=pill_h // 2, fill=(16, 16, 22, 235), outline=(255, 255, 255, 70), width=2)
    draw.ellipse([x0 + pad_x // 2 - 1, cy - 9, x0 + pad_x // 2 + 17, cy + 9], fill=(255, 45, 85, 255))
    draw_persian(draw, (x0 + pill_w // 2, cy - 2), txt, font, (255, 255, 255, 255), anchor="mm")

def draw_insta_pill(draw, W, H):
    handle = "@padiz.studio"
    font = font_for("test", 32)
    pad_x, pill_h = 34, 62
    tw = _text_w(draw, handle, font)
    pill_w = tw + pad_x * 2
    x0 = (W - pill_w) // 2
    y0 = H - 84
    draw.rounded_rectangle([x0, y0, x0 + pill_w, y0 + pill_h],
                           radius=pill_h // 2, fill=(16, 16, 22, 200))
    draw.text((x0 + pill_w // 2, y0 + pill_h // 2 - 1), handle,
              font=font, fill=(200, 200, 210, 255), anchor="mm")


# Once every model has failed inside one process there is no point paying the
# network round-trips again for the next slide, so Gemini is switched off for
# the rest of the run and edge-tts handles the remaining lines.
_gemini_voice_disabled = False

# Errors that mean "this key/account can never work" - retrying other models or
# later slides would only waste time.
FATAL_GEMINI_ERROR_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "api key expired",
    "unauthenticated",
    "permission_denied",
    "permission denied",
)

# Errors that mean "quota is gone for now" - one process must not produce a
# video narrated half by Gemini and half by edge-tts, so the first quota hit
# switches the whole run to the fallback voice.
QUOTA_GEMINI_ERROR_MARKERS = (
    "quota",
    "resource_exhausted",
    "resource exhausted",
    "rate_limit",
    "rate limit",
    "generate_content_free_tier",
    "429",
)


# Owner directive (2026-10-03): Persian narration must NEVER use edge-tts.
# Edge-tts Persian sounds robotic and often unintelligible, so a Persian video
# with no Gemini voice is worse than no video at all. When the narration text
# is Persian and Gemini TTS is unavailable, the pipeline refuses to render and
# fails loudly instead of publishing a robotic video. English keeps the
# edge-tts fallback (it sounds acceptable there).
# Escape hatch: set FA_ALLOW_EDGE_VOICE=1 to re-enable the fallback.
_FA_VOICE_STRICT = os.environ.get("FA_ALLOW_EDGE_VOICE", "").strip().lower() not in ("1", "true", "yes", "on")


def _refuse_robotic_fa(text: str):
    """Raise for Persian text when Gemini TTS is unavailable. No-op otherwise."""
    if _FA_VOICE_STRICT and is_fa_text(text):
        raise RuntimeError(
            "Gemini TTS unavailable for Persian text - refusing edge-tts "
            "fallback (robotic/unintelligible). Set FA_ALLOW_EDGE_VOICE=1 to override."
        )


def gemini_voice_enabled() -> bool:
    """Gemini narration is used unless it is switched off by env or a prior failure."""
    if _gemini_voice_disabled:
        return False
    return os.environ.get("DISABLE_GEMINI_VOICE", "").strip().lower() not in ("1", "true", "yes", "on")


def _is_fatal_gemini_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in FATAL_GEMINI_ERROR_MARKERS)


def _is_quota_gemini_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in QUOTA_GEMINI_ERROR_MARKERS)


def _disable_gemini_voice():
    """Switch narration to edge-tts for the rest of this process."""
    global _gemini_voice_disabled
    _gemini_voice_disabled = True


def gemini_voice_for(edge_voice: str) -> str:
    """Map an edge-tts voice name onto a compatible Gemini prebuilt voice."""
    if os.environ.get("GEMINI_TTS_VOICE", "").strip():
        return GEMINI_DEFAULT_VOICE
    return GEMINI_VOICE_BY_EDGE.get(edge_voice, GEMINI_DEFAULT_VOICE)


def gemini_speech_config(model_name: str, voice_name: str):
    """Build the speech config for a model.

    Newer (gemini-3.x) models document ``voice_config.voice`` while older ones use
    the nested ``prebuilt_voice_config``; the installed SDK accepts both.
    """
    if model_name.startswith("gemini-3"):
        voice_config = genai_types.VoiceConfig(voice=voice_name)
    else:
        voice_config = genai_types.VoiceConfig(
            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=voice_name)
        )
    return genai_types.SpeechConfig(voice_config=voice_config)


def _gemini_audio_to_mp3(raw_audio: bytes, output_path: str) -> bool:
    """Write raw Gemini audio (WAV container or raw 24 kHz PCM) out as an MP3."""
    is_wav = raw_audio[:4] == b"RIFF" and b"WAVE" in raw_audio[:16]

    with tempfile.NamedTemporaryFile(suffix=".wav" if is_wav else ".pcm", delete=False) as tf:
        tf.write(raw_audio)
        temp_audio_file = tf.name

    try:
        if is_wav:
            # The WAV container already carries its own sample format.
            ffmpeg_cmd = ["ffmpeg", "-y", "-i", temp_audio_file]
        else:
            # Raw PCM: 16-bit little-endian mono @ 24 kHz (Gemini L16 default).
            ffmpeg_cmd = ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                          "-i", temp_audio_file]

        ffmpeg_cmd += ["-c:a", "libmp3lame", "-b:a", "192k", output_path]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    finally:
        if os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
            except OSError:
                pass


def generate_voice_gemini(text: str, output_path: str, voice_name: str = None) -> bool:
    """Generate natural Persian narration using Google AI Studio (Gemini audio output).

    Returns True when an MP3 was written to ``output_path``, and False when Gemini
    is unavailable (no API key / SDK missing) or produced nothing usable, so the
    caller can fall back to edge-tts.
    """
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key or not HAS_GENAI or not gemini_voice_enabled():
        return False

    voice_name = voice_name or GEMINI_DEFAULT_VOICE
    client = genai.Client(api_key=api_key)
    style = GEMINI_STYLE_EN if not is_fa_text(text) else GEMINI_STYLE_FA

    # Styled part first (steers delivery), then the bare text as a safety net for
    # models/SDK versions that reject the style metadata.
    contents_variants = [
        [
            genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part(
                        text=text,
                        speech_metadata=genai_types.SpeechMetadata(style=style),
                    )
                ],
            )
        ],
        text,
    ]

    def attempt(model_name, speech_config, contents):
        """Run one request; returns raw audio bytes, or None when unusable."""
        config = genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
        )
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )
        for candidate in (response.candidates or []):
            if not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    return inline.data
        return None

    quota_hit = False
    for model_name in [m for m in GEMINI_TTS_MODELS if m]:
        speech_config = gemini_speech_config(model_name, voice_name)
        for variant_index, contents in enumerate(contents_variants):
            try:
                raw_audio = attempt(model_name, speech_config, contents)
            except Exception as e:
                print(f"[Gemini TTS] {model_name} variant {variant_index} failed: {e}")
                if _is_quota_gemini_error(e):
                    # Daily quota of THIS model is gone - other models still
                    # have their own free quota, so keep trying them. Gemini
                    # is only switched off when nothing is left at all.
                    quota_hit = True
                    break                     # same quota for both variants
                if _is_fatal_gemini_error(e):
                    print("[Gemini TTS] API key rejected - using edge-tts for this run.")
                    _disable_gemini_voice()
                    return False
                continue

            if not raw_audio:
                continue

            if _gemini_audio_to_mp3(raw_audio, output_path):
                print(f"[Gemini TTS] {model_name} (voice={voice_name}) -> {output_path}")
                return True
            print(f"[Gemini TTS] {model_name} returned audio FFmpeg could not convert.")

    # No model produced audio: stop trying for the remaining slides of this run.
    if quota_hit:
        print("[Gemini TTS] all model quotas exhausted - using edge-tts for this run.")
    else:
        print("[Gemini TTS] No Gemini model returned audio - using edge-tts for this run.")
    _disable_gemini_voice()
    return False


def generate_voice(text: str, voice: str, output_path: str):
    """Narrate ``text`` into ``output_path`` as an MP3.

    Tries Google AI Studio (Gemini) audio generation first for natural Persian
    speech, and falls back to edge-tts whenever that is unavailable or fails.
    Every failure (not just a rejected key) disables Gemini for the rest of the
    process, so one video is never narrated half by one engine and half by
    the other - with the free TTS quota this small, partial runs are the norm,
    not the exception.
    """
    try:
        gemini_voice = gemini_voice_for(voice)
        if generate_voice_gemini(text, output_path, voice_name=gemini_voice):
            print(f"[voice] Generated with Google AI Studio (Gemini voice: {gemini_voice})")
            return
        print("[voice] Gemini voice unavailable -> falling back to edge-tts.")
    except Exception as e:
        print(f"[voice] Gemini voice error ({e}) -> falling back to edge-tts.")

    # Persian strict mode: a robotic edge-tts Persian video is worse than none.
    if is_fa_text(text):
        _refuse_robotic_fa(text)

    asyncio.run(generate_voice_edge(text, voice, output_path))

def _detect_silences(audio_path: str, noise_db: int = -35, min_dur: float = 0.25):
    """Return [(start, end)] silence spans reported by ffmpeg silencedetect."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", audio_path,
           "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    spans, start = [], None
    for line in (res.stderr or "").splitlines():
        if "silence_start:" in line:
            try:
                start = float(line.split("silence_start:")[1].strip().split()[0])
            except (IndexError, ValueError):
                start = None
        elif "silence_end:" in line and start is not None:
            try:
                end = float(line.split("silence_end:")[1].strip().split()[0])
            except (IndexError, ValueError):
                continue
            spans.append((start, end))
            start = None
    return spans


def split_audio_by_silence(audio_path: str, parts: int, out_paths: list, weights: list = None) -> bool:
    """Cut one narration track into `parts` clips at pauses.

    `weights` = relative size of each part (e.g. character counts of the source
    texts). Cut points are then chosen near the *expected* boundaries instead of
    simply taking the longest pauses, which often land mid-scene and silently
    desync narration from slides.
    """
    if parts <= 1:
        shutil.copy2(audio_path, out_paths[0])
        return True

    spans = [s for s in _detect_silences(audio_path) if s[1] - s[0] >= 0.18]
    if len(spans) < parts - 1:
        return False

    total = get_audio_duration(audio_path)
    mids = sorted((s[0] + s[1]) / 2.0 for s in spans)

    if weights and len(weights) >= parts and sum(weights[:parts]) > 0:
        w = [max(float(x), 1.0) for x in weights[:parts]]
        w_sum = sum(w)
        targets, acc = [], 0.0
        for x in w[:-1]:
            acc += x
            targets.append(total * acc / w_sum)
    else:
        # Fallback: longest pauses, evenly ranked.
        ranked = sorted(spans, key=lambda s: (s[1] - s[0]), reverse=True)[: parts - 1]
        targets = sorted((s[0] + s[1]) / 2.0 for s in ranked)

    # Greedy nearest-silence per target, keeping cuts ordered and sane.
    cuts, prev = [], 0.0
    for i, target in enumerate(targets):
        remaining = parts - 1 - i          # cuts still needed after this one
        lo = prev + 1.0
        hi = total - (remaining + 1) * 1.0
        candidates = [m for m in mids if lo <= m <= hi]
        if not candidates:
            return False
        cut = min(candidates, key=lambda m: abs(m - target))
        cuts.append(cut)
        prev = cut

    bounds = [0.0] + cuts + [total]
    try:
        for i in range(parts):
            start, end = bounds[i], bounds[i + 1]
            if end - start < 0.8:
                return False
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                 "-i", audio_path, "-c:a", "libmp3lame", "-b:a", "192k", out_paths[i]],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    return all(os.path.exists(p) and os.path.getsize(p) > 2000 for p in out_paths)


def generate_voice_batch(texts: list, voice: str, out_paths: list) -> bool:
    """Narrate every slide in ONE Gemini request, then split it at the pauses.

    The free Gemini tier allows only a handful of TTS requests per day, and one
    request per video (instead of one per slide) is what keeps the whole day of
    uploads on the natural voice instead of falling back to edge-tts.
    """
    if not texts or len(texts) != len(out_paths):
        return False
    if not gemini_voice_enabled() or not (os.environ.get("GEMINI_API_KEY") or "").strip():
        return False

    combined = "\n\n".join(t.strip() for t in texts if t and t.strip())
    if _FA_VOICE_STRICT and any(is_fa_text(t) for t in texts):
        # Persian batched path: never silently produce a robotic video. If the
        # one-shot Gemini call fails, raise instead of falling back to edge-tts.
        gemini_voice = gemini_voice_for(voice)
        tmp_mp3 = os.path.join(BASE_DIR, "temp_render", "_batch_narration.mp3")
        os.makedirs(os.path.dirname(tmp_mp3), exist_ok=True)
        if not generate_voice_gemini(combined, tmp_mp3, voice_name=gemini_voice):
            _refuse_robotic_fa(combined)
        if split_audio_by_silence(tmp_mp3, len(out_paths), out_paths,
                                  weights=[len(t.strip()) for t in texts]):
            print(f"[voice] one-shot Gemini narration split into {len(out_paths)} clips "
                  f"(voice={gemini_voice})")
            return True
        # Gemini spoke but clips could not be aligned - per-slide voices are still
        # safe (they go through generate_voice, which enforces the same rule).
        print("[voice] batch narration could not be split cleanly - using per-slide voices.")
    gemini_voice = gemini_voice_for(voice)
    tmp_mp3 = os.path.join(BASE_DIR, "temp_render", "_batch_narration.mp3")
    os.makedirs(os.path.dirname(tmp_mp3), exist_ok=True)
    try:
        if not generate_voice_gemini(combined, tmp_mp3, voice_name=gemini_voice):
            return False
        if split_audio_by_silence(tmp_mp3, len(out_paths), out_paths,
                                  weights=[len(t.strip()) for t in texts]):
            print(f"[voice] one-shot Gemini narration split into {len(out_paths)} clips "
                  f"(voice={gemini_voice})")
            return True
        print("[voice] batch narration could not be split cleanly - using per-slide voices.")
    except Exception as e:
        print(f"[voice] batch narration failed ({e}) - using per-slide voices.")
    return False


def get_audio_duration(file_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return float(res.stdout.strip())

def build_full_short(topic_data: dict, output_filename: str):
    work_dir = os.path.join(BASE_DIR, "temp_render")
    os.makedirs(work_dir, exist_ok=True)

    print(f"[render] libraqm={HAS_RAQM} -> Persian shaping by "
          f"{'Pillow/Raqm' if HAS_RAQM else 'arabic_reshaper + python-bidi'}")

    category = topic_data.get("category", "")
    topic_lang = (topic_data.get("lang") or "").strip().lower()
    slides = topic_data["slides"]
    total = len(slides)
    clip_files = []

    # Support explicit voice selection per topic or alternate voices per slide/topic
    base_voice_idx = topic_data.get("voice_index", 0)
    lang_voices = voices_for(topic_data)

    # Preferred path: ONE Gemini request narrates the whole video (consistent,
    # natural voice + saves the small free-tier quota). Falls back to one request
    # per slide, and finally to edge-tts, without ever stopping the pipeline.
    audio_paths = [os.path.join(work_dir, f"slide_{i}.mp3") for i in range(1, total + 1)]
    batch_voice = lang_voices[base_voice_idx % len(lang_voices)]
    if not generate_voice_batch([s.get("speech", "") for s in slides], batch_voice, audio_paths):
        for idx, slide in enumerate(slides, start=1):
            voice = slide.get("voice") or lang_voices[(base_voice_idx + idx - 1) % len(lang_voices)]
            generate_voice(slide["speech"], voice, audio_paths[idx - 1])

    for idx, slide in enumerate(slides, start=1):
        img_path = os.path.join(work_dir, f"slide_{idx}.png")
        audio_path = audio_paths[idx - 1]
        clip_path = os.path.join(work_dir, f"clip_{idx}.mp4")

        create_slide_image(category, slide["title"], slide["text"], idx, total, img_path, lang=topic_lang or None)
        duration = get_audio_duration(audio_path) + 0.4

        ffmpeg_clip = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_path,
            "-i", audio_path,
            "-t", f"{duration:.2f}",
            "-vf", "scale=1080:1920,format=yuv420p",
            "-c:v", "libx264", "-tune", "stillimage", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            clip_path
        ]
        subprocess.run(ffmpeg_clip, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clip_files.append(clip_path)

    concat_list_file = os.path.join(work_dir, "concat_list.txt")
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for clip in clip_files:
            safe_clip = clip.replace("\\", "/")
            f.write(f"file '{safe_clip}'\n")

    final_video_path = os.path.join(BASE_DIR, output_filename)
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list_file,
        "-c", "copy",
        final_video_path
    ]
    subprocess.run(concat_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return final_video_path

BG_MUSIC_EN = os.path.join(BASE_DIR, "sad_aesthetic_bg.mp3")
BG_MUSIC_DIR_EN = os.path.join(BASE_DIR, "music_en")
BG_MUSIC_DIR_FA = os.path.join(BASE_DIR, "music_fa")
BG_MUSIC_VOLUME = float(os.environ.get("BG_MUSIC_VOLUME", "0.18"))
BG_MUSIC_VOLUME_FA = float(os.environ.get("BG_MUSIC_VOLUME_FA", "0.15"))

# Persian pools are defined in topics_pool.py without a music key, so each topic
# is mapped to the bed that matches its mood (the old single sad track is gone).
FA_MUSIC_BY_ID = {
    "psy_attraction_01": "calm",
    "comedy_daily_01": "energy",
    "wildlife_predators_01": "cinematic",
    "ocean_creatures_01": "chill",
    "love_deep_01": "minimal",
    "transform_edit_01": "energy",
    "cooking_secrets_01": "chill",
    "iran_travel_01": "cinematic",
    "trending_music_01": "energy",
    "space_mysteries_01": "cinematic",
    "sleep_brain_01": "calm",
    "history_facts_01": "cinematic",
    "human_body_01": "chill",
}
FA_DEFAULT_MOOD = "calm"


def bg_track_for(topic_data: dict) -> str:
    """Theme-matched bed for a topic: music_en/* for EN, music_fa/* for FA."""
    lang = (topic_data.get("lang") or "").strip().lower()
    is_en = lang.startswith("en")
    mood = (topic_data.get("music") or "").strip().lower()
    if not mood:
        mood = "chill" if is_en else FA_MUSIC_BY_ID.get(topic_data.get("id", ""), FA_DEFAULT_MOOD)
    folder = BG_MUSIC_DIR_EN if is_en else BG_MUSIC_DIR_FA
    prefix = "en" if is_en else "fa"

    cand = os.path.join(folder, f"{prefix}_{mood}.mp3")
    if os.path.exists(cand) and os.path.getsize(cand) > 1000:
        return cand
    # fallback: any bed of the right language
    try:
        for f in sorted(os.listdir(folder)):
            p = os.path.join(folder, f)
            if f.startswith(prefix) and f.endswith(".mp3") and os.path.getsize(p) > 1000:
                return p
    except Exception:
        pass
    return ""


def mix_bg_music(video_path: str, lang: str = "", track: str = "") -> str:
    """Mix the theme bed under the narration (both languages). Returns final path."""
    is_en = (lang or "").strip().lower().startswith("en")
    src = track or (BG_MUSIC_EN if is_en else "")
    if not src or not os.path.exists(src) or os.path.getsize(src) < 1000:
        print("[music] no bg music file - skipping mix")
        return video_path
    volume = BG_MUSIC_VOLUME if is_en else BG_MUSIC_VOLUME_FA
    mixed_path = video_path.replace(".mp4", "_music.mp4")
    try:
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-stream_loop", "-1", "-i", src,
            "-filter_complex",
            f"[0:a]volume=1.0[a0];[1:a]volume={volume}[a1];"
            "[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            mixed_path,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(mixed_path) and os.path.getsize(mixed_path) > 10000:
            print(f"[music] mixed {os.path.basename(src)} ({volume}) -> {mixed_path}")
            return mixed_path
    except Exception as e:
        print(f"[music] mix failed ({e}) - using dry voice")
    return video_path


def upload_to_youtube(video_path: str, title: str, description: str, tags: list, privacy_status="public"):
    with open(TOKEN_PATH, "rb") as token_file:
        creds = pickle.load(token_file)

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27"
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")

    video_id = response.get("id")
    video_url = f"https://www.youtube.com/shorts/{video_id}"
    return video_url

if __name__ == "__main__":
    sample_topic = {
        "title": "۳ راز شگفت‌انگیز که مغزت رو منفجر می‌کنه! 🤯 #shorts",
        "description": "۳ دانستنی باورنکردنی و علمی که احتمالاً تا الان نشنیده بودید! کانال پادیز رو سابسکرایب کنید تا هر روز ویدیوهای جذاب ببینید.\n\n#shorts #دانستنی #علمی #فکت #جالب",
        "tags": ["shorts", "دانستنی", "فکت", "علمی", "عجیب", "آموزشی", "شورت"],
        "slides": [
            {
                "title": "قلب‌های اختاپوس",
                "text": "اختاپوس‌ها سه قلب دارند و رنگ خون آن‌ها آبی است!",
                "speech": "آیا می‌دانستید اختاپوس‌ها سه تا قلب دارند و خون آن‌ها به جای قرمز، کاملاً آبی است؟"
            },
            {
                "title": "عسل فاسدنشدنی",
                "text": "عسل طبیعی تنها ماده غذایی در جهان است که هرگز فاسد نمی‌شود.",
                "speech": "عسل طبیعی تنها خوراکی در جهانه که حتی بعد از سه هزار سال هم فاسد نمی‌شه و کاملاً سالمه!"
            },
            {
                "title": "صدای آب جوش و سرد",
                "text": "گوش انسان می‌تواند تفاوت صدای ریختن آب سرد و آب داغ را تشخیص دهد!",
                "speech": "انسان‌ها ناخودآگاه با گوش دادن به صدای ریختن آب، می‌تونن بفهمن اون آب سرده یا در حال جوشیدنه!"
            }
        ]
    }

    output_vid = "shorts_sample_1.mp4"
    print("Generating Shorts video...")
    rendered_file = build_full_short(sample_topic, output_vid)
    print("Video rendered successfully at:", rendered_file)
