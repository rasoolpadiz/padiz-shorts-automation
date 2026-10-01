# -*- coding: utf-8 -*-
"""Channel analytics feedback loop for Padiz Studio.

Owner directive (2026-10-01): analyse which videos actually get views and make
more of those topics. Reads REAL performance for everything published and lets
it steer which niche is chosen next.

Rules kept deliberately:
  * READ-ONLY - never uploads, never touches the publish workflows. The stored
    token already carries `youtube.readonly`, so no new consent or secret.
  * State lives in analytics_history.json in the repo (same pattern as
    posted_long.json), so the daily GitHub Actions run sees it for free.
  * Every consumer degrades to the OLD behaviour when data is missing, so a
    first-time or failed collection can never break a publish run.

Baseline is the median views/day (idea from channel-learning-engine.js) so one
lucky hit cannot distort the ranking; fetch pattern follows ytmetrix
ingest/analytics-sync.
"""
import base64
import json
import os
import pickle
import re
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE_DIR, "analytics_history.json")
TOKEN_PATH = os.path.join(BASE_DIR, "YOUTUBE_TOKEN_B64.txt")

MAX_DAYS = 90                 # daily snapshots kept
REPEAT_COOLDOWN_DAYS = 14     # a niche sits out this long after being used


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


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _credentials():
    """Stored OAuth credentials: base64 pickle from secrets, else the repo file."""
    raw = os.environ.get("YOUTUBE_TOKEN_B64")
    if not raw and os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, encoding="utf-8") as f:
            raw = f.read().strip()
    if not raw:
        raise RuntimeError("no YOUTUBE_TOKEN_B64 available")
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        blob = raw.encode()
    return pickle.loads(blob)


def _youtube_client():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_credentials())


def _iso_to_days(published_at, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        when = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 1
    return max(1, (now - when).days)


def _is_long(duration):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return False
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return (h * 3600 + mi * 60 + s) >= 61




def _video_ids(yt):
    """Every video on the channel via the uploads playlist (cheap list calls)."""
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        return []
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        page = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads, maxResults=50, pageToken=token
        ).execute()
        ids += [i["contentDetails"]["videoId"] for i in page.get("items", [])]
        token = page.get("nextPageToken")
        if not token:
            break
    return ids


def _channel_subs(yt):
    try:
        st = yt.channels().list(part="statistics", mine=True).execute()["items"][0]["statistics"]
        return int(st.get("subscriberCount", 0))
    except Exception:
        return None


def _fetch_stats(yt):
    """views / likes / comments per video, batched 50 ids per request."""
    rows = []
    ids = _video_ids(yt)
    for i in range(0, len(ids), 50):
        page = yt.videos().list(
            part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])
        ).execute()
        for v in page.get("items", []):
            st, sn = v.get("statistics", {}), v.get("snippet", {})
            days = _iso_to_days(sn.get("publishedAt", ""))
            views = int(st.get("viewCount", 0))
            rows.append({
                "video_id": v["id"],
                "title": sn.get("title", ""),
                "published_at": sn.get("publishedAt", ""),
                "days_live": days,
                "views": views,
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
                "views_per_day": round(views / days, 2),
                "duration": v.get("contentDetails", {}).get("duration", ""),
            })
    return rows


# --------------------------------------------------------------------------- #
# Mapping: video -> the niche / category that produced it
# --------------------------------------------------------------------------- #
def _short_index():
    """video_id -> (lang, category) for every Short we published."""
    pools = {}
    for mod_name, lang, var in (("topics_pool", "fa", "FACTS_POOL"),
                                ("topics_pool_en", "en", "FACTS_POOL_EN")):
        try:
            mod = __import__(mod_name)
            for item in getattr(mod, var, []):
                pools[item["id"]] = (lang, item.get("category") or "(uncategorised)")
        except Exception as e:
            _log(f"[analytics] {mod_name} unavailable ({e})")

    index = {}
    for rec in _json_load(os.path.join(BASE_DIR, "posted_shorts.json"), []):
        m = re.search(r"(?:shorts/|watch\?v=)([A-Za-z0-9_-]{11})", rec.get("url", ""))
        if m and rec.get("id") in pools:
            index[m.group(1)] = pools[rec["id"]]
    return index


