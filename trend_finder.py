# -*- coding: utf-8 -*-
"""Find the best Shorts topics from what is ACTUALLY trending - cheaply.

Owner directive 2026-10-13: stop guessing. Every Short should be built on a topic
with proven demand and low competition, and the hunt for it must never eat the
upload budget.

Why not the trending chart: `videos.list?chart=mostPopular&regionCode=IR` is
REJECTED by the API - "the regionCode parameter specifies an invalid region code"
(verified live 2026-10-13; US/TR/AE work, IR does not). Iran has no mostPopular
chart. So the trending signal comes from `search.list` ordered by view count over
the last week, which returns genuinely fresh, high-demand Persian videos.

Cost model (YouTube Data API v3 default: 10,000 units/day)
    videos.insert   1600 units  <- ONE upload. Four a day = 6,400 units.
    search.list      100 units  <- the trending sweep (6 niches = 600 units)
    videos.list        1 unit   <- statistics for up to 50 videos at once
    channels.list      1 unit   <- average-views baseline, up to 50 channels
A full sweep costs ~602 units and still leaves ~2,000 free after the day's
uploads are paid for (see yt_budget).

The signal is the OUTLIER score: a video's views divided by its own channel's
average views per video. A small channel whose clip pulled 10x its usual audience
proves demand the big channels have not already saturated - a far better "best
topic" than a raw view count, which just re-finds the same giants every day.
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_PATH = os.path.join(BASE_DIR, "trend_pool.json")

sys.path.insert(0, BASE_DIR)

DAYS_BACK = int(os.environ.get("TREND_DAYS_BACK", "7"))
MAX_SEARCHES = int(os.environ.get("TREND_MAX_SEARCHES", "6"))
SEARCH_RESULTS = 50
MIN_VIEWS = 2000          # below this a "trending" video is noise
MIN_AVG_VIEWS = 500.0     # floor so a brand-new channel cannot fake a huge outlier
MAX_OUTLIER = 60.0        # cap absurd ratios


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
        return float(DAYS_BACK)


def _dur_seconds(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def _is_short(dur_s):
    return 0 < dur_s <= 185      # YouTube counts up to ~3 min as a Short


# --------------------------------------------------------------------------- #
# Approved niches only.
# --------------------------------------------------------------------------- #
def approved_niches():
    try:
        import topics_niches as N
        return list(getattr(N, "FA_NICHES", []) or [])
    except Exception as e:
        _log(f"[trend] niche list unavailable ({e})")
        return []


def query_for(niche):
    try:
        import discover as D
        return D.query_for(niche, "fa")
    except Exception:
        return niche


def _niche_keywords():
    hints = {}
    try:
        import discover as D
        hints = getattr(D, "FA_QUERY_HINTS", {}) or {}
    except Exception:
        pass
    out = {}
    for n in approved_niches():
        words = set()
        for src in (n, hints.get(n, "")):
            for w in _norm(src).split():
                if len(w) >= 3:
                    words.add(w)
        out[n] = words
    return out


def match_niche(title, table=None):
    """Best approved niche for a title, or '' when nothing matches."""
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
# YouTube
# --------------------------------------------------------------------------- #
def _client():
    import analytics as A
    return A._youtube_client()


def search_trending(query, days_back=None, max_results=SEARCH_RESULTS):
    """Fresh, high-view Persian videos for one query. Costs 100 units."""
    import yt_budget as B
    if not B.can_spend(B.COST_SEARCH):
        _log("[trend] unit budget exhausted - no more searches")
        return []
    yt = _client()
    since = (datetime.now(timezone.utc)
             - timedelta(days=days_back or DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        resp = yt.search().list(
            part="snippet", q=query, type="video", order="viewCount",
            publishedAfter=since, maxResults=max_results,
            relevanceLanguage="fa", regionCode="IR",
        ).execute()
    except Exception as e:
        _log(f"[trend] search {query!r} failed ({str(e)[:110]})")
        return []
    B.add_units(B.COST_SEARCH, reason="search")
    return [i for i in (resp.get("items") or []) if i.get("id", {}).get("videoId")]


def video_stats(video_ids):
    """statistics + contentDetails for up to 50 ids at a time. 1 unit per call."""
    import yt_budget as B
    ids = [v for v in dict.fromkeys(video_ids) if v]
    out = {}
    yt = _client()
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        if not B.can_spend(B.COST_LIST):
            break
        try:
            resp = yt.videos().list(
                part="statistics,contentDetails,snippet", id=",".join(chunk)).execute()
        except Exception as e:
            _log(f"[trend] videos.list failed ({str(e)[:110]})")
            break
        B.add_units(B.COST_LIST, reason="videos.list")
        for v in resp.get("items", []) or []:
            out[v["id"]] = v
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
            _log(f"[trend] channels.list failed ({str(e)[:110]})")
            break
        B.add_units(B.COST_LIST, reason="channels.list")
        for c in resp.get("items", []) or []:
            st = c.get("statistics") or {}
            total = int(st.get("viewCount", 0) or 0)
            count = int(st.get("videoCount", 0) or 0)
            if count > 0:
                out[c.get("id")] = total / float(count)
    return out


def outlier(views, avg_views):
    return min(views / max(float(avg_views or 0), MIN_AVG_VIEWS), MAX_OUTLIER)


def _niche_perf():
    try:
        import analytics as A
        return A.load_scores() or {}
    except Exception:
        return {}


def _rank_niches():
    """Approved niches, best-performing first, so the few searches we can afford
    are spent on the niches this channel already proves it can win."""
    niches = approved_niches()
    perf = _niche_perf()
    def score(n):
        try:
            return -float(perf.get(("fa", n), 0.0) or 0.0)
        except Exception:
            return 0.0
    return sorted(niches, key=score)


def discover(save=True, niches=None, max_searches=None):
    """Sweep trending inside approved niches, score it, return the ranked list."""
    import yt_budget as B
    _log(f"[trend] {B.report()}")
    free = B.remaining()
    affordable = free // B.COST_SEARCH
    budget_searches = max_searches if max_searches is not None else MAX_SEARCHES
    budget_searches = max(0, min(budget_searches, affordable))
    if budget_searches <= 0:
        _log("[trend] not enough unit budget for a sweep - skipping (uploads come first)")
        return []

    targets = list(niches or _rank_niches())[:budget_searches]
    _log(f"[trend] sweeping {len(targets)} niches ({budget_searches} searches, "
         f"~{budget_searches * B.COST_SEARCH} units)")

    found, seen = [], set()
    for niche in targets:
        for hit in search_trending(query_for(niche)):
            vid = hit["id"]["videoId"]
            if vid in seen:
                continue
            seen.add(vid)
            found.append((niche, vid))
    if not found:
        _log("[trend] no candidates found")
        return []

    stats = video_stats([vid for _n, vid in found])
    baselines = channel_baselines(
        [(stats.get(vid, {}).get("snippet") or {}).get("channelId", "")
         for _n, vid in found])

    perf = _niche_perf()
    table = _niche_keywords()
    items = []
    for niche, vid in found:
        v = stats.get(vid)
        if not v:
            continue
        st = v.get("statistics") or {}
        sn = v.get("snippet") or {}
        cd = v.get("contentDetails") or {}
        views = int(st.get("viewCount", 0) or 0)
        if views < MIN_VIEWS:
            continue
        cid = sn.get("channelId", "")
        avg = baselines.get(cid, 0.0)
        out = outlier(views, avg)
        age = _iso_days(sn.get("publishedAt"))
        dur = _dur_seconds(cd.get("duration"))
        fresh = max(0.35, 1.0 - age / 45.0)
        try:
            p = float(perf.get(("fa", niche), 0.0) or 0.0)
        except Exception:
            p = 0.0
        fit = 0.75 + min(max(p, 0.0), 12.0) / 12.0 * 0.5
        # A Short that already overperformed is the strongest possible proof that
        # this story works in short form; a long video is a weaker (but valid) hint.
        form = 1.15 if _is_short(dur) else 0.95
        score = round(math.log10(out + 1.0) * fresh * fit * form, 4)
        items.append({
            "video_id": vid, "title": sn.get("title", ""),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "views": views, "likes": int(st.get("likeCount", 0) or 0),
            "comments": int(st.get("commentCount", 0) or 0),
            "channel": sn.get("channelTitle", ""), "channel_id": cid,
            "avg_views": round(avg), "outlier": round(out, 2),
            "published_at": sn.get("publishedAt", ""), "age_days": round(age, 1),
            "duration_s": dur, "is_short": _is_short(dur),
            "niche": match_niche(sn.get("title", ""), table) or niche,
            "score": score, "source": "youtube_search_trending", "lang": "fa",
        })

    items.sort(key=lambda i: -i["score"])
    pool = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "days_back": DAYS_BACK, "searches": len(targets),
        "units_spent_today": B.spent_today(), "count": len(items), "items": items,
    }
    if save:
        try:
            _json_save(POOL_PATH, pool)
        except OSError as e:
            _log(f"[trend] could not write pool ({e})")
    for i in items[:10]:
        _log(f"[trend] {i['score']:6.3f} x{i['outlier']:<6} {i['views']:>10,} "
             f"avg {i['avg_views']:>9,} {'S' if i['is_short'] else 'L'} "
             f"{i['age_days']:>4}d  {i['niche'][:20]:20} {i['title'][:40]}")
    if not items:
        _log("[trend] nothing matched an approved niche this sweep")
    _log(f"[trend] {len(items)} scored -> {POOL_PATH} | {B.report()}")
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
    out = {}
    for it in (load_pool().get("items") or []):
        n = it.get("niche")
        if n and it.get("score", 0) > out.get(n, 0):
            out[n] = it["score"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cheap trending + outlier discovery")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--searches", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)
    items = discover(save=not args.no_save, max_searches=args.searches)
    if args.json:
        print(json.dumps(items[:args.top], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
