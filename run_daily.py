# -*- coding: utf-8 -*-
"""
Main entry point for automated execution (runs both in GitHub Actions and locally).
Picks a fresh unposted Persian fact Short, renders it, and uploads to @padiz.
Maintains state in posted_shorts.json to never repeat.
"""

import os
import sys
import json
import base64
from topics_pool import FACTS_POOL
import pipeline

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTED_FILE = os.path.join(BASE_DIR, "posted_shorts.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")

def ensure_auth():
    # If running in GitHub Actions, decode the secret token
    if not os.path.exists(TOKEN_PATH):
        token_b64 = os.environ.get("YOUTUBE_TOKEN_B64")
        if token_b64:
            print("Found YOUTUBE_TOKEN_B64 in environment. Decoding token.pickle...")
            with open(TOKEN_PATH, "wb") as f:
                f.write(base64.b64decode(token_b64))
        else:
            print("ERROR: token.pickle not found and YOUTUBE_TOKEN_B64 is not set.")
            sys.exit(1)

def load_posted():
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_posted(topic_id, url):
    posted = load_posted()
    posted.append({"id": topic_id, "url": url})
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(posted, f, ensure_ascii=False, indent=2)

def main():
    ensure_auth()
    posted_records = load_posted()
    posted_ids = {r["id"] for r in posted_records}

    candidate = None
    for item in FACTS_POOL:
        if item["id"] not in posted_ids:
            candidate = item
            break

    if not candidate:
        print("All facts in pool have been posted! Recycling oldest...")
        candidate = FACTS_POOL[0]

    print(f"Selected topic: {candidate['title']} (ID: {candidate['id']})")
    out_video = os.path.join(BASE_DIR, f"short_{candidate['id']}.mp4")

    print("Rendering video...")
    rendered_path = pipeline.build_full_short(candidate, out_video)
    print("Video rendered at:", rendered_path)

    print("Uploading to YouTube channel @padiz...")
    short_url = pipeline.upload_to_youtube(
        video_path=rendered_path,
        title=candidate["title"],
        description=candidate["description"],
        tags=candidate["tags"],
        privacy_status="public"
    )

    print("=========================================")
    print("SUCCESSFULLY PUBLISHED TO YOUTUBE SHORTS!")
    print("Video URL:", short_url)
    print("=========================================")

    save_posted(candidate["id"], short_url)

    # Clean up local video file
    if os.path.exists(rendered_path):
        try:
            os.remove(rendered_path)
        except Exception:
            pass

if __name__ == "__main__":
    main()
