"""Recover publish records that the pull dropped, from the server's run logs.

The union in merge_state.py used to key on the TOPIC id, which repeats across
publishes, so a newer publish of an already-seen topic was discarded and
posted_shorts.json fell behind reality. The logs still contain every upload, so
the missing records are reconstructed here.

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

RUN_RE = re.compile(r"====\s*short run\s+(\d{8}_\d{6})")
LONG_RUN_RE = re.compile(r"====\s*long run\s+(\d{8}_\d{6})")
ID_RE = re.compile(r"\(ID:\s*([^)]+)\)")
SHORT_URL_RE = re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})")
LONG_URL_RE = re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]{6,})")


def _stamp(ts):
    try:
        dt = datetime.strptime(ts, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return ""


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def scan(log_path, run_re, url_re, kind):
    """[(url, topic_id, posted_at)] found in the log, in order."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    out, when, topic = [], "", ""
    for line in lines:
        m = run_re.search(line)
        if m:
            when, topic = _stamp(m.group(1)), ""
            continue
        m = ID_RE.search(line)
        if m:
            topic = m.group(1).strip()
            continue
        m = url_re.search(line)
        if m:
            vid = m.group(1)
            url = (f"https://www.youtube.com/shorts/{vid}" if kind == "short"
                   else f"https://www.youtube.com/watch?v={vid}")
            out.append((url, topic or f"{kind}_{vid}", when))
            topic = ""
    return out


def merge_into(path, found, kind):
    existing = _load(path)
    seen = {str(r.get("url")) for r in existing if isinstance(r, dict)}
    added = 0
    for url, topic, when in found:
        if url in seen:
            continue
        existing.append({"id": topic, "url": url, "posted_at": when,
                         "recovered_from": "server log"})
        seen.add(url)
        added += 1
        print(f"  + {kind}: {url}  ({topic[:40]})")
    if added:
        try:
            existing.sort(key=lambda d: str(d.get("posted_at", "")))
        except Exception:
            pass
        _save(path, existing)
    print(f"[recover] {os.path.basename(path)}: {len(existing)} records, +{added} recovered")
    return added


def main():
    total = 0
    total += merge_into(os.path.join(BASE_DIR, "posted_shorts.json"),
                        scan(SHORT_LOG, RUN_RE, SHORT_URL_RE, "short"), "short")
    total += merge_into(os.path.join(BASE_DIR, "longform_out", "posted_long.json"),
                        scan(LONG_LOG, LONG_RUN_RE, LONG_URL_RE, "long"), "long")
    print(f"[recover] total recovered: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
