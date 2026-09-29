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


def draw_smart(draw, xy, text: str, font, fill, anchor: str = "mm"):
    """RTL shaping for Persian, plain LTR for English."""
    if is_fa_text(text):
        draw_persian(draw, xy, text, font, fill, anchor=anchor)
    else:
        clean = re.sub(r'[\U00010000-\U0010ffff]', '', text or '').strip()
        draw.text(xy, clean, font=font, fill=fill, anchor=anchor)

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

    title_font = font_for(title, 54)
    draw_smart(draw, (width // 2, card_top + 130), title, title_font, THEME["title"])

    draw.line([(card_margin + 60, card_top + 210), (width - card_margin - 60, card_top + 210)], fill=THEME["divider"], width=2)

    content_font = font_for(text, 46)
    max_chars = 22 if is_fa_text(text) else 30
    words = text.split()
    lines, curr_line = [], []
    for word in words:
        test_line = " ".join(curr_line + [word])
        if len(test_line) > max_chars:
            lines.append(" ".join(curr_line))
            curr_line = [word]
        else:
            curr_line.append(word)
    if curr_line:
        lines.append(" ".join(curr_line))

    line_height = 80
    total_h = len(lines) * line_height
    start_y = card_top + 340 + ((card_bottom - card_top - 420 - total_h) // 2)

    for i, line in enumerate(lines):
        y = start_y + (i * line_height)
        draw_smart(draw, (width // 2, y), line, content_font, THEME["body"])

    progress_font = font_for("test", 34)
    progress_txt = f"Fact {slide_num} of {total_slides}" if en_mode else f"نکته {slide_num} از {total_slides}"
    draw_smart(draw, (width // 2, card_bottom - 70), progress_txt, progress_font, THEME["progress"])

    sub_font = font_for("Subscribe", 42)
    draw.rounded_rectangle([(140, 1620), (width - 140, 1740)], radius=30, fill=THEME["btn"])
    sub_txt = "Subscribe so you never miss new videos!" if en_mode else "کانال رو سابسکرایب کنید تا ویدیوهای جدید رو از دست ندید"
    draw_smart(draw, (width // 2, 1680), sub_txt, sub_font, THEME["btn_text"])

    img.save(output_path, quality=95)

async def generate_voice_edge(text: str, voice: str, output_path: str):
    """Fallback Persian TTS using edge-tts."""
    communicator = edge_tts.Communicate(text, voice, rate="+5%", pitch="+0Hz")
    await communicator.save(output_path)

# Gemini reads whatever text it is given out loud, so the narration must be sent
# verbatim (wrapping it in "read this aloud: ..." can make the instruction end up
# in the audio). Delivery is steered with the speech style metadata instead.
GEMINI_STYLE_FA = (
    "Native Iranian Persian (Farsi) narration for a short documentary video. "
    "Speak Farsi with an authentic Tehrani accent, completely natural human intonation, "
    "warm and expressive, conversational pace with gentle pauses between sentences. "
    "Pronounce every Persian word correctly and never use an English or Arabic accent"
)
GEMINI_STYLE_EN = (
    "Natural, energetic and expressive American English narration for a viral Shorts video, "
    "clear pronunciation, upbeat conversational tone"
)

# Dedicated TTS models first (most natural Persian delivery), then general models
# that also accept the AUDIO response modality. The first model that answers wins;
# unsupported ones raise and are skipped. Override with GEMINI_TTS_MODEL.
#
# Free-tier notes (ai.google.dev/gemini-api/docs/pricing): the *Flash* TTS models
# are "Free of charge" on the free tier (their audio may be used to improve Google
# products), while gemini-2.5-pro-preview-tts is "Not available" without billing -
# hence it is tried last. Output audio is billed as 25 tokens per second when a
# paid key is used.
GEMINI_TTS_MODELS = [
    os.environ.get("GEMINI_TTS_MODEL", "").strip(),
    "gemini-3.8-flash-tts",             # newest free-tier TTS, best fidelity
    "gemini-3.8-flash-lite-tts",        # free-tier TTS, cheapest
    "gemini-2.5-flash-preview-tts",     # long-standing free-tier TTS
    "gemini-2.0-flash",                 # general model with AUDIO modality
    "gemini-2.5-flash",                 # general model with AUDIO modality
    "gemini-2.5-pro-preview-tts",       # paid tier only (best steering)
]

# Male voice for Farid-style slides, female voice for Dilara-style slides.
# Persian narration uses Gemini voices that render Farsi most naturally; English
# uses the classic upbeat pair. Override the Persian ones with GEMINI_FA_VOICE.
GEMINI_FA_VOICE = os.environ.get("GEMINI_FA_VOICE", "").strip() or "Charon"
GEMINI_FA_VOICE_ALT = os.environ.get("GEMINI_FA_VOICE_ALT", "").strip() or "Despina"
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


def gemini_voice_enabled() -> bool:
    """Gemini narration is used unless it is switched off by env or a prior failure."""
    if _gemini_voice_disabled:
        return False
    return os.environ.get("DISABLE_GEMINI_VOICE", "").strip().lower() not in ("1", "true", "yes", "on")


def _is_fatal_gemini_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in FATAL_GEMINI_ERROR_MARKERS)


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

    for model_name in [m for m in GEMINI_TTS_MODELS if m]:
        speech_config = gemini_speech_config(model_name, voice_name)
        for variant_index, contents in enumerate(contents_variants):
            try:
                raw_audio = attempt(model_name, speech_config, contents)
            except Exception as e:
                print(f"[Gemini TTS] {model_name} variant {variant_index} failed: {e}")
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
    print("[Gemini TTS] No Gemini model returned audio - using edge-tts for this run.")
    _disable_gemini_voice()
    return False


def generate_voice(text: str, voice: str, output_path: str):
    """Narrate ``text`` into ``output_path`` as an MP3.

    Tries Google AI Studio (Gemini) audio generation first for natural Persian
    speech, and falls back to edge-tts whenever that is unavailable or fails.
    """
    try:
        gemini_voice = gemini_voice_for(voice)
        if generate_voice_gemini(text, output_path, voice_name=gemini_voice):
            print(f"[voice] Generated with Google AI Studio (Gemini voice: {gemini_voice})")
            return
        print("[voice] Gemini voice unavailable -> falling back to edge-tts.")
    except Exception as e:
        print(f"[voice] Gemini voice error ({e}) -> falling back to edge-tts.")

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


def split_audio_by_silence(audio_path: str, parts: int, out_paths: list) -> bool:
    """Cut one narration track into `parts` clips at the longest internal pauses."""
    if parts <= 1:
        shutil.copy2(audio_path, out_paths[0])
        return True

    spans = [s for s in _detect_silences(audio_path) if s[1] - s[0] >= 0.25]
    if len(spans) < parts - 1:
        return False

    # Longest pauses are the sentence/slide boundaries.
    ranked = sorted(spans, key=lambda s: (s[1] - s[0]), reverse=True)[: parts - 1]
    cuts = sorted((s[0] + s[1]) / 2.0 for s in ranked)
    total = get_audio_duration(audio_path)

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
    gemini_voice = gemini_voice_for(voice)
    tmp_mp3 = os.path.join(BASE_DIR, "temp_render", "_batch_narration.mp3")
    os.makedirs(os.path.dirname(tmp_mp3), exist_ok=True)
    try:
        if not generate_voice_gemini(combined, tmp_mp3, voice_name=gemini_voice):
            return False
        if split_audio_by_silence(tmp_mp3, len(out_paths), out_paths):
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