def _long_titles():
    """title(lower) -> (lang, niche) for every long-form topic we can load."""
    try:
        import longform as L
    except Exception as e:
        _log(f"[analytics] longform unavailable ({e})")
        return {}
    out = {}
    for t in L.load_topics():
        niche = t.get("niche") or t.get("series") or "(uncategorised)"
        out[str(t.get("title", "")).strip().lower()] = (t.get("lang", ""), niche)
    return out


def annotate(rows):
    """Attach (kind, lang, niche) to every fetched video. Never raises."""
    shorts = _short_index()
    longs = _long_titles()
    for r in rows:
        vid, title = r["video_id"], (r.get("title") or "").strip()
        long_hit = _is_long(r.get("duration", ""))
        if vid in shorts:
            lang, niche = shorts[vid]
            r.update(kind="short", lang=lang, niche=niche)
        elif long_hit and title.lower() in longs:
            lang, niche = longs[title.lower()]
            r.update(kind="long", lang=lang, niche=niche)
        else:
            # Old or manual upload - still counted at channel level.
            r.update(kind="long" if long_hit else "short",
                     lang="fa" if re.search(r"[\u0600-\u06FF]", title) else "en",
                     niche="(unmapped)")
    return rows


# --------------------------------------------------------------------------- #
# Scoring - median baseline so one lucky hit cannot dominate the ranking
# --------------------------------------------------------------------------- #
def niche_scores(rows):
    """{(lang, niche): score} where 1.0 ~= the channel's median video.

    score = (median views/day of the niche) / (channel median), with a small
    engagement kicker and a confidence discount so a single video never
    outranks a proven niche. Missing data simply yields an empty dict.
    """
    if not rows:
        return {}
    baseline = _median([r.get("views_per_day") for r in rows]) or 1.0
    grouped = {}
    for r in rows:
        niche = r.get("niche")
        if not niche or niche.startswith("("):
            continue
        grouped.setdefault((r.get("lang", ""), niche), []).append(r)

    scores = {}
    for key, vids in grouped.items():
        vpd = _median([v.get("views_per_day") for v in vids])
        likes = _median([v.get("likes") for v in vids])
        raw = (vpd / baseline) * (1.0 + min(likes or 0, 50) / 250.0)
        confidence = min(1.0, len(vids) / 3.0)   # 3+ samples = fully trusted
        scores[key] = round(0.5 + (raw - 0.5) * confidence, 3)
    return scores


def _tokens(text):
    """Latin + Persian word tokens so EN and FA niches both compare cleanly."""
    return set(re.findall(r"[a-z0-9]{4,}|[\u0600-\u06FF]{4,}", str(text).lower()))


def family_score(lang, niche, scores):
    """Score for a long-form niche, borrowing signal from related Shorts.

    Shorts and long-form use two vocabularies (e.g. "Ø±ÙˆØ§Ù†Ø´Ù†Ø§Ø³ÛŒ Ø±Ø§Ø¨Ø·Ù‡" vs
    "Ø±ÙˆØ§Ù†Ø´Ù†Ø§Ø³ÛŒ Ùˆ Ø±ÙØªØ§Ø± Ø§Ù†Ø³Ø§Ù†") so an exact lookup misses. Sharing a meaningful
    token links them without a hand-maintained mapping table. 1.0 = no data.
    """
    mine = _tokens(niche)
    if not mine or not scores:
        return 1.0
    best, found = 1.0, False
    for (s_lang, s_niche), score in scores.items():
        if s_lang != lang:
            continue
        other = _tokens(s_niche)
        linked = bool(mine & other) or any(len(t) > 5 and t in str(s_niche) for t in mine)
        if linked:
            found = True
            best = max(best, score)
    return best if found else 1.0


