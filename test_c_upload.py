# -*- coding: utf-8 -*-
"""
TEST C - Upload (fully standalone).

  Local MP4 -> YouTube Data API videos.insert (official endpoint)
  https://developers.google.com/youtube/v3/docs/videos/insert

Keeps the channel's own OAuth (token.pickle / YOUTUBE_TOKEN_B64) - the same
credentials the pipeline already uses. Nothing else in the pipeline is
touched: this script never reads posted_shorts.json or processed_reels.json.

Defaults to privacyStatus=private so a test run never publishes anything;
pass --privacy public for a real publication test.

Usage:
  python test_c_upload.py                                # default sample file
  python test_c_upload.py --file some.mp4 --privacy public
"""

import argparse
import base64
import json
import os
import pickle
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")
RESULT_PATH = os.path.join(BASE_DIR, "test_c_result.json")
DEFAULT_FILE = os.path.join(BASE_DIR, "aesthetic_short_under20s.mp4")


def load_credentials():
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
    parser = argparse.ArgumentParser(description="TEST C: local MP4 -> YouTube")
    parser.add_argument("--file", default=DEFAULT_FILE)
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        default="private",
    )
    parser.add_argument("--title", default=None)
    args = parser.parse_args(argv)

    result = {
        "test": "C",
        "name": "mp4->youtube_upload",
        "pass": False,
        "file": args.file,
        "privacy": args.privacy,
        "video_id": None,
        "error": None,
    }

    if not os.path.exists(args.file):
        result["error"] = f"file not found: {args.file}"
    elif os.path.getsize(args.file) == 0:
        result["error"] = f"file is empty: {args.file}"
    else:
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            creds = load_credentials()
            youtube = build("youtube", "v3", credentials=creds)

            title = args.title or (
                "PROBE TEST C - "
                + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                + " (delete me)"
            )
            body = {
                "snippet": {
                    "title": title,
                    "description": (
                        "Independent TEST C of the padiz pipeline probe "
                        "(videos.insert). Safe to delete."
                    ),
                    "tags": ["probe", "test"],
                    "categoryId": "22",
                },
                "status": {
                    "privacyStatus": args.privacy,
                    "selfDeclaredMadeForKids": False,
                },
            }
            media = MediaFileUpload(
                args.file, mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024
            )
            request = youtube.videos().insert(
                part="snippet,status", body=body, media_body=media
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"  upload {int(status.progress() * 100)}%")
            result["video_id"] = response["id"]
            result["pass"] = True
        except Exception as exc:  # noqa: BLE001 - the reason IS the test output
            result["error"] = f"{type(exc).__name__}: {exc}"

    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print(f"TEST C {'PASS' if result['pass'] else 'FAIL'}")
    print(f"  file   : {args.file}")
    print(f"  privacy: {args.privacy}")
    if result["pass"]:
        print(f"  video  : https://youtu.be/{result['video_id']}")
    if result["error"]:
        print(f"  error  : {result['error']}")
    print(f"  result -> {RESULT_PATH}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
