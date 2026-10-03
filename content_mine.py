# -*- coding: utf-8 -*-
"""Mine the highest-engagement spoken/written text on a topic from the internet.

Repo supplies only the NICHE. The clip's content comes from the top-performing
content found online for that niche.

Never downloads a video - only captions text (YouTube) + article bodies (news).

CLI:
    python content_mine.py --niche "روانشناسی رابطه" --lang fa
    python content_mine.py --niche "Psychology" --lang en --json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

QUERY_HINTS = {
    "روانشناسی رابطه": "روانشناسی رابطه جذابیت عشق",
    "روانشناسی و رفتار انسان": "روانشناسی رفتار انسان حقایق",
    "طنز روزمره": "طنز روزمره خنده دار",
    "پول و اقتصاد روزمره": "پول و اقتصاد روزمره پس انداز",
    "Psychology": "psychology facts human behavior",
    "Human Behavior": "human behavior psychology explained",
    "Money": "money psychology finance explained",
    "Relationships": "relationship psychology attraction",
    "Comedy": "funny comedy sketches",
}

MIN_VIEWS = int(os.environ.get("MINE_MIN_VIEWS", "2000"))
MIN_DURATION = int(os.environ.get("MINE_MIN_DURATION", "15"))
MAX_DURATION = int(os.environ.get("MINE_MAX_DURATION", "1200"))
SEARCH_N = int(os.environ.get("MINE_SEARCH_N", "6"))
CAPTION_LANGS = ["fa", "en", "en-US", "en-GB"]


def _log(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def build_query(niche, lang, extra=""):
    hint = QUERY_HINTS.get(str(niche).strip())
    base = hint if hint else str(niche).strip()
    if extra:
        base = f"{base} {extra}".strip()
    if lang == "en" and not hint:
        base = f"{base} facts explained"
    return base


def search_youtube(query, n=SEARCH_N):
    """Top YouTube results - metadata only, NO video download."""
    import yt_dlp
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True, "default_search": f"ytsearch{n}",
        # Ranking now uses engagement + recency, so pull those fields too.
        "extractor_args": {"youtube": {"skip": ["dash", "hls"]}},
        "ignore_no_formats_error": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
    return [e for e in (info.get("entries") or []) if e]


def _recency_factor(e):
    """1.0 for a fresh upload, decaying over ~1 year.

    A 6-year-old viral video often covers a topic that has since been answered
    better; a video from this week that is already climbing is the better bet.
    """
    ts = e.get("timestamp") or e.get("upload_date") or 0
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return 0.6
    if ts > 1e11:          # millisecond epoch
        ts /= 1000.0
    if ts <= 0:
        return 0.6
    days = max(0.0, (time.time() - ts) / 86400.0)
    return max(0.25, 1.0 - days / 365.0)


def _engagement_rate(e):
    """likes+comments per view, saturating around 5% - a real "people cared" signal."""
    views = e.get("view_count") or 0
    if views < MIN_VIEWS:
        return 0.0
    reacts = (e.get("like_count") or 0) + (e.get("comment_count") or 0)
    return min(reacts / views, 0.05)


def content_score(e):
    """Rank candidates by what actually worked, not by raw view count.

    score = (views per minute of runtime)  x  recency  x  (1 + engagement)

    Raw view_count was the old key, which ranked 3-hour compilations above tight
    explainers. Views-per-minute rewards dense, rewatchable content; the
    engagement multiplier prefers clips viewers reacted to; recency keeps the
    channel on topics people care about now.
    """
    views = e.get("view_count") or 0
    dur = e.get("duration") or 0
    vpm = views / max(dur / 60.0, 1.0) if dur else views / 8.0
    # log-compress so a 10x-bigger video is not a 10x-better source
    import math
    base = math.log10(vpm + 1.0)
    return base * (0.6 + 0.8 * _recency_factor(e)) * (1.0 + 20.0 * _engagement_rate(e))


def pick_best(entries):
    """Highest content_score among entries that have captions and a sane length."""
    usable = []
    for e in entries:
        if not e:
            continue
        if (e.get("view_count") or 0) < MIN_VIEWS:
            continue
        dur = e.get("duration") or 0
        if dur and not (MIN_DURATION <= dur <= MAX_DURATION):
            continue
        if not (e.get("subtitles") is not None or e.get("automatic_captions") is not None):
            continue
        usable.append(e)
    if not usable:
        return None
    usable.sort(key=lambda e: -content_score(e))
    best = usable[0]
    _log(f"[mine] best video: {str(best.get('title'))[:55]} "
         f"({best.get('view_count', 0):,} views, "
         f"score={content_score(best):.2f}, "
         f"eng={_engagement_rate(best) * 100:.1f}%)")
    return best


def search_news(query, lang="fa", n=4):
    """Top article headlines/links from Google News RSS (no key needed)."""
    import urllib.parse
    lang_prefix = "fa" if lang == "fa" else "en"
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query) + f"&hl={lang_prefix}&gl="
           + ("IR" if lang == "fa" else "US") + "&ceid="
           + (":IR" if lang == "fa" else ":US"))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            xml = r.read().decode("utf-8", "replace")
    except Exception as e:
        _log(f"[mine] news failed ({e})")
        return []
    items = []
    for m in re.finditer(
        r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>"
        r".*?<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", xml, re.S
    ):
        title, link = m.group(1).strip(), m.group(2).strip()
        if title and link:
            items.append({"title": title, "url": link})
        if len(items) >= n:
            break
    return items


def search_wikipedia(query, lang="fa"):
    """Wikipedia summaries - free, no key, never rate-limited hard.

    Owner directive 2026-10-03: YouTube is not the only source. Wikipedia is a
    reliable fallback that gives real explanatory prose for almost any niche.
    """
    import urllib.parse
    api = "https://fa.wikipedia.org/w/api.php" if lang == "fa" else "https://en.wikipedia.org/w/api.php"
    url = (api + "?action=query&prop=extracts&explaintext=1"
           "&redirects=1&format=json&exlimit=1&titles="
           + urllib.parse.quote(query))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PadizAutomation/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        _log(f"[mine] wikipedia failed ({e})")
        return None
    pages = (data.get("query") or {}).get("pages") or {}
    for _k, page in pages.items():
        if page.get("missing"):
            continue
        text = (page.get("extract") or "").strip()
        if len(text) < 120:
            continue
        return {"title": page.get("title", query), "url": page.get("fullurl", ""),
                "text": text, "views": 0}
    return None


def search_reddit(query, lang="fa", n=3):
    """Top Reddit posts for the niche - real discussion text, no key needed."""
    import urllib.parse
    sub = "iran" if lang == "fa" else "worldnews"
    url = ("https://www.reddit.com/search.json?q=" + urllib.parse.quote(query)
           + f"&sort=top&t=month&limit={n}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PadizAutomation/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return []
    out = []
    for ch in ((data.get("data") or {}).get("children") or []):
        d = ch.get("data") or {}
        body = (d.get("selftext") or "").strip()
        if len(body) > 300:
            out.append({"title": d.get("title", ""), "text": body,
                        "url": "https://reddit.com" + (d.get("permalink") or "")})
    return out


def search_hackernews(query, n=3):
    """Algolia HN search - technical niches and evergreen psychology threads."""
    import urllib.parse
    url = "https://hn.algolia.com/api/v1/search?query=" + urllib.parse.quote(query) + f"&hitsPerPage={n}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PadizAutomation/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return []
    out = []
    for h in (data.get("hits") or []):
        body = re.sub(r"<[^>]+>", " ", h.get("comment_text") or h.get("story_text") or "")
        if len(body.split()) > 120:
            out.append({"title": h.get("title") or h.get("story_title") or "",
                        "text": body,
                        "url": h.get("url") or "https://news.ycombinator.com/item?id=" + str(h.get("objectID"))})
    return out


TAG_RE = re.compile(r"<[^>]+>")
TIME_RE = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}\s*-->")


def _clean_caption(raw):
    """VTT/SRT -> plain spoken text, rolling auto-caption dupes removed."""
    if not raw:
        return ""
    if raw.lstrip().startswith("{"):
        try:
            data = json.loads(raw)
            parts = []
            for ev in data.get("events", []):
                for seg in ev.get("segs", []) or []:
                    t = seg.get("utf8", "")
                    if t and t != "\n":
                        parts.append(t)
            raw = " ".join(parts)
        except Exception:
            pass
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or TIME_RE.match(line):
            continue
        if line.upper().startswith(("WEBVTT", "KIND:", "LANGUAGE:", "NOTE", "STYLE", "-->")):
            continue
        line = TAG_RE.sub("", line).replace("\ufeff", "").strip()
        if not line:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    text = re.sub(r"\s{2,}", " ", " ".join(lines)).strip()
    words = len(re.sub(r"[^\w؀-ۿ]", "", text, flags=re.UNICODE))
    return text if words >= 40 else ""


def _download(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _caption_url(video, langs=CAPTION_LANGS):
    """Manual captions first, then auto - prefer VTT, fall back to any format."""
    for bucket in ("subtitles", "automatic_captions"):
        tracks = video.get(bucket) or {}
        for lang in langs:
            variants = tracks.get(lang) or []
            for want in ("vtt", "json3", "srv3", "ttml"):
                for v in variants:
                    if v.get("ext") == want and v.get("url"):
                        return v["url"]
            if variants and variants[0].get("url"):
                return variants[0]["url"]
    return None


def fetch_captions(video, langs=CAPTION_LANGS):
    url = _caption_url(video, langs)
    if not url:
        return ""
    try:
        return _clean_caption(_download(url))
    except Exception as e:
        _log(f"[mine] caption download failed ({e})")
        return ""


def mine(niche, lang="fa", extra=""):
    """Best source text for a repo niche. Returns dict or None."""
    query = build_query(niche, lang, extra)
    _log(f"[mine] niche={niche!r} query={query!r}")

    videos, news = [], []
    try:
        videos = search_youtube(query)
        _log(f"[mine] youtube: {len(videos)} candidates")
    except Exception as e:
        _log(f"[mine] youtube search failed ({type(e).__name__}: {str(e)[:120]})")
    try:
        news = search_news(query, lang)
        _log(f"[mine] news: {len(news)} articles")
    except Exception as e:
        _log(f"[mine] news search failed ({e})")

    # 1) best video with captions
    best = pick_best(videos)
    text, source_url, views, src_title = "", "", 0, ""
    if best:
        src_title = str(best.get("title") or "")
        views = int(best.get("view_count") or 0)
        source_url = f"https://www.youtube.com/watch?v={best.get('id')}"
        _log(f"[mine] best video: {src_title[:60]} ({views} views)")
        langs = ["fa", "en"] if lang == "fa" else ["en", "fa"]
        text = fetch_captions(best, langs)
        # dead caption track -> next-best candidate
        if not text:
            for alt in sorted(videos, key=lambda v: -(v.get("view_count") or 0))[1:4]:
                t = fetch_captions(alt, langs)
                if t:
                    best, text, views = alt, t, int(alt.get("view_count") or 0)
                    src_title = str(alt.get("title") or "")
                    source_url = f"https://www.youtube.com/watch?v={alt.get('id')}"
                    _log(f"[mine] fallback video used: {src_title[:50]}")
                    break

    # 2) no video text -> Wikipedia, then Reddit / Hacker News, then news
    # articles. Owner directive 2026-10-03: never depend on a single source.
    if not text:
        try:
            for term in (query, str(niche).strip()):
                wiki = search_wikipedia(term, lang)
                if wiki:
                    src_title = wiki["title"]
                    source_url = wiki["url"] or f"https://{lang}.wikipedia.org/wiki/{query}"
                    text = wiki["text"]
                    _log(f"[mine] wikipedia used ({len(text.split())} words)")
                    break
        except Exception as e:
            _log(f"[mine] wikipedia failed ({e})")

    if not text:
        try:
            for hit in (search_reddit(query, lang) or [])[:2]:
                src_title = hit["title"] or query
                source_url = hit["url"]
                text = hit["text"]
                _log(f"[mine] reddit used ({len(text.split())} words)")
                break
        except Exception as e:
            _log(f"[mine] reddit failed ({e})")

    if not text:
        try:
            for hit in (search_hackernews(query) or [])[:2]:
                src_title = hit["title"] or query
                source_url = hit["url"]
                text = hit["text"]
                _log(f"[mine] hackernews used ({len(text.split())} words)")
                break
        except Exception as e:
            _log(f"[mine] hackernews failed ({e})")

    # 3) last resort: the best news article
    if not text and news:
        src_title, source_url = news[0].get("title", ""), news[0].get("url", "")
        try:
            html = _download(news[0]["url"])
            body = _html_to_text(html)
            text = body
            _log(f"[mine] article body used ({len(body.split())} words)")
        except Exception as e:
            _log(f"[mine] article fetch failed ({e})")

    if not text:
        _log("[mine] nothing usable found")
        return None

    return {
        "niche": niche, "lang": lang, "query": query,
        "source_title": src_title, "source_url": source_url,
        "views": views, "words": len(text.split()),
        "also_news": [n.get("title") for n in news[:3]],
        "text": text,
    }


def _html_to_text(html):
    html = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as _h
    text = _h.unescape(html)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # keep the meaty middle, drop nav/footer noise
    if len(text.split()) > 400:
        words = text.split()
        text = " ".join(words[:400])
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mine best on-topic text from the internet")
    ap.add_argument("--niche", required=True, help="repo niche (topic list)")
    ap.add_argument("--lang", default="fa", choices=["fa", "en"])
    ap.add_argument("--extra", default="", help="extra search words")
    ap.add_argument("--json", action="store_true", help="print result as JSON")
    ap.add_argument("--out", default="", help="write raw text to this file")
    args = ap.parse_args(argv)

    result = mine(args.niche, args.lang, args.extra)
    if not result:
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(result["text"])
        _log(f"[mine] text -> {args.out}")

    if args.json:
        slim = {k: v for k, v in result.items() if k != "text"}
        slim["text_chars"] = len(result["text"])
        print(json.dumps(slim, ensure_ascii=False, indent=2))
        if args.out:
            pass
        else:
            print(result["text"][:800])
    else:
        _log(f"[mine] {result['words']} words | {result['views']} views")
        _log(f"[mine] source: {result['source_title'][:70]}")
        _log(f"[mine] url: {result['source_url']}")
        _log("-" * 60)
        _log(result["text"][:900])
    return 0


if __name__ == "__main__":
    sys.exit(main())
