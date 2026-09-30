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


def create_scene_frame(scene, idx, total, series_title, out_path, lang="fa", bg_image=None):
    """Scene card: real photo (optional) + dark scrim + text panel + progress UI."""
    from PIL import Image, ImageDraw

    th = _long_theme(lang)
    if bg_image and os.path.exists(bg_image):
        try:
            base = _cover_crop(Image.open(bg_image).convert("RGB"), WIDTH, HEIGHT)
            scrim = Image.new("RGB", (WIDTH, HEIGHT), th["bg"])
            img = Image.blend(base, scrim, 0.66)      # keep the photo visible but dark
        except Exception as e:
            print(f"  [frame] image failed ({e}) - using flat background")
            img = Image.new("RGB", (WIDTH, HEIGHT), color=th["bg"])
    else:
        img = Image.new("RGB", (WIDTH, HEIGHT), color=th["bg"])

    draw = ImageDraw.Draw(img, "RGBA")

    draw.rectangle([(0, 0), (14, HEIGHT)], fill=th["accent"])
    draw.rectangle([(0, 0), (WIDTH, 12)], fill=th["bar"])

    # text panel (left). Bottom is kept clear for the burned-in subtitles.
    draw.rounded_rectangle([(80, 130), (1190, HEIGHT - 260)], radius=32,
                           fill=th["bg2"] + (232,), outline=th["accent"] + (255,), width=3)

    brand_font = P.font_for("Padiz", 30)
    P.draw_smart(draw, (130, 180), "PADIZ STUDIO", brand_font, th["muted"], anchor="lm")
    head_font = P.font_for(series_title, 38)
    P.draw_smart(draw, (130, 226), series_title, head_font, th["muted"], anchor="lm")

    draw.rounded_rectangle([(130, 292), (350, 366)], radius=20, fill=th["bar"])
    num_font = P.font_for("1", 38)
    label = f"Part {idx}/{total}" if (lang or "").lower().startswith("en") else f"بخش {idx} از {total}"
    P.draw_smart(draw, (240, 329), label, num_font, (255, 255, 255))

    title_font = P.font_for(scene["title"], 64)
    P.draw_smart(draw, (130, 462), scene["title"], title_font, th["head"], anchor="lm")

    body_font = P.font_for(scene["text"], 44)
    max_chars = 44 if not P.is_fa_text(scene["text"]) else 33
    words = scene["text"].split()
    lines, cur = [], []
    for w in words:
        if len(" ".join(cur + [w])) > max_chars:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))

    y = 560
    for line in lines[:5]:
        P.draw_smart(draw, (130, y), line, body_font, th["body"], anchor="lm")
        y += 64

    big_font = P.font_for("1", 280)
    P.draw_smart(draw, (1580, 400), f"{idx}", big_font, th["bg2"], anchor="mm")

    dot_y = HEIGHT - 90
    gap = 34
    start_x = WIDTH - 120 - (total - 1) * gap
    for i in range(1, total + 1):
        x = start_x + (i - 1) * gap
        r = 12
        draw.ellipse([(x - r, dot_y - r), (x + r, dot_y + r)],
                     fill=th["accent"] if i <= idx else th["bg2"],
                     outline=th["muted"], width=2)

    draw.rectangle([(0, HEIGHT - 40), (WIDTH, HEIGHT - 26)], fill=th["bg2"])
    draw.rectangle([(0, HEIGHT - 40), (int(WIDTH * idx / total), HEIGHT - 26)], fill=th["accent"])

    img.save(out_path, quality=95)
    return out_path




def create_thumbnail(topic, out_path):
    """1280x720 clickable thumbnail: big hook text + brand."""
    from PIL import Image, ImageDraw

    lang = topic.get("lang", "fa")
    th = _long_theme(lang)
    img = Image.new("RGB", (1280, 720), color=th["bg"])
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1280, 22)], fill=th["bar"])
    draw.rounded_rectangle([(60, 120), (1220, 600)], radius=30, fill=th["bg2"],
                           outline=th["accent"], width=4)

    hook = topic.get("thumbnail_text") or topic["title"].replace("#shorts", "").strip()
    hook_font = P.font_for(hook, 96)
    words = hook.split()
    lines, cur = [], []
    limit = 18 if not P.is_fa_text(hook) else 16
    for w in words:
        if len(" ".join(cur + [w])) > limit:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))

    y = 250 if len(lines) < 3 else 190
    for line in lines[:3]:
        P.draw_smart(draw, (640, y), line, hook_font, th["head"])
        y += 120

    brand_font = P.font_for("Padiz", 40)
    P.draw_smart(draw, (640, 660), "PADIZ STUDIO", brand_font, th["muted"])
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
                           bg_image=images.get(idx))

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
    create_thumbnail(topic, thumb)

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

