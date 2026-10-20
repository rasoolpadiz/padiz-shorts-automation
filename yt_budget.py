# -*- coding: utf-8 -*-
"""Shared YouTube Data API unit budget.

A day has 10,000 units. One upload costs 1,600, so four uploads (3 Shorts + 1
long-form) already spend 6,400 before any discovery happens. Before this module
the only guard was "max 6 searches/day" inside discover.py, which had no idea how
many uploads had already run or how much a new endpoint costs - so a busy day
could spend the upload budget on searching and then fail to publish.

Rule: uploads are paid for FIRST. Everything else lives on what is left.
State lives in discovery_quota.json (shared with discover.py).
"""
import json
import os
from datetime import date, datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUOTA_PATH = os.path.join(BASE_DIR, "discovery_quota.json")

DAILY_BUDGET = int(os.environ.get("YT_DAILY_UNITS", "10000"))
UPLOAD_COST = 1600            # videos.insert
# Shorts-only channel (owner directive 2026-10-20): long-form is retired, so the
# reservation now covers Shorts alone. Keep this equal to MAX_SHORTS_PER_DAY in
# run_daily.py - reserving more starves discovery, reserving less risks running
# out of units halfway through the day's uploads.
UPLOADS_PER_DAY = int(os.environ.get("YT_UPLOADS_PER_DAY", "3"))
SAFETY_UNITS = 800            # headroom for a retry or a late catch-up run

# Cost of the endpoints the pipeline actually uses.
COST_SEARCH = 100             # search.list
COST_LIST = 1                 # videos.list / channels.list / playlistItems.list


def upload_capacity():
    """Uploads the day's unit budget allows: 10000 / 1600 = 6.

    This is the API ceiling, not the channel ceiling - a young channel can hit
    `uploadLimitExceeded` below it, which is why run_daily.py keeps its own,
    lower MAX_SHORTS_PER_DAY brake.
    """
    return DAILY_BUDGET // UPLOAD_COST


def _log(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load():
    try:
        with open(QUOTA_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(data):
    try:
        with open(QUOTA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _state():
    q = _load()
    if q.get("date") != _today():
        q = {"date": _today(), "yt_searches": 0, "units": 0, "log": []}
    q.setdefault("units", 0)
    q.setdefault("log", [])
    return q


def spent_today():
    """Total units spent today across every endpoint (uploads included)."""
    return int(_state().get("units", 0) or 0)


def search_count_today():
    """Kept for backwards compatibility with discover.py's own counter."""
    return int(_state().get("yt_searches", 0) or 0)


def add_units(n, reason=""):
    """Record a spend. `n` is the endpoint cost in units."""
    q = _state()
    q["units"] = int(q.get("units", 0) or 0) + int(n)
    if reason == "search":
        q["yt_searches"] = int(q.get("yt_searches", 0) or 0) + 1
    log = q.setdefault("log", [])
    log.append({"reason": reason, "units": int(n)})
    del log[:-40]
    _save(q)


def _count_posted(path, key="posted_at"):
    """How many things were published today (UTC date) from a state file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    today = _today()
    n = 0
    if isinstance(data, list):
        for r in data:
            stamp = str((r or {}).get(key) or "")
            if stamp[:10] == today:
                n += 1
    elif isinstance(data, dict):
        for when in (data.get("posted") or {}).values():
            if str(when)[:10] == today:
                n += 1
    return n


def uploads_done_today():
    shorts = _count_posted(os.path.join(BASE_DIR, "posted_shorts.json"))
    longs = _count_posted(os.path.join(BASE_DIR, "longform_out", "posted_long.json"))
    return shorts + longs


def remaining():
    """Units still free for non-upload work after reserving the day's uploads."""
    left = UPLOADS_PER_DAY - uploads_done_today()
    reserved = max(0, left) * UPLOAD_COST
    free = DAILY_BUDGET - spent_today() - reserved - SAFETY_UNITS
    return max(0, free)


def can_spend(n):
    return remaining() >= int(n)


def report():
    return (f"[quota] spent={spent_today()} uploads_today={uploads_done_today()} "
            f"free_for_discovery={remaining()}/{DAILY_BUDGET} "
            f"upload_cap={upload_capacity()}/day")


def main():
    _log(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
