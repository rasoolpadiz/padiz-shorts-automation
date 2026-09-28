# -*- coding: utf-8 -*-
"""READ-ONLY diagnostic for the "viral hunter" half of the pipeline.

Nothing here uploads or deletes anything. It answers three questions:

  1. Is token.pickle valid and which channel does it belong to?
  2. What is the real status of the videos that WERE uploaded (public /
     blocked by Content ID / removed / rejected by YouTube)?
  3. Does the niche search (YouTube Data API) + yt-dlp download still work?

Run:
    python viral_debug.py            # questions 1 + 2 (cheap, read-only)
    python viral_debug.py --download # also tries niche search + yt-dlp download
"""

import os
import sys
import pickle
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def load_creds():
    from google.auth.transport.requests import Request

    if not os.path.exists(TOKEN_PATH):
        raise SystemExit("token.pickle not found - run python auth_test.py first")

    with open(TOKEN_PATH, "rb") as fh:
        creds = pickle.load(fh)

    print("has refresh_token :", bool(creds.refresh_token))
    print("has token         :", bool(creds.token))
    print("expiry            :", creds.expiry)
    print("scopes            :", sorted(creds.scopes or []))

    if not creds.valid:
        print("-> token reported invalid/expired, refreshing...")
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as fh:
            pickle.dump(creds, fh)
        print("-> refreshed OK, new expiry:", creds.expiry)
    else:
        print("-> token still valid (no refresh needed)")
    return creds


def check_channel(youtube):
    section("1) CHANNEL THAT THIS TOKEN OWNS")
    resp = youtube.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        print("!! channels().list(mine=True) returned NO channel.")
        print("   The OAuth token may belong to a Google account without a channel,")
        print("   or uploading is disabled for it.")
        return None

    ch = items[0]
    print("channel title  :", ch["snippet"]["title"])
    print("channel id     :", ch["id"])
    print("subscribers    :", ch["statistics"].get("subscriberCount"))
    print("video count    :", ch["statistics"].get("videoCount"))
    print("uploads list   :", ch["contentDetails"]["relatedPlaylists"].get("uploads"))
    return ch


def check_recent_uploads(youtube, channel):
    section("2) REAL STATUS OF RECENT UPLOADS (visible / blocked / removed?)")
    uploads = (channel or {}).get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads:
        print("no uploads playlist on channel")
        return

    items = youtube.playlistItems().list(
        part="contentDetails", playlistId=uploads, maxResults=25
    ).execute().get("items", [])
    ids = [i["contentDetails"]["videoId"] for i in items]
    if not ids:
        print("uploads playlist is EMPTY - nothing published from this token")
        return

    print(f"(most recent {len(ids)} uploads)\n")
    details = youtube.videos().list(
        part="snippet,status,contentDetails,statistics", id=",".join(ids)
    ).execute()

    for v in details.get("items", []):
        st = v.get("status", {})
        cd = v.get("contentDetails", {})
        sn = v.get("snippet", {})
        print(f"{sn.get('publishedAt','')[:19]}  {v['id']}  {sn.get('title','')[:58]}")
        print(f"    privacy={st.get('privacyStatus')} upload={st.get('uploadStatus')}"
              f" rejection={st.get('rejectionReason', '-')} failure={st.get('failureReason', '-')}")
        print(f"    views={v.get('statistics',{}).get('viewCount','0')}"
              f" regionRestriction={cd.get('regionRestriction', '-')}"
              f" licensedContent={cd.get('licensedContent')}")

    listed = {v["id"] for v in details.get("items", [])}
    missing = [vid for vid in ids if vid not in listed]
    if missing:
        print("\n!! These IDs sit in the uploads playlist but videos().list no longer")
        print("   returns them (removed by YouTube / deleted / channel strike):")
        for mid in missing:
            print("   -", mid)


def check_search():
    section("3) NICHE SEARCH VIA YOUTUBE DATA API (read-only, ~100 units/niche)")
    import viral_hunter

    try:
        candidate = viral_hunter.find_global_viral_candidate()
    except Exception:
        print("!! find_global_viral_candidate() raised:")
        traceback.print_exc()
        return None

    if not candidate:
        print("-> No candidate found. Either the search API returned nothing")
        print("   (quota / restrictions / queries too narrow), every hit was already")
        print("   processed (processed_reels.json), or views were below 100k.")
        return None

    print(f"-> candidate: {candidate['url']}  views={candidate['views']:,}"
          f"  niche={candidate['niche']['category']}")
    return candidate


def check_download(candidate):
    section("4) yt-dlp DOWNLOAD TEST")
    import viral_hunter

    url = (candidate or {}).get("url") or "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    print("url:", url)
    out = os.path.join(BASE_DIR, "debug_dl_test.mp4")
    try:
        viral_hunter.download_video(url, out)
        size = os.path.getsize(out) if os.path.exists(out) else 0
        print("download OK ->", out, size, "bytes")
    except Exception as exc:
        print("download FAILED:", type(exc).__name__, exc)
        print("(yt-dlp bot-check / 403 / geo-block problems surface here)")
    finally:
        if os.path.exists(out):
            try:
                os.remove(out)
            except Exception:
                pass


def main():
    print("youtube_pipeline viral-path diagnostic -", BASE_DIR)
    section("0) TOKEN")
    creds = load_creds()

    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=creds)
    channel = check_channel(youtube)
    check_recent_uploads(youtube, channel)

    if "--download" in sys.argv:
        candidate = check_search()
        check_download(candidate)
    else:
        print("\n(pass --download to also test niche search + yt-dlp download)")


if __name__ == "__main__":
    main()

