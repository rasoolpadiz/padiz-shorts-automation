import os
import sys
import json
import asyncio
import subprocess
import pickle
import re
from PIL import Image, ImageDraw, ImageFont
from PIL import features as pil_features
import arabic_reshaper
from bidi.algorithm import get_display
import edge_tts
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(BASE_DIR, "Vazirmatn-Bold.ttf")
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")

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

def create_slide_image(category: str, title: str, text: str, slide_num: int, total_slides: int, output_path: str):
    width, height = 1080, 1920
    img = Image.new("RGB", (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (width, 24)], fill=(239, 68, 68))

    badge_font = ImageFont.truetype(FONT_PATH, 38)
    badge_label = f"{category} | Padiz Studio" if category else "Padiz Studio"
    draw_persian(draw, (width // 2, 220), badge_label, badge_font, (148, 163, 184))

    card_margin = 70
    card_top = 400
    card_bottom = 1500
    draw.rounded_rectangle([(card_margin, card_top), (width - card_margin, card_bottom)], radius=40, fill=(30, 41, 59), outline=(51, 65, 85), width=4)

    title_font = ImageFont.truetype(FONT_PATH, 54)
    draw_persian(draw, (width // 2, card_top + 130), title, title_font, (250, 204, 21))

    draw.line([(card_margin + 60, card_top + 210), (width - card_margin - 60, card_top + 210)], fill=(71, 85, 105), width=2)

    content_font = ImageFont.truetype(FONT_PATH, 46)
    words = text.split()
    lines, curr_line = [], []
    for word in words:
        test_line = " ".join(curr_line + [word])
        if len(test_line) > 26:
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
        draw_persian(draw, (width // 2, y), line, content_font, (241, 245, 249))

    progress_font = ImageFont.truetype(FONT_PATH, 34)
    draw_persian(draw, (width // 2, card_bottom - 70), f"نکته {slide_num} از {total_slides}", progress_font, (148, 163, 184))

    sub_font = ImageFont.truetype(FONT_PATH, 42)
    draw.rounded_rectangle([(140, 1620), (width - 140, 1740)], radius=30, fill=(220, 38, 38))
    draw_persian(draw, (width // 2, 1680), "برای دانستنی‌های بیشتر دنبال کنید", sub_font, (255, 255, 255))

    img.save(output_path, quality=95)

async def generate_speech(text: str, voice: str, output_path: str):
    communicator = edge_tts.Communicate(text, voice, rate="+5%", pitch="+0Hz")
    await communicator.save(output_path)

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
    slides = topic_data["slides"]
    total = len(slides)
    clip_files = []

    for idx, slide in enumerate(slides, start=1):
        img_path = os.path.join(work_dir, f"slide_{idx}.png")
        audio_path = os.path.join(work_dir, f"slide_{idx}.mp3")
        clip_path = os.path.join(work_dir, f"clip_{idx}.mp4")

        create_slide_image(category, slide["title"], slide["text"], idx, total, img_path)
        asyncio.run(generate_speech(slide["speech"], "fa-IR-FaridNeural", audio_path))
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
