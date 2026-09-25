# -*- coding: utf-8 -*-
"""
Small helper for the @padiz channel: list recent uploads and either unlist
(make private, reversible) or delete a video from the command line.

Usage:
    python channel_admin.py list
    python channel_admin.py unlist <VIDEO_ID>
    python channel_admin.py delete <VIDEO_ID>
"""

import os
import pickle
import sys

from googleapiclient.discovery import build

try:  # Persian titles must be printable on cp1252 Windows consoles too
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")


def youtube_client():
    if not os.path.exists(TOKEN_PATH):
        sys.exit("ERROR: token.pickle not found.")
    with open(TOKEN_PATH, "rb") as token_file:
        creds = pickle.load(token_file)
    return build("youtube", "v3", credentials=creds)


def uploads_playlist_id(youtube):
    response = youtube.channels().list(part="contentDetails", mine=True).execute()
    return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_recent(youtube, limit=20):
    playlist_id = uploads_playlist_id(youtube)
    response = youtube.playlistItems().list(
        part="snippet,contentDetails", playlistId=playlist_id, maxResults=limit
    ).execute()

    ids = [item["contentDetails"]["videoId"] for item in response["items"]]
    statuses = {}
    if ids:
        details = youtube.videos().list(part="status", id=",".join(ids)).execute()
        statuses = {item["id"]: item["status"]["privacyStatus"] for item in details["items"]}

    print(f"{'videoId':<13} {'published':<22} {'privacy':<9} title")
    for item in response["items"]:
        video_id = item["contentDetails"]["videoId"]
        snippet = item["snippet"]
        print(f"{video_id:<13} {snippet['publishedAt']:<22} "
              f"{statuses.get(video_id, '?'):<9} {snippet['title'][:60]}")


def set_privacy(youtube, video_id, privacy_status):
    youtube.videos().update(
        part="status",
        body={"id": video_id, "status": {"privacyStatus": privacy_status}},
    ).execute()
    print(f"{video_id} -> privacyStatus={privacy_status}")


def delete_video(youtube, video_id):
    youtube.videos().delete(id=video_id).execute()
    print(f"{video_id} deleted")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    command = sys.argv[1].lower()
    youtube = youtube_client()

    if command == "list":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        list_recent(youtube, limit)
    elif command == "unlist" and len(sys.argv) == 3:
        set_privacy(youtube, sys.argv[2], "private")
    elif command == "publish" and len(sys.argv) == 3:
        set_privacy(youtube, sys.argv[2], "public")
    elif command == "delete" and len(sys.argv) == 3:
        delete_video(youtube, sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