# --------------------------------------------------------------------------- #
# Cooldown - winners get repeated, but never back to back
# --------------------------------------------------------------------------- #
def recent_niches(lang, days=REPEAT_COOLDOWN_DAYS):
    """Niches published within `days` - callers keep them out of the queue."""
    hist = _json_load(HISTORY_PATH, {})
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    recent = set()
    for entry in hist.get("published", []):
        if entry.get("lang") != lang:
            continue
        try:
            stamp = datetime.fromisoformat(entry.get("published_at", "")).timestamp()
        except (ValueError, TypeError, AttributeError):
            continue
        if stamp >= cutoff:
            recent.add(entry.get("niche"))
    return {n for n in recent if n}




# --------------------------------------------------------------------------- #
# Collection
# --------------------------------------------------------------------------- #
def collect(save=True):
    """Fetch stats for the whole channel, annotate, snapshot, return them."""
    yt = _youtube_client()
    rows = annotate(_fetch_stats(yt))
    scores = niche_scores(rows)
    totals = {
        "videos": len(rows),
        "views": sum(r.get("views", 0) for r in rows),
        "short_views": sum(r.get("views", 0) for r in rows if r.get("kind") == "short"),
        "long_views": sum(r.get("views", 0) for r in rows if r.get("kind") == "long"),
        "subs": _channel_subs(yt),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    if save:
        hist = _json_load(HISTORY_PATH, {})
        hist.setdefault("snapshots", [])
        # One snapshot per calendar day; re-running today just replaces it.
        today = totals["collected_at"][:10]
        hist["snapshots"] = [s for s in hist["snapshots"]
                             if str(s.get("collected_at", ""))[:10] != today]
        hist["snapshots"].append(totals)
        hist["snapshots"] = hist["snapshots"][-MAX_DAYS:]
        hist["videos"] = rows
        hist["scores"] = {f"{lang}|{niche}": v
                          for (lang, niche), v in scores.items()}
        hist["latest"] = totals["collected_at"]
        hist.setdefault("published", [])
        _json_save(HISTORY_PATH, hist)
    return rows, scores, totals


def load_scores():
    """{(lang, niche): score} from the committed snapshot. {} when unavailable."""
    hist = _json_load(HISTORY_PATH, {})
    out = {}
    for key, val in (hist.get("scores") or {}).items():
        if "|" in key:
            lang, niche = key.split("|", 1)
            out[(lang, niche)] = val
    return out


def report(rows, scores):
    """Human-readable ranking: `python analytics.py --report`."""
    grouped = {}
    for r in rows:
        grouped.setdefault((r.get("lang", ""), r.get("niche", "")), []).append(r)

    _log(f"{'lang':4} {'score':>6} {'n':>3} {'views':>7} {'/day':>8}  niche")
    _log("-" * 88)
    for key, vids in sorted(grouped.items(), key=lambda kv: -scores.get(kv[0], 1.0)):
        lang, niche = key
        _log(f"{lang:4} {scores.get(key, 1.0):>6.2f} {len(vids):>3} "
             f"{sum(v.get('views', 0) for v in vids):>7} "
             f"{_median([v.get('views_per_day') for v in vids]):>8.1f}  "
             f"{str(niche)[:44]}")
    winners = [k for k, v in scores.items() if v > 1.05]
    losers = [k for k, v in scores.items() if v < 0.95]
    _log("")
    _log(f"winners (score > 1.05): {len(winners)}")
    _log(f"laggards (score < 0.95): {len(losers)}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        rows, scores, totals = collect()
    except Exception as e:
        _log(f"[analytics] collection failed: {e}")
        return 1
    _log(f"[analytics] {totals['videos']} videos | {totals['views']} views | "
         f"shorts {totals['short_views']} | long {totals['long_views']} | "
         f"subs {totals['subs']}")
    report(rows, scores)
    return 0


if __name__ == "__main__":
    sys.exit(main())

