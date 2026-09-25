# -*- coding: utf-8 -*-
"""
Padiz Global Viral Hunter Engine
Discovers trending, viral short-form videos across multiple global niches
(supercars, phone repairs, satisfying jewelry, AI, sports, psychology, viral humor),
downloads the best quality stream, applies custom Padiz branding, and publishes to Shorts.
"""

import os
import json
import random
import subprocess
import pickle
import base64
from datetime import datetime, timezone, timedelta
import yt_dlp
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_LOG = os.path.join(BASE_DIR, "processed_reels.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")

VIRAL_NICHES = [
    {
        "category": "luxury_cars",
        "search_query": "#shorts luxury supercar hypercar",
        "title_fa": "شاهکار ماشین‌های لوکس و سوپراسپرت دنیا 🔥",
        "desc_fa": "یکی از خاص‌ترین و گران‌ترین سوپراسپرت‌های دنیا! نظرتون چیه؟",
        "tags": ["ماشین", "ماشین_لوکس", "سوپراسپرت", "luxurycars", "supercars"]
    },
    {
        "category": "phone_repair",
        "search_query": "#shorts satisfying phone restoration repair",
        "title_fa": "تعمیر و بازسازی فوق‌العاده و لذت‌بخش موبایل 📱✨",
        "desc_fa": "بازسازی باورنکردنی و بسیار تمیز قطعات ظریف موبایل. حتماً تا آخر ببینید!",
        "tags": ["تعمیرات_موبایل", "تکنولوژی", "ترفند", "phonerepair", "restoration"]
    },
    {
        "category": "jewelry_craft",
        "search_query": "#shorts satisfying diamond jewelry making craft",
        "title_fa": "ساخت خیره‌کننده جواهرات لوکس و الماس 💎✨",
        "desc_fa": "ظرافت باورنکردنی در تراش و ساخت گران‌ترین جواهرات و طلا در جهان.",
        "tags": ["طلا", "جواهرات", "الماس", "هنر", "jewelry", "crafts", "luxury"]
    },
    {
        "category": "ai_creations",
        "search_query": "#shorts mindblowing AI video Sora Midjourney",
        "title_fa": "قدرت باورنکردنی هوش مصنوعی در ساخت ویدیو 🤖🤯",
        "desc_fa": "پیشرفت شگفت‌انگیز هوش مصنوعی! آیا تشخیص میدید این صحنه واقعی نیست؟",
        "tags": ["هوش_مصنوعی", "تکنولوژی", "آینده", "ai", "artificialintelligence"]
    },
    {
        "category": "sports_moments",
        "search_query": "#shorts insane sports moments unbelievable skills",
        "title_fa": "مهارت‌های دیوانه‌کننده و لحظات تاریخی ورزشی ⚡⚽",
        "desc_fa": "یکی از شاهکارهای غیرممکن دنیای ورزش! شانس بود یا مهارت خالص؟",
        "tags": ["ورزش", "فوتبال", "مهارت", "هیجان", "sports", "viral"]
    },
    {
        "category": "psychology_facts",
        "search_query": "#shorts mindblowing psychology facts human behavior",
        "title_fa": "فکت‌های تکان‌دهنده روانشناسی که ذهن را قفل می‌کند 🧠",
        "desc_fa": "چند راز جالب و روانشناسی درباره رفتار انسان‌ها که شاید نمی‌دانستید.",
        "tags": ["روانشناسی", "دانستنی", "فکت", "ذهن", "psychology", "facts"]
    },
    {
        "category": "viral_humor",
        "search_query": "#shorts funniest viral moments epic fails",
        "title_fa": "خنده‌دارترین اتفاقات و لحظات وایرال شده 😂🔥",
        "desc_fa": "این یکی واقعاً غیرمنتظره بود! برای ویدیوهای فان بیشتر کانال رو سابسکرایب کن.",
        "tags": ["طنز", "خنده_دار", "فان", "سوتی", "funny", "humor"]
    },
    {
        "category": "aesthetic_heartbreak",
        "search_query": "#shorts dark aesthetic sad deep quotes mood",
        "title_fa": "گاهی سکوت، زیباترین فریاد یک دل خسته است... 💔🥀",
        "desc_fa": "پر از ناگفته‌هایی که هیچ کلمه‌ای توان گفتنش را ندارد. نظرتون رو کامنت کنید.",
        "tags": ["غمگین", "دپ", "دلنوشته", "تکست_خاص", "مود", "aesthetic", "sad"]
    }

]

def ensure_auth():
    if not os.path.exists(TOKEN_PATH):
        token_b64 = os.environ.get("YOUTUBE_TOKEN_B64")
        if token_b64:
            with open(TOKEN_PATH, "wb") as f:
                f.write(base64.b64decode(token_b64))

