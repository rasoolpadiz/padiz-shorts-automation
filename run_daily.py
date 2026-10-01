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
try:
    from topics_pool_en import FACTS_POOL_EN
    HAS_EN = True
except ImportError:
    FACTS_POOL_EN = []
    HAS_EN = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTED_FILE = os.path.join(BASE_DIR, "posted_shorts.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")

# Safety net: GitHub's cron can fire late, be retried, or be triggered manually
# while a scheduled run is already queued. This guard keeps at most one upload
# per slot window, so redundant triggers become harmless no-ops.
MIN_GAP_MINUTES = 90


def _today():
    """Today's UTC date, used to keep recently-posted topics out of recycling."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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
    dry_run = os.environ.get("VIRAL_DRY_RUN") == "1"
    ensure_auth()
    posted_records = load_posted()

    gap = minutes_since_last_post(posted_records)
    if gap is not None and gap < MIN_GAP_MINUTES:
        if dry_run:
            print(f"(test_only: the {MIN_GAP_MINUTES}-minute gap rule is ignored, "
                  f"last upload was {gap:.1f} minutes ago)")
        else:
            print(f"Skipping: the last Short was published {gap:.1f} minutes ago "
                  f"(minimum gap between uploads is {MIN_GAP_MINUTES} minutes).")
            print("Nothing to do - safe exit.")
            return

    # Alternating mode: FA run <-> EN run.
    # EN replaces the old viral-downloader: same self-made style, English audience.
    # Odd total_posted -> EN turn; even -> FA turn (FA pool untouched).
    def pick_from(pool, posted_records):
        """Fresh topic first; among fresh ones, the proven performer wins.

        Owner directive 2026-10-01: make more of what actually gets views.
        Ranking uses real YouTube numbers from analytics.py. When there is no
        data the original pool order is kept, so behaviour is unchanged.
        """
        lang = "en" if pool is FACTS_POOL_EN else "fa"
        posted_ids = {r["id"] for r in posted_records}

        def performance(item):
            """Real median views/day of this topic's category; 0 when unknown."""
            try:
                import analytics as A
                scores = A.load_scores()
            except Exception:
                return 0.0
            if not scores:
                return 0.0
            return scores.get((lang, item.get("category") or ""), 0.0)

        dynamic = []
        try:
            import gen_shorts as GS
            dynamic = [t for t in GS.load_generated()
                       if t.get("lang") == lang and not t.get("posted")
                       and t["id"] not in posted_ids]
            # تازه‌هایی که با Gemini نوشته شده‌اند جلوتر از قالب‌های آماده‌اند.
            g, fb = [t for t in dynamic if not t.get("fallback")], [t for t in dynamic if t.get("fallback")]
            dynamic = g + fb
        except Exception:
            dynamic = []

        fresh = [it for it in pool if it["id"] not in posted_ids]
        ordered = [dict(t) for t in dynamic] + [
            dict(item, lang=lang) for item in
            sorted(fresh, key=lambda it: -performance(it))
        ]
        if ordered:
            # Dynamic (freshly discovered) Shorts come first; the static pool
            # keeps its performance order underneath.
            return ordered[0]

        last_posted = {}
        for record in posted_records:
            tid = record.get("id")
            st = record.get("posted_at") or ""
            if tid not in last_posted or st > last_posted[tid]:
                last_posted[tid] = st
        print("Pool exhausted - recycling a proven performer (oldest first)...")
        # Among topics not posted in a while, prefer the ones that performed.
        eligible = [it for it in pool if last_posted.get(it["id"], "")[:10] < _today()]
        candidates = eligible or list(pool)
        best = min(candidates,
                   key=lambda it: (-performance(it), last_posted.get(it["id"], "")))
        return dict(best, lang=lang)

    total_posted = len(posted_records)
    force_lang = (os.environ.get("FORCE_LANG") or "").strip().lower()
    if force_lang in ("fa", "en"):
        is_en_turn = (force_lang == "en")
    else:
        is_en_turn = (total_posted % 2 == 1)
    if is_en_turn and not HAS_EN:
        print("English pool missing - falling back to Persian pool.")
        is_en_turn = False

    if is_en_turn:
        print("EN turn: rendering self-made English Short (viral downloader retired)...")
        candidate = pick_from(FACTS_POOL_EN, posted_records)
    else:
        print("FA turn: rendering Persian Short...")
        candidate = pick_from(FACTS_POOL, posted_records)

    print(f"Selected topic: {candidate['title']} (ID: {candidate['id']})")
    out_video = os.path.join(BASE_DIR, f"short_{candidate['id']}.mp4")

    print("Rendering video...")
    rendered_path = pipeline.build_full_short(candidate, out_video)
    print("Video rendered at:", rendered_path)

    # Theme-matched bed for both languages (FA gets its own Persian-mood tracks,
    # the old single sad track is retired).
    try:
        track = pipeline.bg_track_for(candidate)
        if track:
            rendered_path = pipeline.mix_bg_music(rendered_path, lang=candidate.get("lang", ""), track=track)
    except Exception as e:
        print(f"[music] auto-mix skipped ({e})")

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
