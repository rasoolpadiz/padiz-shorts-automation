# -*- coding: utf-8 -*-
"""
Padiz Global Viral Hunter Engine
Discovers trending, viral short-form videos across multiple global niches
(supercars, phone repairs, satisfying jewelry, AI, sports, psychology, viral humor),
downloads the best quality stream, applies custom Padiz branding, and publishes to Shorts.
"""

import os
import sys
import json
import time
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

# Minimum view count for a video to be considered "viral enough" to pick up.
MIN_VIEWS = int(os.environ.get("VIRAL_MIN_VIEWS", "100000"))

# Shorts must stay vertical and under 3 minutes; anything longer is trimmed.
SHORTS_MAX_SECONDS = 178

# Set VIRAL_LICENSE=creativeCommon to only pick up videos that their uploader
# published under the Creative Commons licence (safe to reuse). Left configurable
# because it shrinks the candidate pool a lot.
VIRAL_LICENSE = os.environ.get("VIRAL_LICENSE", "").strip() or None


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
            search_args = {
                "part": "id",
                "q": niche["search_query"],
                "type": "video",
                "videoDuration": "short",
                "order": "viewCount",
                "publishedAfter": published_after,
                "maxResults": 10,
            }
            if VIRAL_LICENSE:
                search_args["videoLicense"] = VIRAL_LICENSE
            req = youtube.search().list(**search_args)
            resp = req.execute()
            video_ids = [item["id"]["videoId"] for item in resp.get("items", []) if "videoId" in item.get("id", {})]
            unseen_ids = [vid for vid in video_ids if vid not in processed_ids]
            print(f"[search] {niche['category']}: {len(video_ids)} hits,"
                  f" {len(unseen_ids)} not processed yet")
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
                if views >= MIN_VIEWS:
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

class ViralDownloadBlocked(RuntimeError):
    """Raised when YouTube refuses every download attempt from this IP."""


def cookies_file():
    """yt-dlp needs a real cookie jar file to pass YouTube's bot check.

    Order of preference:
      1. ``YT_COOKIES_FILE`` env var pointing at an existing file
      2. ``YT_COOKIES_B64`` env var (GitHub Actions secret) -> decoded to disk
      3. ``yt_cookies.txt`` sitting next to this script (local / server use)
    """
    env_file = os.environ.get("YT_COOKIES_FILE")
    if env_file and os.path.exists(env_file):
        return env_file

    path = os.path.join(BASE_DIR, "yt_cookies.txt")
    b64 = os.environ.get("YT_COOKIES_B64")
    if b64 and not os.path.exists(path):
        try:
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(b64))
            print("[download] decoded YT_COOKIES_B64 -> yt_cookies.txt")
        except Exception as exc:
            print(f"[download] could not decode YT_COOKIES_B64: {exc}")
    return path if os.path.exists(path) else None


# YouTube answers yt-dlp on datacenter IPs (GitHub runners and most VPS hosts)
# with "Sign in to confirm you're not a bot". The official proof-of-origin token
# provider (a container on port 4416 + the bgutil-ytdlp-pot-provider plugin in
# requirements.txt) fixes this without any Google account; yt-dlp finds the
# token automatically. Cookies and YT_PROXY are used as well when present, and
# the different internal player clients are tried in turn as a fallback.
DOWNLOAD_ATTEMPTS = [
    ("default", None),
    ("android+web_safari", ["android", "web_safari"]),
    ("tv_embedded", ["tv_embedded"]),
    ("web_embedded", ["web_embedded"]),
    ("android_vr", ["android_vr"]),
    ("web_creator", ["web_creator"]),
    ("ios", ["ios"]),
    ("mweb", ["mweb"]),
    ("tv", ["tv"]),
]


