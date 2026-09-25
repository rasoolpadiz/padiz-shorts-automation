import os
import json
import subprocess
import pickle
import yt_dlp
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_LOG = os.path.join(BASE_DIR, "processed_reels.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")
WATERMARK_TEXT = "@padiz_studio"

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

def download_instagram_reel(reel_url, output_path):
    ydl_opts = {
        'outtmpl': output_path,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([reel_url])
    return output_path

def apply_padiz_branding(input_video, output_video):
    # FFMPEG overlay: Draw semi-transparent box and @padiz_studio watermark at top-center and bottom
    filter_complex = (
        "drawbox=y=ih*0.06:color=black@0.55:width=iw:height=70:t=fill,"
        "drawtext=text='IG\\: @padiz_studio':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=h*0.06+16"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video,
        "-vf", filter_complex,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        output_video
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_video

def upload_short(video_path, title, description, tags):
    with open(TOKEN_PATH, "rb") as token_file:
        creds = pickle.load(token_file)

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:95] if "#shorts" in title else f"{title[:85]} #shorts",
            "description": f"{description}\n\n📌 پیج اینستاگرام ما: https://instagram.com/padiz_studio\n\n#shorts #padiz_studio #اکسپلور #اینستاگرام",
            "tags": tags + ["shorts", "padiz_studio", "ریلز", "اینستاگرام"],
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

if __name__ == "__main__":
    print("Instagram to YouTube Shorts Engine initialized.")
