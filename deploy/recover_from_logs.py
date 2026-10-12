"""Recover publish records that were dropped, from the server's run logs.

Every upload is still recorded in /var/log/padiz_short.log and padiz_long.log,
so a publish record that got lost can be reconstructed from there.

THE TWO STATE FILES HAVE DIFFERENT SHAPES - this matters:
    posted_shorts.json  -> a LIST of {id, url, posted_at}
    longform_out/posted_long.json -> a DICT
        {"posted": {topic_id: "YYYY-MM-DD"}, "counts": {...}, "note": "..."}
An earlier version of this script assumed a list for both and overwrote
posted_long.json, destroying the seeded topic records. Both shapes are handled
explicitly now, and an unreadable file is left alone rather than replaced.

Only ever ADDS. Existing records are never modified or removed.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHORT_LOG = "/var/log/padiz_short.log"
LONG_LOG = "/var/log/padiz_long.log"

SHORT_RUN_RE = re.compile(r"====\s*short run\s+(\d{8}_\d{6})")
LONG_RUN_RE = re.compile(r"====\s*long run\s+(\d{8}_\d{6})")
TOPIC_ID_RE = re.compile(r"\(ID:\s*([^)]+)\)")
SHORT_URL_RE = re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})")
LONG_URL_RE = re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]{6,})")
LONG_DONE_RE = re.compile(r"\[long\]\s*done:.*/long_(.+?)\.mp4")


def _stamp(ts):
    try:
        return datetime.strptime(ts, "%Y%m%d_%H%M%S").replace(
            tzinfo=timezone.utc).isoformat()
    except Exception:
        return ""


def _lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []


def scan_shorts():
    """[(topic_id, url, iso_timestamp)] from the Shorts log."""
    out, when, topic = [], "", ""
    for line in _lines(SHORT_LOG):
        m = SHORT_RUN_RE.search(line)
        if m:
            when, topic = _stamp(m.group(1)), ""
            continue
        m = TOPIC_ID_RE.search(line)
        if m:
            topic = m.group(1).strip()
            continue
        m = SHORT_URL_RE.search(line)
        if m:
            vid = m.group(1)
            out.append((topic or f"short_{vid}",
                        f"https://www.youtube.com/shorts/{vid}", when))
            topic = ""
    return out


def scan_longs():
    """[(topic_id, url, iso_timestamp)] from the long-form log.

    The topic is not printed next to the upload, so it is taken from the
    `[long] done: .../long_<topic>.mp4` line of the same run.
    """
    out, when, topic = [], "", ""
    for line in _lines(LONG_LOG):
        m = LONG_RUN_RE.search(line)
        if m:
            when, topic = _stamp(m.group(1)), ""
            continue
        m = LONG_DONE_RE.search(line)
        if m:
            topic = m.group(1).strip()
            continue
        m = LONG_URL_RE.search(line)
        if m:
            vid = m.group(1)
            out.append((topic or f"long_{vid}",
                        f"https://www.youtube.com/watch?v={vid}", when))
            topic = ""
    return out


def recover_short_list(path, found):
    """posted_shorts.json is a LIST. Union by upload URL."""
    if not os.path.exists(path):
        existing = []
    else:
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except ValueError:
            print(f"[recover] {path}: unreadable JSON - left untouched")
            return 0
        if not isinstance(existing, list):
            print(f"[recover] {path}: expected a list, found "
                  f"{type(existing).__name__} - left untouched")
            return 0

    seen = {str(r.get("url")) for r in existing if isinstance(r, dict)}
    added = 0
    for topic, url, when in found:
        if url in seen:
            continue
        existing.append({"id": topic, "url": url, "posted_at": when,
                         "recovered_from": "server log"})
        seen.add(url)
        added += 1
        print(f"  + short {url}  ({topic[:44]})")
    if added:
        try:
            existing.sort(key=lambda d: str(d.get("posted_at", "")))
        except Exception:
            pass
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(f"[recover] {os.path.basename(path)}: {len(existing)} records, +{added}")
    return added


def recover_long_dict(path, found):
    """posted_long.json is a DICT: {"posted": {topic: date}, "counts": {...}}.

    A topic missing from `posted` is the thing that causes a re-upload, so a
    missing topic is added. Topics already present are left exactly as they are -
    the selector only cares that the id is there.
    """
    if not os.path.exists(path):
        print(f"[recover] {path}: missing - nothing to merge into")
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError:
        print(f"[recover] {path}: unreadable JSON - left untouched")
        return 0
    if not isinstance(data, dict):
        print(f"[recover] {path}: expected a dict, found "
              f"{type(data).__name__} - left untouched")
        return 0

    posted = data.setdefault("posted", {})
    counts = data.setdefault("counts", {})
    added = 0
    for topic, url, when in found:
        if topic in posted:
            continue
        posted[topic] = (when[:10] if when
                         else datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        counts[topic] = counts.get(topic, 0) + 1
        added += 1
        print(f"  + long  {url}  -> posted['{topic}']")
    if added:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
    print(f"[recover] {os.path.basename(path)}: {len(posted)} topics, +{added}")
    return added


def main():
    total = 0
    total += recover_short_list(os.path.join(BASE_DIR, "posted_shorts.json"),
                                scan_shorts())
    total += recover_long_dict(os.path.join(BASE_DIR, "longform_out",
                                            "posted_long.json"), scan_longs())
    print(f"[recover] total recovered: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
