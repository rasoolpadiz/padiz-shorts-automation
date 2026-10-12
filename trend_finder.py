# -*- coding: utf-8 -*-
"""Find the best Shorts topics from what is ACTUALLY trending - cheaply.

Owner directive 2026-10-13: stop guessing. Every Short should be built on a topic
with proven demand and low competition, and the hunt for it must never eat the
upload budget.

Cost model (YouTube Data API v3 default: 10,000 units/day)
    videos.insert   1600 units  <- ONE upload. Four a day = 6,400 units.
    search.list      100 units  <- what the old discover.py spent per niche
    videos.list        1 unit   <- chart=mostPopular IS the trending feed
    channels.list      1 unit   <- batched, up to 50 channel ids in ONE call
A full sweep here costs ~8 units (six mostPopular calls + two channel batches),
i.e. about 1/12th of a single search.list call. That is what makes real trending
data affordable on a free budget.

The signal is the OUTLIER score: a video's views divided by its own channel's
average views per video. A small channel whose clip pulled 10x its usual audience
proves demand that the big channels have not already saturated - a much better
"best topic" than a raw view count, which just re-finds the same giants.
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_PATH = os.path.join(BASE_DIR, "trend_pool.json")

sys.path.insert(0, BASE_DIR)

REGION = os.environ.get("TREND_REGION", "IR")
# Categories that map onto this channel's approved niches. Entertainment,
# Education, Science & Tech, People & Blogs, Comedy, News & Politics,
# Pets & Animals, Travel & Events.
CATEGORIES = [24, 27, 28, 22, 23, 25, 15, 19]
MAX_RESULTS = 50
MIN_VIEWS = 2000          # below this a "trending" video is noise
MIN_AVG_VIEWS = 500.0     # floor so a brand-new channel cannot fake a huge outlier
MAX_OUTLIER = 60.0        # cap absurd ratios (a 12-view channel with 1 video)


def _log(msg):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def _json_load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _json_save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _norm(s):
    s = str(s or "").replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    return s.replace("ي", "ی").replace("ك", "ک").lower()


def _iso_days(published, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        when = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (now - when).total_seconds() / 86400.0)
    except Exception:
        return 15.0


def _dur_seconds(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


# --------------------------------------------------------------------------- #
# Niche matching: keep every topic inside an OWNER-APPROVED niche.
# --------------------------------------------------------------------------- #
def _niche_keywords():
    niches = []
    try:
        import topics_niches as N
        niches = list(getattr(N, "FA_NICHES", []) or [])
    except Exception as e:
        _log(f"[trend] niche list unavailable ({e})")
    hints = {}
    try:
        import discover as D
        hints = getattr(D, "FA_QUERY_HINTS", {}) or {}
    except Exception:
        pass
    out = {}
    for n in niches:
        words = set()
        for src in (n, hints.get(n, "")):
            for w in _norm(src).split():
                if len(w) >= 3:
                    words.add(w)
        out[n] = words
    return out


def match_niche(title, table=None):
    """Best approved niche for a trending title, or '' when nothing matches."""
    table = table if table is not None else _niche_keywords()
    toks = set(w for w in _norm(title).split() if len(w) >= 3)
    if not toks:
        return ""
    best, best_hits = "", 0
    for niche, words in table.items():
        hits = len(toks & words)
        if hits > best_hits:
            best, best_hits = niche, hits
    return best if best_hits >= 1 else ""


# --------------------------------------------------------------------------- #
# YouTube (1-unit endpoints only)
# --------------------------------------------------------------------------- #
def _client():
    import analytics as A
    return A._youtube_client()


def fetch_trending(categories=None, region=None, budget=None):
    """mostPopular per category. 1 unit per call."""
    import yt_budget as B
    categories = categories or CATEGORIES
    region = region or REGION
    yt = _client()
    out = []
    for cat in categories:
        if budget is not None and budget <= 0:
            _log("[trend] budget exhausted - stopping trending sweep")
            break
        if not B.can_spend(B.COST_LIST):
            _log("[trend] unit budget exhausted - stopping trending sweep")
            break
        try:
            resp = yt.videos().list(
                part="snippet,statistics,contentDetails",
                chart="mostPopular", regionCode=region,
                videoCategoryId=str(cat), maxResults=MAX_RESULTS,
            ).execute()
        except Exception as e:
            _log(f"[trend] mostPopular cat={cat} failed ({str(e)[:120]})")
            continue
        B.add_units(B.COST_LIST, reason="mostPopular")
        if budget is not None:
            budget -= B.COST_LIST
        for v in resp.get("items", []) or []:
            st = v.get("statistics") or {}
            sn = v.get("snippet") or {}
            cd = v.get("contentDetails") or {}
            views = int(st.get("viewCount", 0) or 0)
            if views < MIN_VIEWS:
                continue
            out.append({
                "video_id": v.get("id"),
                "title": sn.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={v.get('id')}",
                "views": views,
                "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0),
                "channel": sn.get("channelTitle", ""),
                "channel_id": sn.get("channelId", ""),
                "published_at": sn.get("publishedAt", ""),
                "duration_s": _dur_seconds(cd.get("duration")),
                "category_id": cat,
            })
    _log(f"[trend] {len(out)} trending videos across {len(categories)} categories")
    return out


def channel_baselines(channel_ids):
    """{channel_id: average views per video}. 1 unit per 50 channels."""
    import yt_budget as B
    ids = [c for c in dict.fromkeys(channel_ids) if c]
    out = {}
    yt = _client()
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        if not B.can_spend(B.COST_LIST):
            break
        try:
            resp = yt.channels().list(part="statistics", id=",".join(chunk)).execute()
        except Exception as e:
            _log(f"[trend] channels.list failed ({str(e)[:120]})")
            break
        B.add_units(B.COST_LIST, reason="channels.list")
        for c in resp.get("items", []) or []:
            st = c.get("statistics") or {}
            total = int(st.get("viewCount", 0) or 0)
            count = int(st.get("videoCount", 0) or 0)
            if count > 0:
                out[c.get("id")] = total / float(count)
    _log(f"[trend] baselines for {len(out)} channels")
    return out


def outlier(views, avg_views):
    return min(views / max(float(avg_views or 0), MIN_AVG_VIEWS), MAX_OUTLIER)


def _niche_perf():
    try:
        import analytics as A
        return A.load_scores() or {}
    except Exception:
        return {}


def score_item(item, avg_views, niche_perf):
    """Demand x freshness x channel fit. Log-compressed so one giant outlier
    cannot drown out everything else."""
    out = outlier(item["views"], avg_views)
    age = _iso_days(item.get("published_at"))
    fresh = max(0.35, 1.0 - age / 45.0)
    try:
        perf = float(niche_perf.get(("fa", item.get("niche") or ""), 0.0) or 0.0)
    except Exception:
        perf = 0.0
    fit = 0.75 + min(max(perf, 0.0), 12.0) / 12.0 * 0.5      # 0.75 .. 1.25
    return round(math.log10(out + 1.0) * fresh * fit, 4), round(out, 2), round(age, 1)


def discover(save=True, categories=None, region=None):
    """Sweep trending, score it, return the ranked list. Never raises."""
    import yt_budget as B
    budget = min(B.remaining(), 60)      # hard cap: a sweep may not exceed 60 units
    _log(f"[trend] budget {B.report()}")
    try:
        videos = fetch_trending(categories=categories, region=region, budget=budget)
    except Exception as e:
        _log(f"[trend] trending sweep failed ({e})")
        return []
    if not videos:
        return []

    try:
        baselines = channel_baselines([v["channel_id"] for v in videos])
    except Exception as e:
        _log(f"[trend] baselines failed ({e})")
        baselines = {}

    table = _niche_keywords()
    perf = _niche_perf()
    items = []
    for v in videos:
        v["niche"] = match_niche(v["title"], table)
        v["avg_views"] = round(baselines.get(v["channel_id"], 0.0))
        s, out, age = score_item(v, v["avg_views"], perf)
        v["outlier"] = out
        v["age_days"] = age
        v["score"] = s
        v["source"] = "youtube_trending"
        v["lang"] = "fa"
        items.append(v)

    items.sort(key=lambda i: -i["score"])
    pool = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region": region or REGION,
        "categories": categories or CATEGORIES,
        "units_spent_today": B.spent_today(),
        "count": len(items),
        "items": items,
    }
    if save:
        try:
            _json_save(POOL_PATH, pool)
        except OSError as e:
            _log(f"[trend] could not write pool ({e})")
    top = [i for i in items if i["niche"]][:8]
    for i in top:
        _log(f"[trend] {i['score']:6.3f}  x{i['outlier']:<6}  {i['views']:>10,}  "
             f"avg {i['avg_views']:>9,}  {i['niche'][:22]:22}  {i['title'][:44]}")
    if not top:
        _log("[trend] nothing matched an approved niche this sweep")
    return items


def load_pool():
    return _json_load(POOL_PATH, {})


def top_for_niche(niche, exclude_titles=()):
    """Best trending item inside an approved niche, skipping used stories."""
    pool = load_pool()
    if not pool:
        return None
    skip = {_norm(t) for t in exclude_titles if t}
    best = None
    for it in pool.get("items", []) or []:
        if it.get("niche") != niche:
            continue
        if _norm(it.get("title", "")) in skip:
            continue
        if best is None or it.get("score", 0) > best.get("score", 0):
            best = it
    return best


def niche_boost():
    """{niche: best score} so the writer can rank niches by real demand."""
    pool = load_pool()
    out = {}
    for it in (pool.get("items") or []):
        n = it.get("niche")
        if n and it.get("score", 0) > out.get(n, 0):
            out[n] = it["score"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cheap trending + outlier discovery")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)
    items = discover(save=not args.no_save)
    if args.json:
        print(json.dumps(items[:args.top], ensure_ascii=False, indent=2))
        return 0
    _log(f"[trend] {len(items)} scored items -> {POOL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
