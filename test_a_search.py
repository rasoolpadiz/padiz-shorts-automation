# -*- coding: utf-8 -*-
"""
TEST A - Discovery (fully standalone).

  Search -> Video ID / URL only.  No download, no branding, no upload.

PASS criteria: at least one video ID is returned by the YouTube Data API
and written to test_a_result.json with its watch URL.

Usage:
  python test_a_search.py
  python test_a_search.py --query "#shorts satisfying phone restoration" --max 5
"""

import argparse
import base64
import json
import os
import pickle
import sys
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")
RESULT_PATH = os.path.join(BASE_DIR, "test_a_result.json")

DEFAULT_QUERY = "#shorts satisfying phone restoration repair"


def load_credentials():
    """OAuth for the channel itself - same token.pickle the pipeline uses.

    Falls back to the YOUTUBE_TOKEN_B64 secret (GitHub Actions) when the
    pickle file is absent, exactly like viral_hunter.ensure_auth().
    """
    if not os.path.exists(TOKEN_PATH):
        token_b64 = os.environ.get("YOUTUBE_TOKEN_B64", "")
        if not token_b64:
            raise RuntimeError(
                "No OAuth: token.pickle missing and YOUTUBE_TOKEN_B64 not set"
            )
        with open(TOKEN_PATH, "wb") as fh:
            fh.write(base64.b64decode(token_b64))
    with open(TOKEN_PATH, "rb") as fh:
        return pickle.load(fh)


def main(argv=None):
    parser = argparse.ArgumentParser(description="TEST A: Search -> Video ID")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max", type=int, default=5, dest="max_results")
    parser.add_argument(
        "--days", type=int, default=14,
        help="only videos published within the last N days",
    )
    args = parser.parse_args(argv)

    result = {
        "test": "A",
        "name": "search->video_id",
        "pass": False,
        "query": args.query,
        "ids": [],
        "urls": [],
        "error": None,
    }

    try:
        from googleapiclient.discovery import build

        creds = load_credentials()
        youtube = build("youtube", "v3", credentials=creds)
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=args.days)
        ).isoformat()

        resp = (
            youtube.search()
            .list(
                part="id",
                q=args.query,
                type="video",
                videoDuration="short",
                order="viewCount",
                publishedAfter=published_after,
                maxResults=args.max_results,
            )
            .execute()
        )
        ids = [
            item["id"]["videoId"]
            for item in resp.get("items", [])
            if "videoId" in item.get("id", {})
        ]
        result["ids"] = ids
        result["urls"] = [f"https://www.youtube.com/watch?v={v}" for v in ids]
        result["pass"] = bool(ids)
        if not ids:
            result["error"] = "search succeeded but returned 0 video IDs"
    except Exception as exc:  # noqa: BLE001 - the reason IS the test output
        result["error"] = f"{type(exc).__name__}: {exc}"

    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print(f"TEST A {'PASS' if result['pass'] else 'FAIL'}")
    print(f"  query: {args.query}")
    for url in result["urls"]:
        print(f"  found: {url}")
    if result["error"]:
        print(f"  error: {result['error']}")
    print(f"  result -> {RESULT_PATH}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
