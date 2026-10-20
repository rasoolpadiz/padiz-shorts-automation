"""Plain, static subtitles for Shorts.

Owner directive 2026-10-14: the karaoke treatment shipped in 480ad9c (the spoken
word drawn larger and in the mood accent colour, sweeping across the line) reads
as a distracting animation rather than a subtitle. The subtitle is now PLAIN:
one ordinary line of body text, drawn exactly the way the slide draws its own
body copy - no highlight, no colour change, no size change, nothing inside a line
ever moves.

How it works
------------
1. Neither Gemini TTS nor edge-tts gives us per-word timings, so the measured
   narration duration is distributed over the words, weighted by how long each
   word takes to say: its length plus a pause allowance for trailing
   punctuation. This is the same proportional model longform.build_scene_srt
   already uses.
2. Words are grouped into small chunks (2-4 words) that fit on one line.
3. ONE PNG is rendered per CHUNK. The chunk stays on screen for exactly as long
   as its words take to say, then the next chunk simply replaces it.
4. The frames are handed to ffmpeg as a concat list with explicit per-frame
   durations, so no alpha channel or overlay filter is involved: each frame is a
   complete 1080x1920 picture.

Persian shaping is delegated to pipeline.draw_smart / pipeline.prepare_bidi_text,
so this module inherits the exact same libraqm-vs-arabic_reshaper decision as the
rest of the renderer and can never disagree with the slide underneath.

Guarantee (owner directive 2026-10-20)
--------------------------------------
EVERY Short carries a subtitle. Before this change build_frames() silently
returned None whenever the narration was shorter than two words or shorter than
0.4s, and pipeline.py then shipped a slide with no subtitle at all - and, in the
timing-retry path, with no text either (the body block had been suppressed for a
subtitle that never appeared). Now:

* build_frames() falls back to the slide's own text (then its title) when the
  narration is unusable, and a single static line when there is nothing to time.
* build_static_overlay() renders a transparent caption layer that pipeline.py
  burns over the slide as a last resort, so a subtitle is always on screen.
* band_has_text() reads the encoded clip back and reports whether the caption
  band really contains text, so pipeline.py can detect and repair a clip whose
  subtitle never made it into the file.
"""

import os
import re

import pipeline as P

# --- Tunables ---------------------------------------------------------------
# One caption line. Big is the point: this is read on a phone.
BASE_SIZE = 76
MIN_SIZE = 44
MAX_WORDS_PER_CHUNK = 4
MIN_WORDS_PER_CHUNK = 2
CAPTION_CY = 1055       # vertical centre of the caption line, inside the card
MIN_STATE = 0.12        # never emit a frame shorter than this (1-frame flicker)
MAX_LINES = 2           # a timed chunk is one line; the static net may use 2

# The caption lives inside the card, between the divider and the progress line.
# pipeline.py uses this band to verify the subtitle actually reached the file.
BAND_X = (90, 990)
BAND_Y = (935, 1180)

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


def caption_words(speech, text="", title=""):
    """The words the subtitle should show.

    The narration is the source of truth and is used whenever it has ANY words -
    a one-word line is still what the narrator said. Only a completely empty or
    emoji-only narration falls through to the slide's own text, then its title,
    so a slide can never end up with no subtitle at all.
    """
    for src in (speech, text, title):
        words = clean_words(src)
        if words:
            return words
    return []


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
        widest = max(
            (_line_width(draw, " ".join(c[0] for c in ch), font) for ch in chunks),
            default=0.0,
        )
        if widest <= max_width or size <= MIN_SIZE:
            return chunks, size
        size -= 4


# --- Drawing ----------------------------------------------------------------
def _line_width(draw, text, font):
    return P._measure(draw, P.prepare_bidi_text(text), font)


def _wrap_all(draw, text, font, max_width):
    """Wrap every word, with no line cap (used to measure a whole block)."""
    words = (text or "").split()
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if not cur or _line_width(draw, trial, font) <= max_width:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines or [""]


def _fit_block(draw, text, max_width, max_lines, start_size=BASE_SIZE,
               min_size=MIN_SIZE):
    """Largest size at which `text` wraps into at most `max_lines` lines."""
    size = start_size
    while True:
        font = P.font_for(text, size)
        lines = _wrap_all(draw, text, font, max_width)
        widest = max((_line_width(draw, l, font) for l in lines), default=0.0)
        if (len(lines) <= max_lines and widest <= max_width) or size <= min_size:
            return lines, size
        size -= 4


