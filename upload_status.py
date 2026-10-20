#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""وضعیت پردازش ویدیوهای آپلودشده روی یوتیوب را چک می‌کند.

تفاوت «در حال ترنسکد» با «بلاک/رد شده توسط یوتیوب» را نشان می‌دهد.

    python upload_status.py uCNQ2KvLYUY gMtfotFRA0M
    python upload_status.py --watch 300 uCNQ2KvLYUY      # هر 60 ثانیه تا 5 دقیقه
    python upload_status.py --recent                      # آخرین آپلودهای repost
"""
import argparse
import json
import os
import pickle
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")

PART = "snippet,status,processingDetails,fileDetails,statistics,contentDetails"

# وضعیت‌هایی که یعنی «یوتیوب ویدیو را قبول نکرده»
BAD_UPLOAD = {"rejected", "failed", "deleted"}
BAD_PROC = {"failed", "terminated"}


def service():
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request

    with open(TOKEN_PATH, "rb") as fh:
        creds = pickle.load(fh)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as fh:
            pickle.dump(creds, fh)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def recent_ids(limit=5):
    """آیدی آخرین ویدیوهایی که repost آپلود کرده."""
    path = os.path.join(BASE_DIR, "repost_posted.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    ids = []
    for r in rows[-limit:]:
        url = r.get("url") or ""
        vid = url.rsplit("/", 1)[-1].split("?")[0]
        if vid:
            ids.append(vid)
    return ids


def snapshot(yt, ids):
    """یک عکس لحظه‌ای از وضعیت ویدیوها برمی‌گرداند."""
    resp = yt.videos().list(part=PART, id=",".join(ids)).execute()
    items = resp.get("items", [])
    found = {it["id"] for it in items}
    out = []
    for it in items:
        st = it.get("status", {}) or {}
        pd = it.get("processingDetails", {}) or {}
        fd = it.get("fileDetails", {}) or {}
        cd = it.get("contentDetails", {}) or {}
        out.append({
            "id": it["id"],
            "title": (it.get("snippet") or {}).get("title", ""),
            "privacy": st.get("privacyStatus"),
            "upload": st.get("uploadStatus"),
            "failure": st.get("failureReason"),
            "rejection": st.get("rejectionReason"),
            "proc": pd.get("processingStatus"),
            "progress": pd.get("processingProgress") or {},
            "proc_failure": pd.get("processingFailureReason"),
            "duration": cd.get("duration"),
            "definition": cd.get("definition"),
            "duration_ms": fd.get("durationMs"),
            "views": (it.get("statistics") or {}).get("viewCount"),
            "missing": False,
        })
    for vid in ids:
        if vid not in found:
            out.append({"id": vid, "missing": True, "title": "", "upload": "GONE",
                        "proc": "-", "privacy": "-", "views": "-"})
    return out


def verdict(row):
    """نتیجه‌گیری نهایی برای هر ویدیو."""
    if row["missing"]:
        return "GONE", "ویدیو در API وجود ندارد (حذف شده یا کاملاً بلاک شده)"
    if row["upload"] in BAD_UPLOAD:
        return "REJECTED", "یوتیوب آپلود را رد کرد: %s / %s" % (
            row["failure"], row["rejection"])
    if row["proc"] in BAD_PROC:
        return "PROC_FAILED", "پردازش شکست خورد: %s" % row["proc_failure"]
    if row["proc"] == "succeeded" and row["duration"] not in (None, "P0D"):
        return "LIVE", "آماده و قابل پخش است (duration=%s, %s)" % (
            row["duration"], row["definition"])
    return "PROCESSING", "هنوز در حال ترنسکد است — طبیعی است"


def render(rows, elapsed=None):
    lines = []
    if elapsed is not None:
        lines.append("— بررسی در ثانیه %d —" % elapsed)
    for r in rows:
        code, msg = verdict(r)
        lines.append("[%s] %s" % (code, r["id"]))
        if r["title"]:
            lines.append("   %s" % r["title"][:70])
        lines.append("   upload=%s proc=%s privacy=%s views=%s" % (
            r["upload"], r["proc"], r["privacy"], r["views"]))
        if r["progress"]:
            lines.append("   progress=%s" % r["progress"])
        if r["duration_ms"]:
            lines.append("   durationMs=%s" % r["duration_ms"])
        lines.append("   → %s" % msg)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="video id ها")
    ap.add_argument("--recent", action="store_true", help="آخرین آپلودهای repost")
    ap.add_argument("--watch", type=int, default=0, metavar="SEC",
                    help="تا این تعداد ثانیه پولینگ کن (هر ۶۰ ثانیه)")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    ids = list(args.ids)
    if args.recent or not ids:
        ids = recent_ids() or ids
    if not ids:
        print("هیچ video id ای داده نشد.")
        return 2

    yt = service()
    start = time.time()

    while True:
        try:
            rows = snapshot(yt, ids)
        except Exception as exc:  # noqa: BLE001
            print("خطا در videos.list:", exc)
            return 1

        elapsed = int(time.time() - start)
        print(render(rows, elapsed if args.watch else None), flush=True)

        done = all(verdict(r)[0] in ("LIVE", "REJECTED", "PROC_FAILED", "GONE")
                   for r in rows)
        if done or not args.watch or elapsed >= args.watch:
            break
        print("... %d ثانیه صبر می‌کنم\n" % args.interval, flush=True)
        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    sys.exit(main())
