"""Word-by-word animated captions for Shorts.

Owner directive 2026-10-13: on a vertical Short the single biggest retention
lever is the viewer being able to READ what is being said. Big captions that
highlight the word currently being spoken ("karaoke") hold attention far better
than a static text block, because the eye is given something to track every
~300 ms instead of one change per slide.

How it works
------------
1. Neither Gemini TTS nor edge-tts gives us per-word timings, so the measured
   narration duration is distributed over the words, weighted by how long each
   word takes to say: its length plus a pause allowance for trailing
   punctuation. This is the same proportional model longform.build_scene_srt
   already uses, refined from per-chunk to per-word.
2. Words are grouped into small chunks (2-4 words) that fit on one line.
3. ONE PNG is rendered per SPOKEN WORD. The chunk stays on screen while the
   highlight sweeps across it, and the active word is drawn larger and in the
   mood accent colour - the "pop".
4. The frames are handed to ffmpeg as a concat list with explicit per-frame
   durations, so no alpha channel or overlay filter is involved: each frame is a
   complete 1080x1920 picture.

Persian shaping is delegated to pipeline.draw_persian / pipeline.prepare_bidi_text,
so this module inherits the exact same libraqm-vs-arabic_reshaper decision as the
rest of the renderer and can never disagree with the slide underneath.
"""

import os
import re

import pipeline as P

# --- Tunables ---------------------------------------------------------------
# One caption line. Big is the point: this is read on a phone.
BASE_SIZE = 76
POP_SIZE = 88           # the active word
MIN_SIZE = 44
MAX_WORDS_PER_CHUNK = 4
MIN_WORDS_PER_CHUNK = 2
LINE_GAP_FACTOR = 0.30  # gap between words, as a fraction of the font size
CAPTION_CY = 1055       # vertical centre of the caption line, inside the card
MIN_STATE = 0.12        # never emit a frame shorter than this (1-frame flicker)

# Trailing punctuation means the narrator pauses, so the word "lasts" longer.
HARD_PAUSE = ".!?؟…"
SOFT_PAUSE = "،,;؛:"

_EMOJI_RE = re.compile(r'[\U00010000-\U0010ffff]')


# --- Timing -----------------------------------------------------------------
def clean_words(speech):
    """Words of the narration, with emoji/pictographs removed.

    Emoji would be dropped by the shaping step anyway and would only skew the
    measured widths, so they are removed before anything else happens.
    """
    text = _EMOJI_RE.sub(" ", speech or "")
    return [w for w in text.replace("\n", " ").split(" ") if w.strip()]


def word_weight(word):
    """Relative speaking time of one word."""
    core = re.sub(r"[^\w\u0600-\u06FF]", "", word)
    w = max(len(core), 1) ** 0.85   # long words are slower, but not linearly
    if word and word[-1] in HARD_PAUSE:
        w += 2.4
    elif word and word[-1] in SOFT_PAUSE:
        w += 1.2
    return w


def plan_word_times(words, duration):
    """[(word, start, end)] covering `duration` seconds, in order."""
    if not words or duration <= 0:
        return []
    weights = [word_weight(w) for w in words]
    total = sum(weights) or 1.0
    out, t = [], 0.0
    for w, wt in zip(words, weights):
        span = duration * (wt / total)
        out.append((w, t, t + span))
        t += span
    # Absorb rounding so the last word ends exactly on the audio.
    if out:
        w, s, _ = out[-1]
        out[-1] = (w, s, duration)
    return out


def chunk_words(timed, draw, font, max_width):
    """Group timed words into lines that fit `max_width`."""
    chunks, cur = [], []
    for item in timed:
        trial = cur + [item]
        text = " ".join(t[0] for t in trial)
        fits = P._measure(draw, P.prepare_bidi_text(text), font) <= max_width
        if cur and (not fits or len(cur) >= MAX_WORDS_PER_CHUNK):
            chunks.append(cur)
            cur = [item]
        else:
            cur = trial
    if cur:
        chunks.append(cur)
    # A one-word line at the very end reads as a stutter - fold it back.
    if len(chunks) >= 2 and len(chunks[-1]) < MIN_WORDS_PER_CHUNK:
        last = chunks.pop()
        if len(chunks[-1]) + len(last) <= MAX_WORDS_PER_CHUNK + 1:
            chunks[-1].extend(last)
        else:
            chunks.append(last)
    return chunks


def fit_chunks(draw, words, duration, max_width):
    """Chunk the narration, shrinking the font until every line fits.

    Chunking depends on the font size and the font size depends on the widest
    chunk, so this is a small fixed-point loop rather than two separate steps.
    """
    timed = plan_word_times(words, duration)
    size = BASE_SIZE
    while True:
        font = P.font_for(" ".join(words[:1]) or "x", size)
        chunks = chunk_words(timed, draw, font, max_width)
        gap = size * LINE_GAP_FACTOR
        widest = max(
            (sum(_measure_word(draw, c[0], font) for c in ch) + gap * max(len(ch) - 1, 0)
             for ch in chunks),
            default=0.0,
        )
        if widest <= max_width or size <= MIN_SIZE:
            return chunks, size
        size -= 4