def download_video(video_url, output_path):
    """Download ``video_url`` to ``output_path``.

    Raises :class:`ViralDownloadBlocked` with an actionable message when every
    attempt is refused, so a broken run can never be mistaken for a success.
    """
    cookie = cookies_file()
    if cookie:
        print(f"[download] using cookie file: {os.path.basename(cookie)}")
    else:
        print("[download] no cookie file found - a datacenter IP will be refused")

    # YouTube blocks datacenter IPs (GitHub runners, most VPS hosts) with
    # "Sign in to confirm you're not a bot". Pointing yt-dlp at a proxy whose
    # exit IP is not flagged avoids that without needing a cookie jar.
    proxy = os.environ.get("YT_PROXY", "").strip()
    if proxy:
        print(f"[download] routing through proxy: {proxy}")
    elif not cookie:
        print("[download] no proxy and no cookies: the download will probably be refused")

    last_error = None
    for label, clients in DOWNLOAD_ATTEMPTS:
        ydl_opts = {
            "outtmpl": output_path,
            "format": "best[ext=mp4][height<=1920]/bestvideo[height<=1920]+bestaudio/best",
            "merge_output_format": "mp4",
            "quiet": False,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 3,
            "socket_timeout": 30,
        }
        if cookie:
            ydl_opts["cookiefile"] = cookie
        if proxy:
            ydl_opts["proxy"] = proxy
        if clients:
            ydl_opts["extractor_args"] = {"youtube": {"player_client": clients}}

        try:
            print(f"[download] attempt '{label}' ...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"[download] OK via '{label}' -> {output_path}"
                      f" ({os.path.getsize(output_path)} bytes)")
                return output_path
            raise RuntimeError("yt-dlp finished but no file was produced")
        except Exception as exc:
            last_error = exc
            print(f"[download] attempt '{label}' failed: {str(exc)[:180]}")
            for leftover in (output_path + ".part", output_path):
                if os.path.exists(leftover) and os.path.getsize(leftover) == 0:
                    try:
                        os.remove(leftover)
                    except Exception:
                        pass

    raise ViralDownloadBlocked(
        "YouTube refused every download attempt from this IP address "
        f"(last error: {last_error}).\n"
        "  Fix A: export YouTube cookies to yt_cookies.txt and store the base64\n"
        "         value in the YT_COOKIES_B64 secret (works on GitHub runners).\n"
        "  Fix B: run this script on a residential IP / your own server:\n"
        "         python viral_hunter.py --once"
    )

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

    # Shorts must be vertical. Whatever aspect the source had, it is scaled to
    # cover 1080x1920 and centre-cropped, then the branding overlay is drawn on
    # top with normalised audio. The old scale2ref filter only resized the
    # overlay and left a 16:9 source landscape, which YouTube does not treat as
    # a Short at all (and silently refuses to surface).
    filter_complex = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,fps=30[base];"
        "[base][1:v]overlay=0:0,format=yuv420p[outv]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video,
        "-i", overlay_png,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-t", str(SHORTS_MAX_SECONDS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-movflags", "+faststart",
        output_video
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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

    media = MediaFileUpload(video_path, chunksize=1024 * 1024 * 4, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[upload] {int(status.progress() * 100)}%")

    vid_id = response.get("id")
    print(f"[upload] YouTube accepted the upload, video id = {vid_id}")

    # Ask YouTube what it actually did with the video. A "public" upload can
    # still end up blocked/private (content claim, region block), which looks
    # exactly like "nothing was uploaded" on the channel page.
    try:
        check = youtube.videos().list(
            part="status,contentDetails", id=vid_id
        ).execute()
        if check.get("items"):
            item = check["items"][0]
            st = item.get("status", {})
            print(f"[upload] privacyStatus={st.get('privacyStatus')}"
                  f" uploadStatus={st.get('uploadStatus')}"
                  f" rejectionReason={st.get('rejectionReason', '-')}")
            region = item.get("contentDetails", {}).get("regionRestriction")
            if region:
                print(f"[upload] WARNING - region restricted: {region}")
            if st.get("uploadStatus") != "processed":
                print("[upload] still processing - the channel will show it in a few minutes")
    except Exception as exc:
        print(f"[upload] could not verify status (harmless): {exc}")

    return f"https://www.youtube.com/shorts/{vid_id}"

def _remember_error(message):
    """Keep the last failure next to the script so it is visible without the
    Actions log (the runner's log is only reachable through the website)."""
    try:
        with open(os.path.join(BASE_DIR, "viral_last_error.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}\n")
    except Exception:
        pass


def run_viral_hunter_job(dry_run=False):
    """Find -> download -> brand -> upload one viral Short.

    With ``dry_run=True`` it stops after producing the branded file, so the whole
    path can be tested on a runner without publishing anything.

    Returns the published URL, or None when nothing met the criteria. A refused
    download raises :class:`ViralDownloadBlocked` after printing a loud banner,
    so the caller can never mistake it for a silent "nothing to publish".
    """
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
    keep = os.environ.get("KEEP_VIRAL_FILES") == "1"

    try:
        print("Downloading video stream...")
        download_video(candidate["url"], raw_path)

        print("Applying Padiz branding (vertical 1080x1920)...")
        apply_padiz_branding(raw_path, branded_path)

        if dry_run:
            size = os.path.getsize(branded_path)
            print("=" * 60)
            print("DRY RUN OK - branded file ready:", branded_path, f"({size} bytes)")
            print("Nothing was uploaded and the video id was not recorded.")
            print("=" * 60)
            return f"DRY_RUN:{branded_path}"

        print("Uploading branded viral video to YouTube channel @padiz...")
        short_url = upload_to_youtube(branded_path, niche["title_fa"], niche["desc_fa"], niche["tags"])

        save_processed_id(vid_id)
        print("=" * 50)
        print("SUCCESSFULLY PUBLISHED VIRAL SHORT!")
        print("Published URL:", short_url)
        print("=" * 50)
        return short_url
    except ViralDownloadBlocked as exc:
        print("!" * 60)
        print("VIRAL HUNTER FAILED: YouTube blocked the download from this machine.")
        print(exc)
        print("!" * 60)
        _remember_error(f"download blocked for {candidate['url']}: {exc}")
        raise
    except Exception as exc:
        print("!" * 60)
        print(f"VIRAL HUNTER FAILED at {type(exc).__name__}: {exc}")
        print("!" * 60)
        _remember_error(f"{type(exc).__name__} for {candidate['url']}: {exc}")
        raise
    finally:
        if not keep:
            for p in [raw_path, branded_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
        else:
            print("[viral] KEEP_VIRAL_FILES=1 -> keeping", raw_path, branded_path)


USAGE_TEXT = """\
Global Viral Hunter - usage:

  python viral_hunter.py --once             find + download + brand + upload one Short
  python viral_hunter.py --dry-run          find + download + brand only (no upload, file kept)
  python viral_hunter.py --url <yt url>     download and brand one specific video
  python viral_hunter.py --url <url> --upload
  python viral_hunter.py --list-niches      list the search niches

Environment variables:
  YT_COOKIES_B64 / YT_COOKIES_FILE  cookie jar for YouTube's bot check
  VIRAL_MIN_VIEWS                   view threshold (default 100000)
  VIRAL_LICENSE=creativeCommon      only Creative Commons videos
  KEEP_VIRAL_FILES=1                keep the downloaded/branded files
"""


def main(argv=None):
    """CLI: lets the hunter be run by hand on the PC / server, bypassing GitHub.

        python viral_hunter.py --once            # full find+download+brand+upload
        python viral_hunter.py --dry-run         # no upload, keeps the file
        python viral_hunter.py --url <yt url>    # brand one specific video
        python viral_hunter.py --url <url> --upload
        python viral_hunter.py --list-niches
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--list-niches" in argv:
        for n in VIRAL_NICHES:
            print(f"{n['category']:22} {n['search_query']}")
        return 0

    if "--url" in argv:
        url = argv[argv.index("--url") + 1]
        raw = os.path.join(BASE_DIR, "viral_manual_raw.mp4")
        branded = os.path.join(BASE_DIR, "viral_manual_branded.mp4")
        print(f"[manual] downloading {url}")
        download_video(url, raw)
        print("[manual] applying branding")
        apply_padiz_branding(raw, branded)
        print(f"[manual] branded -> {branded} ({os.path.getsize(branded)} bytes)")
        if "--upload" in argv:
            niche = VIRAL_NICHES[0]
            print(upload_to_youtube(branded, niche["title_fa"], niche["desc_fa"], niche["tags"]))
        else:
            print("[manual] no --upload flag, nothing was published")
        return 0

    if "--dry-run" in argv:
        os.environ["KEEP_VIRAL_FILES"] = "1"
        candidate = find_global_viral_candidate()
        if not candidate:
            print("no candidate found")
            return 1
        raw = os.path.join(BASE_DIR, f"viral_raw_{candidate['video_id']}.mp4")
        branded = os.path.join(BASE_DIR, f"viral_branded_{candidate['video_id']}.mp4")
        download_video(candidate["url"], raw)
        apply_padiz_branding(raw, branded)
        print(f"[dry-run] branded hero file ready: {branded}")
        print("[dry-run] nothing was uploaded to YouTube")
        return 0

    if "--once" not in argv:
        # Publishing costs 1600 API units and is public, so it must never be a
        # side effect of running the file without arguments.
        print(USAGE_TEXT)
        return 2

    print(run_viral_hunter_job())
    return 0


if __name__ == "__main__":
    sys.exit(main())