def load_processed_ids():
    if os.path.exists(PROCESSED_LOG):
        try:
            with open(PROCESSED_LOG, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_processed_id(video_id):
    processed = load_processed_ids()
    processed.add(video_id)
    with open(PROCESSED_LOG, "w", encoding="utf-8") as f:
        json.dump(list(processed), f, ensure_ascii=False, indent=2)

def find_global_viral_candidate():
    ensure_auth()
    with open(TOKEN_PATH, "rb") as token_file:
        creds = pickle.load(token_file)

    youtube = build("youtube", "v3", credentials=creds)
    processed_ids = load_processed_ids()

    niches = list(VIRAL_NICHES)
    random.shuffle(niches)
    published_after = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

    for niche in niches:
        try:
            req = youtube.search().list(
                part="id",
                q=niche["search_query"],
                type="video",
                videoDuration="short",
                order="viewCount",
                publishedAfter=published_after,
                maxResults=10
            )
            resp = req.execute()
            video_ids = [item["id"]["videoId"] for item in resp.get("items", []) if "videoId" in item.get("id", {})]
            unseen_ids = [vid for vid in video_ids if vid not in processed_ids]
            if not unseen_ids:
                continue

            details_req = youtube.videos().list(
                part="snippet,statistics",
                id=",".join(unseen_ids)
            )
            details_resp = details_req.execute()

            for item in details_resp.get("items", []):
                vid = item["id"]
                views = int(item.get("statistics", {}).get("viewCount", 0))
                if views >= 100000:
                    return {
                        "video_id": vid,
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "views": views,
                        "niche": niche
                    }
        except Exception as e:
            print(f"Error checking niche '{niche['category']}': {e}")
            continue

    return None

def download_video(video_url, output_path):
    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo[height<=1920][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    return output_path

def generate_branding_overlay(overlay_path):
    from PIL import Image, ImageDraw, ImageFont
    overlay_img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_img)
    # Branded top translucent bar
    draw.rectangle([(0, 90), (1080, 180)], fill=(0, 0, 0, 150))
    
    # Try system fonts, fallback to default if not found
    font = None
    for fp in ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 42)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    text = "@padiz_studio"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((1080 - tw) // 2, 112), text, font=font, fill=(255, 255, 255, 240))
    overlay_img.save(overlay_path, "PNG")
    return overlay_path

def apply_padiz_branding(input_video, output_video):
    overlay_png = os.path.join(BASE_DIR, "brand_temp_overlay.png")
    generate_branding_overlay(overlay_png)

    filter_complex = "[0:v][1:v]scale2ref=iw:ih[v0][v1];[v0][v1]overlay=0:0"
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video,
        "-i", overlay_png,
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "copy",
        output_video
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        if os.path.exists(overlay_png):
            try:
                os.remove(overlay_png)
            except Exception:
                pass
    return output_video

def upload_to_youtube(video_path, title, description, tags):
    ensure_auth()
    with open(TOKEN_PATH, "rb") as token_file:
        creds = pickle.load(token_file)

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": f"{title} #shorts"[:95],
            "description": f"{description}\n\nکانال رو سابسکرایب کنید تا ویدیوهای جدید رو از دست ندید!\n\n📌 اینستاگرام: https://instagram.com/padiz_studio\n\n#shorts #padiz_studio #اکسپلور #ترند",
            "tags": tags + ["shorts", "padiz_studio", "ترند", "وایرال", "اکسپلور"],
            "categoryId": "24"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()

    vid_id = response.get("id")
    return f"https://www.youtube.com/shorts/{vid_id}"

def run_viral_hunter_job():
    print("=" * 50)
    print("Starting Global Viral Hunter...")
    print("=" * 50)
    candidate = find_global_viral_candidate()
    if not candidate:
        print("No eligible viral candidate found meeting the threshold right now.")
        return None

    vid_id = candidate["video_id"]
    views = candidate["views"]
    niche = candidate["niche"]
    print(f"Found viral video [{niche['category']}]: {candidate['url']} with {views:,} views!")

    raw_path = os.path.join(BASE_DIR, f"viral_raw_{vid_id}.mp4")
    branded_path = os.path.join(BASE_DIR, f"viral_branded_{vid_id}.mp4")

    try:
        print("Downloading video stream...")
        download_video(candidate["url"], raw_path)

        print("Applying Padiz branding...")
        apply_padiz_branding(raw_path, branded_path)

        print("Uploading branded viral video to YouTube channel @padiz...")
        title = niche["title_fa"]
        desc = niche["desc_fa"]
        tags = niche["tags"]
        short_url = upload_to_youtube(branded_path, title, desc, tags)

        save_processed_id(vid_id)
        print("=" * 50)
        print("SUCCESSFULLY PUBLISHED VIRAL SHORT!")
        print("Published URL:", short_url)
        print("=" * 50)
        return short_url
    finally:
        for p in [raw_path, branded_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

if __name__ == "__main__":
    run_viral_hunter_job()