# --- Drawing ----------------------------------------------------------------
def _draw_word(draw, xy, word, font, fill, anchor, stroke=0):
    """One Persian/Latin word. Mirrors pipeline.draw_persian but adds an outline,
    which is what makes the text readable over any slide background."""
    kwargs = {"font": font, "fill": fill, "anchor": anchor}
    if P.HAS_RAQM:
        # Direction is per word: a single Latin word must not be treated as RTL.
        kwargs["direction"] = "rtl" if P.is_fa_text(word) else "ltr"
        kwargs["language"] = "fa" if P.is_fa_text(word) else "en"
    if stroke:
        kwargs["stroke_width"] = stroke
        kwargs["stroke_fill"] = (0, 0, 0)
    draw.text(xy, P.prepare_bidi_text(word), **kwargs)


def _measure_word(draw, word, font):
    return P._measure(draw, P.prepare_bidi_text(word), font)


def layout_line(draw, words, active_i, base_size, en_mode, sample, accent):
    """Draw one caption line with `active_i` popped.

    The words are laid out by hand instead of as a single string because the
    active word needs its own font size and colour. Persian runs right-to-left,
    so the first logical word is placed at the RIGHT edge and the cursor walks
    leftwards; English mirrors that.
    """
    fonts = [P.font_for(sample, base_size)] * len(words)
    if 0 <= active_i < len(fonts):
        fonts[active_i] = P.font_for(sample, POP_SIZE)

    widths = [_measure_word(draw, w, f) for w, f in zip(words, fonts)]
    gap = base_size * LINE_GAP_FACTOR
    total = sum(widths) + gap * max(len(words) - 1, 0)

    cx, cy = 1080 // 2, CAPTION_CY
    stroke = max(3, base_size // 14)

    if en_mode:
        x = cx - total / 2.0
        for i, (w, f, wd) in enumerate(zip(words, fonts, widths)):
            _draw_word(draw, (x, cy), w, f,
                       accent if i == active_i else (255, 255, 255), "lm", stroke)
            x += wd + gap
    else:
        x = cx + total / 2.0
        for i, (w, f, wd) in enumerate(zip(words, fonts, widths)):
            _draw_word(draw, (x, cy), w, f,
                       accent if i == active_i else (255, 255, 255), "rm", stroke)
            x -= wd + gap
    return total


# --- Frame production -------------------------------------------------------
def build_frames(slide_png, speech, audio_duration, out_dir, tag,
                 category="", title="", text="", lang=None):
    """Render one PNG per spoken word for a single slide.

    Returns [(png_path, seconds)] in play order, or None when captions cannot be
    produced (in which case the caller keeps the plain static-image clip).
    """
    from PIL import Image, ImageDraw

    words = clean_words(speech)
    if len(words) < 2 or audio_duration <= 0.4:
        return None

    try:
        base = Image.open(slide_png).convert("RGB")
    except Exception:
        return None

    probe = ImageDraw.Draw(base)
    theme, en_mode, _mood = P.shorts_theme(category, title, text, lang)
    accent = tuple(theme.get("accent") or theme.get("topbar") or (240, 180, 41))
    # 120px of side padding, not the 90px the slide uses: the slide card border
    # sits at 70px, so a caption allowed to reach 90px would run into it.
    safe_w = 1080 - 2 * 120

    chunks, base_size = fit_chunks(probe, words, audio_duration, safe_w)

    os.makedirs(out_dir, exist_ok=True)
    frames = []
    for ci, chunk in enumerate(chunks):
        chunk_text = [c[0] for c in chunk]
        for wi, (word, start, end) in enumerate(chunk):
            frame = base.copy()
            layout_line(ImageDraw.Draw(frame), chunk_text, wi, base_size,
                        en_mode, " ".join(chunk_text), accent)
            path = os.path.join(out_dir, f"cap_{tag}_{ci:02d}_{wi:02d}.png")
            frame.save(path)
            frames.append((path, max(end - start, MIN_STATE)))

    return frames or None


def write_concat_list(frames, out_path, tail=0.0):
    """ffmpeg concat demuxer list with per-frame durations.

    The concat demuxer ignores the duration of the FINAL entry, so the list must
    end with a bare `file` line (the documented "closer"). `tail` is therefore
    folded into the last frame's own duration rather than appended as another
    entry - appending it would put it on the one line that is thrown away.
    """
    lines = []
    last_i = len(frames) - 1
    for i, (path, dur) in enumerate(frames):
        d = dur + (tail if i == last_i else 0.0)
        lines.append(f"file '{path.replace(os.sep, '/')}'")
        lines.append(f"duration {max(d, MIN_STATE):.3f}")
    lines.append(f"file '{frames[last_i][0].replace(os.sep, '/')}'")   # closer
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def enabled():
    """Captions are ON by default; set SHORTS_CAPTIONS=0 to go back to the
    static body text."""
    return (os.environ.get("SHORTS_CAPTIONS", "1") or "1").strip().lower() not in (
        "0", "false", "no", "off")
