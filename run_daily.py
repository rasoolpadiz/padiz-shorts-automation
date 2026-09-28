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
from datetime import datetime, timezone
from topics_pool import FACTS_POOL
import pipeline
import viral_hunter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTED_FILE = os.path.join(BASE_DIR, "posted_shorts.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")

# Safety net: GitHub's cron can fire late, be retried, or be triggered manually
# while a scheduled run is already queued. This guard keeps at most one upload
# per slot window, so redundant triggers become harmless no-ops.
MIN_GAP_MINUTES = 90


def minutes_since_last_post(posted_records):
    """Minutes since the most recent upload, or None when unknown."""
    stamps = [r.get("posted_at") for r in posted_records if r.get("posted_at")]
    if not stamps:
        return None
    try:
        latest = datetime.fromisoformat(max(stamps))
    except ValueError:
        return None
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - latest).total_seconds() / 60.0

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
    posted.append({
        "id": topic_id,
        "url": url,
        "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(posted, f, ensure_ascii=False, indent=2)


def pick_next_topic(posted_records):
    """Pick a fresh topic; when the whole pool has been used, recycle the one
    that was posted the longest time ago (round-robin) so the channel never
    uploads the same topic twice in a row."""
    posted_ids = {r["id"] for r in posted_records}

    for item in FACTS_POOL:
        if item["id"] not in posted_ids:
            return item

    last_posted = {}
    for record in posted_records:
        topic_id = record.get("id")
        stamped = record.get("posted_at") or ""
        if topic_id not in last_posted or stamped > last_posted[topic_id]:
            last_posted[topic_id] = stamped

    print("All facts in pool have been posted! Recycling the oldest topic...")
    return min(FACTS_POOL, key=lambda item: last_posted.get(item["id"], ""))


def main():
    ensure_auth()
    posted_records = load_posted()

    gap = minutes_since_last_post(posted_records)
    if gap is not None and gap < MIN_GAP_MINUTES:
        print(f"Skipping: the last Short was published {gap:.1f} minutes ago "
              f"(minimum gap between uploads is {MIN_GAP_MINUTES} minutes).")
        print("Nothing to do - safe exit.")
        return

    # Alternating mode: Check how many items were posted.
    # Every 2nd run, try to hunt a Global Viral video! If not found, fallback to facts pool.
    total_posted = len(posted_records)
    viral_published = False

    if total_posted % 2 == 1:
        print("Scheduled turn for Global Viral Hunter! Scanning viral trends...")
        try:
            viral_url = viral_hunter.run_viral_hunter_job()
            if viral_url:
                viral_published = True
                save_posted(f"viral_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}", viral_url)
                print("Global Viral Short successfully published.")
                return
            else:
                print("No viral video met criteria, falling back to original Persian fact pool...")
        except viral_hunter.ViralDownloadBlocked as e:
            print("!" * 60)
            print("VIRAL TURN SKIPPED - YOUTUBE BLOCKED THE DOWNLOAD ON THIS MACHINE")
            print(e)
            print("This is the 'Sign in to confirm you're not a bot' block that hits")
            print("GitHub/AWS datacenter IPs. Add the YT_COOKIES_B64 secret, or run")
            print("`python viral_hunter.py --once` on your own PC/server.")
            print("Falling back to the fact pool so the channel still gets its video.")
            print("!" * 60)
        except Exception as e:
            print("!" * 60)
            print(f"VIRAL HUNTER ERROR ({type(e).__name__}): {e}")
            print("Falling back to the fact pool so the channel still gets its video.")
            print("!" * 60)

    candidate = pick_next_topic(posted_records)

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
