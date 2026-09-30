# -*- coding: utf-8 -*-
"""Long-form (16:9) engine for Padiz - monetization-grade long videos.

Same self-made philosophy as the Shorts pipeline: our own script + our own voice +
our own music, rendered at 1920x1080 with gentle motion, chaptered description and
a custom thumbnail. Nothing is downloaded, so the channel stays 100% original.

CLI:
    python longform.py --list
    python longform.py --topic en_long_01            # build only
    python longform.py --topic en_long_01 --upload    # build + publish
"""
import os
import sys
import json
import math
import wave
import subprocess

import numpy as np

import pipeline as P

BASE_DIR = P.BASE_DIR


def _srt_escape(path):
    """ffmpeg's subtitles filter needs a Windows-safe, escaped path."""
    return path.replace("\\", "/").replace(":", "\\:")


def _fmt_ts(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_scene_srt(speech, duration, out_path, words_per_line=7):
    """Split one scene's narration into short caption lines with proportional timing."""
    words = [w for w in speech.replace("\n", " ").split(" ") if w.strip()]
    if not words:
        return None
    chunks = [" ".join(words[i:i + words_per_line]) for i in range(0, len(words), words_per_line)]
    weights = [max(len(c), 1) for c in chunks]
    total_w = sum(weights)
    t = 0.0
    lines = []
    for i, (chunk, w) in enumerate(zip(chunks, weights), start=1):
        span = duration * (w / total_w)
        lines.append(f"{i}\n{_fmt_ts(t)} --> {_fmt_ts(min(t + span, duration))}\n{chunk}\n")
        t += span
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def make_whoosh(out_path, seconds=0.55, seed=3):
    """Generate a soft transition 'whoosh' (self-made, copyright-free)."""
    if os.path.exists(out_path):
        return out_path
    rng = np.random.default_rng(seed)
    sr = 44100
    n = int(sr * seconds)
    t = np.arange(n) / sr
    noise = rng.normal(0, 1, n)
    # band-sweeping noise + airy tail
    sweep = np.sin(2 * np.pi * (300 + 1400 * (t / seconds)) * t)
    env = np.sin(np.pi * (t / seconds)) ** 1.6
    sig = 0.55 * noise * env + 0.25 * sweep * env
    sig /= max(1e-6, np.abs(sig).max())
    sig *= 0.6
    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((sig * 32767).astype(np.int16).tobytes())
    return out_path


def build_whoosh_track(boundaries, total_seconds, out_wav, whoosh_path):
    """One audio bed with a whoosh placed at every scene boundary."""
    sr = 44100
    total = int(sr * (total_seconds + 1.0))
    bed = np.zeros(total, dtype=np.float32)
    try:
        with wave.open(whoosh_path, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
        who = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        who = np.array([], dtype=np.float32)

    if who.size:
        for b in boundaries:
            at = int(sr * b)
            if 0 <= at < total:
                end = min(total, at + who.size)
                bed[at:end] += who[:end - at]
    bed = np.clip(bed, -1, 1)
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((bed * 32767).astype(np.int16).tobytes())
    return out_wav


WHOOSH = os.path.join(BASE_DIR, "assets", "whoosh.wav")

LONGFORM_DIR = os.path.join(BASE_DIR, "longform_out")

WIDTH, HEIGHT, FPS = 1920, 1080, 30
SCENES_PER_TTS_REQUEST = int(os.environ.get("LONG_SCENES_PER_TTS_REQUEST", "6"))
LONG_MUSIC_VOLUME = float(os.environ.get("LONG_MUSIC_VOLUME", "0.12"))
SECONDS_BETWEEN_SCENES = float(os.environ.get("LONG_SCENE_PAD", "0.9"))


def _long_theme(lang: str) -> dict:
    """FA keeps the brand navy/gold, EN uses the teal identity."""
    if (lang or "").lower().startswith("en"):
        return {"bg": (4, 22, 30), "bg2": (7, 40, 52), "accent": (34, 211, 238),
                "head": (103, 232, 249), "body": (226, 245, 250),
                "muted": (125, 211, 252), "bar": (6, 182, 212)}
    return {"bg": (10, 16, 30), "bg2": (22, 32, 52), "accent": (239, 68, 68),
            "head": (250, 204, 21), "body": (233, 238, 246),
            "muted": (148, 163, 184), "bar": (220, 38, 38)}


# --- Colour psychology -------------------------------------------------------
# Owner directive 2026-09-30: palette must match the mood of the topic, not one
# default look for every video. Navy/gold = trust & money (finance). Violet/amber
# = mystery & the unknown. Deep blue/cyan = science & tech. Sepia/brass = history.
# Crimson = danger/dark history. Emerald = health/nature.
_MOOD_PALETTES = {
    "money":     {"accent": (240, 180, 41), "head": (255, 214, 102), "bar": (198, 138, 20),
                  "wash": (18, 26, 46), "accent2": (16, 185, 129)},
    "mystery":   {"accent": (168, 85, 247), "head": (233, 196, 106), "bar": (126, 58, 196),
                  "wash": (24, 14, 40), "accent2": (217, 70, 239)},
    "science":   {"accent": (56, 189, 248), "head": (165, 243, 252), "bar": (14, 116, 190),
                  "wash": (8, 22, 40), "accent2": (45, 212, 191)},
    "history":   {"accent": (214, 158, 84), "head": (245, 213, 158), "bar": (154, 103, 46),
                  "wash": (32, 22, 14), "accent2": (198, 138, 60)},
    "dark":      {"accent": (220, 38, 38), "head": (252, 165, 165), "bar": (153, 27, 27),
                  "wash": (28, 10, 12), "accent2": (249, 115, 22)},
    "nature":    {"accent": (52, 211, 153), "head": (167, 243, 208), "bar": (5, 150, 105),
                  "wash": (8, 28, 24), "accent2": (132, 204, 22)},
}

_MOOD_WORDS = {
    "money": ["money", "finance", "investing", "wealth", "economy", "business",
              "crypto", "real estate", "startup", "entrepreneur", "money trap"],
    "mystery": ["mystery", "unsolved", "conspiracy", "crime", "horror", "secret",
                "vanished", "enigma", "dark", "occult"],
    "science": ["science", "space", "ai", "technology", "tech", "coding", "robot",
                "body", "medical", "physics", "future", "software", "cyber"],
    "history": ["history", "ancient", "civilization", "archaeology", "empire",
                "war", "medieval", "iran", "heritage", "archaeological"],
    "nature": ["nature", "animal", "food", "health", "fitness", "earth", "ocean", "climate"],
}


def _topic_mood(topic):
    """Pick a palette from the topic id, series and tags."""
    hay = " ".join([
        str(topic.get("id", "")), str(topic.get("series", "")),
        str(topic.get("title", "")), " ".join(topic.get("tags") or []),
    ]).lower()
    for mood, words in _MOOD_WORDS.items():
        if any(w in hay for w in words):
            return mood
    return "science"


def _palette(topic, lang):
    """Blend the chosen mood with the language identity so FA/EN stay recognisable."""
    th = _long_theme(lang)
    mood = _topic_mood(topic)
    p = _MOOD_PALETTES[mood]
    # Keep a hint of the brand identity (teal for EN, red for FA) as accent2.
    p = dict(p)
    p["brand"] = th["accent"]
    p["brand_bg"] = th["bg"]
    p["mood"] = mood
    return p


def _vignette(img, strength=140, w=None, h=None):
    """Darken the corners so text always wins over a busy photo."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = w or img.width, h or img.height
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w * 0.30, -h * 0.34, w * 1.30, h * 1.34], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(int(260 * w / WIDTH)))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    img.paste(dark, (0, 0), mask.point(lambda v: int((255 - v) * strength / 255)))
    return img


def _top_scrim(img, band=250, peak=210):
    """Extra darkening under the top chrome so the brand line is never lost."""
    from PIL import Image
    w, h = img.width, img.height
    band = int(band * w / WIDTH)
    m = Image.new("L", (1, band))
    px = m.load()
    for y in range(band):
        t = y / max(band - 1, 1)
        px[0, y] = int(peak * (1 - t) ** 1.3)
    m = m.resize((w, band))
    full = Image.new("L", (w, h), 0)
    full.paste(m, (0, 0))
    black = Image.new("RGB", (w, h), (2, 4, 10))
    return Image.composite(black, img, full)


def _gradient_scrim(img, top=70, bottom=232, left_boost=True):
    """Cinematic vertical scrim: keeps the photo alive up top, black where text sits."""
    from PIL import Image, ImageDraw, ImageChops
    w, h = img.width, img.height
    grad = Image.new("L", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = int(top + (bottom - top) * (t ** 1.55))
    grad = grad.resize((w, h))
    if left_boost:
        side = Image.new("L", (w, h), 0)
        sd = ImageDraw.Draw(side)
        for x in range(w):
            v = int(120 * max(0.0, 1.0 - (x / (w * 0.62)) ** 1.4))
            sd.line([(x, 0), (x, h)], fill=v)
        grad = ImageChops.add(grad, side, scale=1.0)
    black = Image.new("RGB", (w, h), (4, 6, 14))
    return Image.composite(black, img, grad.point(lambda v: min(255, v)))


def _wrap_to_width(draw, text, font, max_width, max_lines=4):
    """Real measured wrapping (character counting produced ragged, broken lines)."""
    words = text.split()
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(" ".join(cur))
    if len(lines) == max_lines and len(words) > sum(len(l.split()) for l in lines):
        lines[-1] = lines[-1] + " ..."
    return lines


def _shadow_text(draw, xy, text, font, fill, anchor=None, shadow=(0, 0, 0, 190), off=4):
    """Text with a soft drop shadow - mandatory over photography."""
    x, y = xy
    draw.text((x + off, y + off), text, font=font, fill=shadow, anchor=anchor)
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _cover_crop(im, w, h):
    """Resize + center-crop an image to exactly w x h (like CSS background-size: cover)."""
    from PIL import Image
    src_ratio = im.width / im.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    im = im.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return im.crop((left, top, left + w, top + h))


def create_scene_frame(scene, idx, total, series_title, out_path, lang="fa", bg_image=None, topic=None):
    """Scene card: full-bleed photo + cinematic scrim + kinetic-ready typographic block.

    Rewritten 2026-09-30 after owner feedback that the old flat-blend frame with one
    grey rounded box looked weak. Now: real measured text wrapping, drop shadows,
    a mood palette chosen from the topic, a ghost numeral, and a cleaner progress rail.
    """
    from PIL import Image, ImageDraw, ImageFilter
    import fonts as F

    topic = topic or {}
    pal = _palette(topic, lang)
    theme_bg = tuple(pal["brand_bg"])
    accent, head, bar = pal["accent"], pal["head"], pal["bar"]

    # --- Background: photo, graded, not just dimmed ------------------------------
    base = None
    if bg_image and os.path.exists(bg_image):
        try:
            base = _cover_crop(Image.open(bg_image).convert("RGB"), WIDTH, HEIGHT)
        except Exception as e:
            print(f"  [frame] image failed ({e}) - using flat background")
    if base is None:
        base = Image.new("RGB", (WIDTH, HEIGHT), tuple(pal["wash"]))

    # Gentle colour grade toward the topic mood so every frame feels intentional.
    wash = Image.new("RGB", (WIDTH, HEIGHT), tuple(pal["wash"]))
    base = Image.blend(base, wash, 0.18)
    img = _gradient_scrim(base, top=58, bottom=236)
    img = _vignette(img, strength=150)
    img = _top_scrim(img, band=250, peak=205)

    draw = ImageDraw.Draw(img, "RGBA")

    # --- Top chrome: brand, series, part chip -------------------------------------
    brand_font = F.body(28, "Padiz")
    series_font = F.body(30, series_title)

    label = (f"PART {idx} / {total}" if (lang or "").lower().startswith("en")
             else f"بخش {idx} از {total}")
    # NOTE: the font must be chosen from the *real* string - passing a Latin sample
    # made the Persian label fall back to a Latin face and render as empty boxes.
    chip_font = F.body(26, label)

    _shadow_text(draw, (96, 74), "PADIZ STUDIO", brand_font, (255, 255, 255, 220), off=3)
    _shadow_text(draw, (96, 116), series_title, series_font, accent + (245,), off=3)

    tw = draw.textlength(label, font=chip_font)
    pad_x, chip_h = 30, 56
    chip_w = tw + pad_x * 2
    cx0 = WIDTH - 96 - chip_w
    draw.rounded_rectangle([(cx0, 70), (cx0 + chip_w, 70 + chip_h)], radius=chip_h // 2,
                           fill=accent + (240,))
    draw.text((cx0 + chip_w / 2, 70 + chip_h / 2), label, font=chip_font,
              fill=(12, 14, 22, 255), anchor="mm")

    # --- Ghost numeral on the right ------------------------------------------------
    ghost = F.number(340, str(idx))
    _shadow_text(draw, (WIDTH - 150, 430), str(idx), ghost, accent + (38,), anchor="mm", off=0)

    # --- Text block (kept clear of the subtitle zone at the bottom) ----------------
    x = 96
    max_w = int(WIDTH * 0.56)
    title_font = F.display(78, scene["title"])
    body_font = F.body(44, scene["text"])

    # Auto-shrink long titles so they never collide with the edge.
    while draw.textlength(scene["title"], font=title_font) > max_w and title_font.size > 52:
        title_font = F.display(title_font.size - 4, scene["title"])

    title_lines = _wrap_to_width(draw, scene["title"], title_font, max_w, max_lines=2)
    body_lines = _wrap_to_width(draw, scene["text"], body_font, max_w, max_lines=3)

    y = 300
    # Accent rule above the title - a designed detail instead of a floating box.
    draw.rectangle([(x, y - 26), (x + 132, y - 18)], fill=accent + (255,))

    for line in title_lines:
        _shadow_text(draw, (x, y), line, title_font, head, off=5)
        y += int(title_font.size * 1.18)

    y += 22
    for line in body_lines:
        _shadow_text(draw, (x, y), line, body_font, (238, 243, 250, 240), shadow=(0, 0, 0, 215), off=3)
        y += int(body_font.size * 1.42)

    # --- Progress rail -------------------------------------------------------------
    rail_y = HEIGHT - 58
    draw.rounded_rectangle([(96, rail_y), (WIDTH - 96, rail_y + 8)], radius=4,
                           fill=(255, 255, 255, 38))
    filled = 96 + int((WIDTH - 192) * (idx / max(total, 1)))
    draw.rounded_rectangle([(96, rail_y), (filled, rail_y + 8)], radius=4, fill=accent + (255,))

    dot_y = rail_y + 34
    gap = 30
    start_x = WIDTH - 96 - (total - 1) * gap
    for i in range(1, total + 1):
        x_i = start_x + (i - 1) * gap
        r = 7
        if i <= idx:
            draw.ellipse([(x_i - r, dot_y - r), (x_i + r, dot_y + r)], fill=accent + (255,))
        else:
            draw.ellipse([(x_i - r, dot_y - r), (x_i + r, dot_y + r)],
                         fill=(255, 255, 255, 30), outline=(255, 255, 255, 60), width=1)

    img.save(out_path, quality=95)
    return out_path




def create_thumbnail(topic, out_path, bg_image=None):
    """1280x720 thumbnail built on a real photo.

    Owner verdict 2026-09-30: the old flat-colour card looked cheap. This version uses
    the strongest scene photo, a hard contrast scrim, 2-4 words of display type and a
    single accent element - readable at 210px wide in mobile search.
    """
    from PIL import Image, ImageDraw
    import fonts as F

    lang = topic.get("lang", "fa")
    pal = _palette(topic, lang)
    accent, head = pal["accent"], pal["head"]
    W, H = 1280, 720

    # --- Photo base ---------------------------------------------------------------
    if bg_image and os.path.exists(bg_image):
        try:
            img = _cover_crop(Image.open(bg_image).convert("RGB"), W, H)
        except Exception:
            img = Image.new("RGB", (W, H), tuple(pal["wash"]))
    else:
        img = Image.new("RGB", (W, H), tuple(pal["wash"]))
    img = _top_scrim(img, band=200, peak=190)
    img = _gradient_scrim(img, top=40, bottom=225, left_boost=False)
    img = _vignette(img, strength=170)
    draw = ImageDraw.Draw(img, "RGBA")

    # --- Hook text (2-4 words, auto-shrunk to fit) --------------------------------
    hook = topic.get("thumbnail_text") or topic["title"].replace("#shorts", "").strip()
    hook = hook.strip()
    words = hook.split()
    if len(words) > 4:
        hook = " ".join(words[:4])

    size = 132
    lines = None
    while size > 44:
        f = F.display(size, hook)
        trial = _wrap_to_width(draw, hook, f, W - 190, max_lines=3)
        widest = max((draw.textlength(l, font=f) for l in trial), default=0)
        if len(trial) <= 3 and widest <= W - 190 and len(trial) * size * 1.12 <= 470:
            lines, size_used = trial, size
            break
        size -= 6
    if lines is None:
        lines = _wrap_to_width(draw, hook, F.display(60, hook), W - 190, max_lines=3)
        size_used = 60

    font = F.display(size_used, hook)
    line_h = int(size_used * 1.14)
    block_h = line_h * len(lines)
    y = (H - block_h) / 2 + 18

    for line in lines:
        _shadow_text(draw, (W / 2, y), line, font, head, anchor="ma", off=7)
        y += line_h

    # --- Accent bar under the hook -------------------------------------------------
    bar_y = min(int(y + 16), H - 150)
    bar_w = min(int(max(draw.textlength(l, font=font) for l in lines)) + 60, W - 120)
    draw.rounded_rectangle([(W / 2 - bar_w / 2, bar_y), (W / 2 + bar_w / 2, bar_y + 12)],
                           radius=6, fill=accent + (255,))

    # --- Brand lockup ---------------------------------------------------------------
    brand_font = F.display(40, "Padiz")
    _shadow_text(draw, (W / 2, H - 96), "PADIZ STUDIO", brand_font, (255, 255, 255, 235),
                 anchor="ma", off=4)

    img.save(out_path, quality=95)
    return out_path


def _narrate_scenes(topic, scenes, work_dir):
    """Narrate every scene, chunking the Gemini calls to respect the free quota."""
    out_paths = [os.path.join(work_dir, f"long_voice_{i:02d}.mp3") for i in range(1, len(scenes) + 1)]

    # Cache: reuse existing narration (re-renders must not burn Gemini quota).
    if all(os.path.exists(p) and os.path.getsize(p) > 5000 for p in out_paths):
        print(f"  [voice] using {len(out_paths)} cached narration clips")
        return out_paths

    lang = topic.get("lang", "fa")
    voices = P.voices_for(dict(topic, lang=lang))
    voice = voices[topic.get("voice_index", 0) % len(voices)]

    for start in range(0, len(scenes), SCENES_PER_TTS_REQUEST):
        chunk = scenes[start:start + SCENES_PER_TTS_REQUEST]
        chunk_out = out_paths[start:start + SCENES_PER_TTS_REQUEST]
        if P.generate_voice_batch([s.get("speech", "") for s in chunk], voice, chunk_out):
            continue
        for offset, scene in enumerate(chunk):
            P.generate_voice(scene.get("speech", ""), voice, chunk_out[offset])
    return out_paths


def build_long_video(topic, output_name=None, use_images=True):
    """Render a 16:9 long video (photo scenes + narration + captions + whoosh + music)."""
    os.makedirs(LONGFORM_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(WHOOSH), exist_ok=True)
    work = os.path.join(LONGFORM_DIR, topic["id"])
    os.makedirs(work, exist_ok=True)

    lang = topic.get("lang", "fa")
    scenes = topic["scenes"]
    total = len(scenes)
    series = topic.get("series") or topic["title"]

    print(f"[long] {topic['id']}: {total} scenes, lang={lang}")
    voices = _narrate_scenes(topic, scenes, work)

    images = {}
    if use_images:
        try:
            import image_fetch
            images = image_fetch.fetch_topic_images(topic)
            print(f"  [img] {len(images)}/{total} photos ready")
        except Exception as e:
            print(f"  [img] skipped ({e})")

    make_whoosh(WHOOSH)
    font_name = "Arial" if lang.lower().startswith("en") else "Vazirmatn"
    fonts_dir = _srt_escape(BASE_DIR)

    clips, chapters, boundaries = [], [], []
    t_cursor = 0.0
    for idx, scene in enumerate(scenes, start=1):
        img = os.path.join(work, f"scene_{idx:02d}.png")
        clip = os.path.join(work, f"clip_{idx:02d}.mp4")
        create_scene_frame(scene, idx, total, series, img, lang=lang,
                           bg_image=images.get(idx), topic=topic)

        audio = voices[idx - 1]
        speech_dur = P.get_audio_duration(audio)
        dur = speech_dur + SECONDS_BETWEEN_SCENES
        frames = max(int(dur * FPS), FPS)

        srt = build_scene_srt(scene.get("speech", ""), speech_dur,
                              os.path.join(work, f"scene_{idx:02d}.srt"))
        fade_out_st = max(dur - 0.35, 0.1)

        vf = (f"scale=2112:1188,zoompan=z='min(zoom+0.00035,1.07)':"
              f"d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={WIDTH}x{HEIGHT}:fps={FPS},"
              f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_st:.2f}:d=0.35")
        if srt:
            style = (f"FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00141414,"
                     f"BorderStyle=1,Outline=2,Shadow=0,MarginV=40,Alignment=2")
            vf += (f",subtitles='{_srt_escape(srt)}':fontsdir='{fonts_dir}'"
                   f":force_style='{style}'")
        vf += ",format=yuv420p"

        subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", audio,
                        "-t", f"{dur:.2f}", "-vf", vf,
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", clip],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clips.append(clip)
        chapters.append((t_cursor, scene["title"]))
        if idx > 1:
            boundaries.append(t_cursor)      # whoosh on every scene change
        t_cursor += dur
        print(f"  scene {idx}/{total} ok ({dur:.1f}s)")

    lst = os.path.join(work, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for c in clips:
            f.write("file '%s'\n" % c.replace("\\", "/"))

    speech_track = os.path.join(work, "speech.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", speech_track],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    out_name = output_name or f"long_{topic['id']}.mp4"
    final = os.path.join(LONGFORM_DIR, out_name)

    whoosh_bed = build_whoosh_track(boundaries, t_cursor,
                                    os.path.join(work, "whoosh_bed.wav"), WHOOSH)
    track = P.bg_track_for(topic)
    if track:
        subprocess.run(["ffmpeg", "-y", "-i", speech_track,
                        "-stream_loop", "-1", "-i", track,
                        "-i", whoosh_bed,
                        "-filter_complex",
                        f"[0:a]volume=1.0[a0];[1:a]volume={LONG_MUSIC_VOLUME}[a1];"
                        f"[2:a]volume=0.55[a2];"
                        "[a0][a1][a2]amix=inputs=3:duration=first:dropout_transition=2[aout]",
                        "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", final],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["ffmpeg", "-y", "-i", speech_track, "-i", whoosh_bed,
                        "-filter_complex",
                        "[0:a]volume=1.0[a0];[1:a]volume=0.55[a1];"
                        "[a0][a1]amix=inputs=2:duration=first[aout]",
                        "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", final],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    thumb = os.path.join(LONGFORM_DIR, f"thumb_{topic['id']}.jpg")
    # Prefer a scene photo that passed the quality gate, so the thumbnail is never
    # built on a rejected diagram/scan.
    thumb_bg = next((images[i] for i in sorted(images)), None)
    create_thumbnail(topic, thumb, bg_image=thumb_bg)

    duration = P.get_audio_duration(final)
    meta = {"id": topic["id"], "video": final, "thumbnail": thumb,
            "duration": duration, "chapters": chapters, "lang": lang,
            "images": len(images)}
    with open(os.path.join(LONGFORM_DIR, f"{topic['id']}.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[long] done: {final} ({duration/60:.2f} min)")
    return meta


def chapters_block(chapters):
    out = []
    for start, title in chapters:
        mm, ss = divmod(int(start), 60)
        hh, mm = divmod(mm, 60)
        stamp = f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
        out.append(f"{stamp} {title}")
    return "\n".join(out)


def _clean_credit(text):
    """Strip HTML tags/links that Wikimedia returns; YouTube rejects HTML in descriptions."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)          # drop all tags
    text = re.sub(r"https?://\S+", "", text)       # drop bare URLs
    text = re.sub(r"\s+", " ", text).strip(" -,;")
    return text[:120]


def _credits_block(topic_id):
    """Aggregate photo credits (CC0/PD - attribution optional but nice)."""
    folder = os.path.join(BASE_DIR, "longform_images", topic_id)
    if not os.path.isdir(folder):
        return ""
    seen, lines = set(), []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".credit.txt"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                first = fh.readline().strip()
        except OSError:
            continue
        first = _clean_credit(first)
        if first and first.lower() not in ("unknown", "anonymous", "anonymousunknown author") and first not in seen:
            seen.add(first)
            lines.append(f"- {first}")
    if not lines:
        return ""
    return "\n\nVisuals: public-domain / CC0 photos (Wikimedia Commons, Openverse):\n" + "\n".join(lines)


def upload_long(meta, topic):
    desc = topic["description"].rstrip()
    desc += "\n\nChapters:\n" + chapters_block(meta["chapters"])
    desc += "\n\n" + topic.get("cta", "Subscribe for more deep dives!")
    desc += _credits_block(topic["id"])
    url = P.upload_to_youtube(meta["video"], topic["title"], desc, topic["tags"],
                              privacy_status=topic.get("privacy", "public"))
    video_id = url.rstrip("/").split("/")[-1]
    url = f"https://www.youtube.com/watch?v={video_id}"  # long-form -> standard watch URL
    try:
        import pickle
        from googleapiclient.discovery import build
        with open(P.TOKEN_PATH, "rb") as fh:
            creds = pickle.load(fh)
        yt = build("youtube", "v3", credentials=creds)
        yt.thumbnails().set(videoId=video_id,
                            media_body=P.MediaFileUpload(meta["thumbnail"])).execute()
        print("[long] custom thumbnail set")
    except Exception as e:
        print(f"[long] thumbnail upload skipped ({e})")
    return url


def load_topics():
    topics = []
    for mod_name, var in (("topics_pool_long_fa", "LONG_TOPICS_FA"),
                          ("topics_pool_long_en", "LONG_TOPICS_EN")):
        try:
            mod = __import__(mod_name)
            topics.extend(getattr(mod, var))
        except Exception as e:
            print(f"[long] {mod_name} not available ({e})")
    return topics


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    topics = load_topics()
    if "--list" in argv or not argv:
        for t in topics:
            print(f"{t['id']:24} {t['lang']:3} {len(t['scenes']):3} scenes  {t['title'][:60]}")
        return 0

    wanted = (argv[argv.index("--topic") + 1] if "--topic" in argv else topics[0]["id"])
    topic = next((t for t in topics if t["id"] == wanted), None)
    if topic is None:
        print(f"topic {wanted} not found")
        return 1

    meta = build_long_video(topic)
    if "--upload" in argv:
        if "--unlisted" in argv:
            topic = dict(topic, privacy="unlisted")
        print(upload_long(meta, topic))
    return 0


if __name__ == "__main__":
    sys.exit(main())