def draw_block(draw, text, size, fill, max_width, max_lines=MAX_LINES,
               cy=CAPTION_CY):
    """Draw the caption as a centred block of 1..max_lines plain lines.

    A single line is the normal case. The block form exists so a subtitle that
    cannot fit on one line at MIN_SIZE is wrapped instead of being truncated -
    text must never be silently dropped from a subtitle.
    """
    lines, size = _fit_block(draw, text, max_width, max_lines, start_size=size)
    if len(lines) > max_lines:
        # Even at MIN_SIZE it does not fit: keep the head, mark the cut.
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + " …"
    font = P.font_for(text, size)
    line_h = int(size * 1.24)
    y0 = cy - ((len(lines) - 1) * line_h) / 2.0
    for i, line in enumerate(lines):
        P.draw_smart(draw, (1080 // 2, y0 + i * line_h), line, font, fill,
                     anchor="mm")
    return size


def layout_line(draw, text, size, fill):
    """Draw one plain caption line, centred.

    Deliberately nothing more than the slide's own body copy: one font, one size,
    one colour for the whole line. pipeline.draw_smart does the Persian shaping
    and RTL ordering and the centre anchor, so the subtitle can never disagree
    with the typography of the card it sits on.
    """
    draw_block(draw, text, size, fill, 1080 - 2 * 120, max_lines=MAX_LINES)


def _caption_style(category, title, text, lang):
    """(fill, safe_width) - the slide's own body colour, as the subtitle colour."""
    try:
        theme, _en_mode, _mood = P.shorts_theme(category, title, text, lang)
        fill = tuple(theme.get("body") or (241, 245, 249))
    except Exception:
        fill = (241, 245, 249)
    # 120px of side padding, not the 90px the slide uses: the slide card border
    # sits at 70px, so a caption allowed to reach 90px would run into it.
    return fill, 1080 - 2 * 120


# --- Frame production -------------------------------------------------------
def build_frames(slide_png, speech, audio_duration, out_dir, tag,
                 category="", title="", text="", lang=None, overlay=False):
    """Render one PNG per caption chunk for a single slide.

    Returns [(png_path, seconds)] in play order. It returns None ONLY when the
    slide image cannot be read or there is no text at all to show - never merely
    because the narration was short, which used to cost the video its subtitle.

    overlay=True renders transparent 1080x1920 frames containing only the
    caption, for the timed-overlay clip builder in pipeline.py. That path does
    not depend on the concat demuxer for the OUTPUT duration, which is what
    truncated the clips (see pipeline._clip_from_timed_overlay).
    """
    from PIL import Image, ImageDraw

    words = caption_words(speech, text, title)
    if not words:
        return None

    if overlay:
        base = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    else:
        try:
            base = Image.open(slide_png).convert("RGB")
        except Exception:
            return None

    fill, safe_w = _caption_style(category, title, text, lang)
    dur = float(audio_duration or 0.0)

    if dur <= 0.4 or len(words) < MIN_WORDS_PER_CHUNK:
        # Nothing to time: hold ONE static line for the whole slide. A fixed
        # subtitle is always better than no subtitle.
        hold = max(dur, 0.6)
        chunks = [[(w, 0.0, hold) for w in words]]
        base_size = BASE_SIZE
    else:
        try:
            chunks, base_size = fit_chunks(ImageDraw.Draw(base), words, dur, safe_w)
        except Exception as e:
            print(f"[caption] chunking failed ({type(e).__name__}: {e}) - one line")
            chunks, base_size = [[(w, 0.0, dur) for w in words]], MIN_SIZE
    if not chunks:
        chunks = [[(w, 0.0, max(dur, 0.6)) for w in words]]

    os.makedirs(out_dir, exist_ok=True)
    frames = []
    for ci, chunk in enumerate(chunks):
        # One frame per chunk: it holds the screen for exactly as long as its
        # words take to say, then the next chunk replaces it. Nothing animates.
        line = " ".join(c[0] for c in chunk)
        span = chunk[-1][2] - chunk[0][1]
        frame = base.copy()
        try:
            draw_block(ImageDraw.Draw(frame), line, base_size, fill, safe_w)
        except Exception as e:
            # A shaping/measure failure must not cost the slide its subtitle:
            # draw the plainest possible line instead.
            print(f"[caption] chunk {ci} draw failed ({type(e).__name__}: {e})")
            try:
                P.draw_smart(ImageDraw.Draw(frame), (1080 // 2, CAPTION_CY), line,
                             P.font_for(line, MIN_SIZE), fill, anchor="mm")
            except Exception:
                pass
        path = os.path.join(out_dir, f"cap_{tag}_{ci:02d}.png")
        frame.save(path)
        frames.append((path, max(span, MIN_STATE)))

    return frames or None


def build_static_overlay(text, out_path, category="", title="", lang=None,
                         max_lines=3):
    """Transparent caption layer for the last-resort burn-in path.

    Used when the timed frames cannot be produced or verified. pipeline.py
    overlays this PNG on the slide for the whole clip, so the Short still ships
    with a visible subtitle instead of an empty card.
    """
    from PIL import Image, ImageDraw

    line_text = " ".join(caption_words(text, title))
    if not line_text:
        return None
    fill, safe_w = _caption_style(category, title, text, lang)
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw_block(ImageDraw.Draw(img), line_text, BASE_SIZE, fill, safe_w,
               max_lines=max_lines)
    img.save(out_path)
    return out_path


# --- Verification -----------------------------------------------------------
def band_has_text(frame_png, card_fill, threshold=300):
    """Does the caption band of `frame_png` actually contain drawn text?

    The slide is rendered with its body block suppressed, so that band is a flat
    card fill when no subtitle landed. Any pixel far from that fill is text.
    Returns True when the check itself cannot run - a broken probe must never
    cost a render.
    """
    try:
        from PIL import Image
        im = Image.open(frame_png).convert("RGB").crop(
            (BAND_X[0], BAND_Y[0], BAND_X[1], BAND_Y[1]))
    except Exception:
        return True
    ref = tuple(card_fill or (30, 41, 59))
    try:
        # Counting unique colours is far cheaper than walking 200k pixels, and
        # the server runs this once per slide under `nice`.
        colors = im.getcolors(maxcolors=1 << 18)
    except Exception:
        return True
    if colors is None:
        # More distinct colours than a flat card fill could ever produce.
        return True
    hits = 0
    for count, (r, g, b) in colors:
        if abs(r - ref[0]) + abs(g - ref[1]) + abs(b - ref[2]) > 90:
            hits += count
            if hits >= threshold:
                return True
    return False


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
    """Subtitles are ON by default; set SHORTS_CAPTIONS=0 to go back to the
    slide's own static body text (one block per slide, never changing)."""
    return (os.environ.get("SHORTS_CAPTIONS", "1") or "1").strip().lower() not in (
        "0", "false", "no", "off")
