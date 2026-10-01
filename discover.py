# -*- coding: utf-8 -*-
"""Daily discovery: the channel picks its own topics instead of a fixed list.

Owner directive (2026-10-01): the system should go online every day, search inside
the niches WE approved, and build whatever is genuinely hot right now.

topics_niches.py stays the only gate: a niche we did not approve can never be used.
What changes is the ANGLE inside an approved niche - instead of picking blindly we
look at what is actually gaining attention and hand that story to the writer.

Sources (free, verified working from this machine):
  * YouTube search.list  - viral videos per niche, in any language. Uses the
                           channel OAuth token, so NO YouTube API key. 100 units/call.
  * Hacker News (Algolia)- tech/business/science with real engagement.
  * Google News RSS      - what is being read today, EN + FA.
  * Reddit is deliberately absent: its public JSON endpoint answers 403 to bots.

Scoring is deterministic, so discovery costs NO Gemini quota. The writer is only
invoked afterwards, exactly as often as before.
"""
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_PATH = os.path.join(BASE_DIR, "discovery_pool.json")
QUOTA_PATH = os.path.join(BASE_DIR, "discovery_quota.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; PadizStudioBot/1.0)"}
MAX_YT_SEARCHES_PER_DAY = int(os.environ.get("DISCOVERY_YT_SEARCHES", "10"))
VIDEOS_PER_SEARCH = 8


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


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _norm(title):
    """Title fingerprint used for de-duplication."""
    return re.sub(r"[^a-z0-9؀-ۿ]+", "", str(title).lower())[:44]



# --------------------------------------------------------------------------- #
# Niche -> search phrase. The owner list is the gate; this only sharpens the search.
# --------------------------------------------------------------------------- #
EN_QUERY_HINTS = {
    'AI': 'artificial intelligence explained',
    'Technology': 'technology explained',
    'Money': 'money mistakes finance',
    'Finance': 'personal finance explained',
    'Business': 'business case study',
    'Entrepreneurship': 'startup business lessons',
    'Psychology': 'psychology of human behavior',
    'Human Behavior': 'human behavior psychology',
    'Science': 'science explained',
    'Space': 'space astronomy discovery',
    'History': 'history explained facts',
    'Mystery': 'mystery explained',
    'True Crime': 'true crime case explained',
    'Survival': 'survival tips wilderness',
    'Health': 'health explained facts',
    'Fitness': 'fitness habits that work',
    'Self Improvement': 'self improvement habits',
    'Motivation': 'motivation discipline',
    'Education': 'learning explained',
    'Interesting Facts': 'interesting facts you dont know',
    'Weird Facts': 'weird facts',
    'Animals': 'animal facts amazing',
    'Nature': 'nature facts amazing',
    'Travel': 'travel destinations hidden',
    'Geography': 'geography facts countries',
    'Food': 'food facts explained',
    'Cooking': 'cooking tips kitchen hacks',
    'Gaming': 'gaming facts',
    'Sports': 'sports explained',
    'Football': 'football explained',
    'Basketball': 'basketball explained',
    'Movies': 'movie facts behind the scenes',
    'TV Shows': 'tv show facts',
    'Entertainment': 'entertainment explained',
    'Celebrity Stories': 'celebrity story explained',
    'Pop Culture': 'pop culture explained',
    'Internet Culture': 'internet culture explained',
    'Social Media': 'social media explained',
    'Relationships': 'relationships advice psychology',
    'Dating': 'dating psychology',
    'Love': 'love psychology facts',
    'Life Hacks': 'life hacks that actually work',
    'Productivity': 'productivity tips that work',
    'Career': 'career advice',
    'Jobs': 'jobs career mistakes',
    'Coding': 'programming explained',
    'Software': 'software engineering explained',
    'Cybersecurity': 'cybersecurity explained',
    'Future Technology': 'future technology',
    'Robotics': 'robotics explained',
    'Cars': 'cars facts',
    'Luxury': 'luxury explained',
    'Real Estate': 'real estate explained',
    'Investing': 'investing explained',
    'Cryptocurrency': 'cryptocurrency explained',
    'Marketing': 'marketing explained',
    'E-commerce': 'ecommerce business',
    'Startups': 'startup lessons',
    'Inventions': 'inventions explained',
    'Ancient Civilizations': 'ancient civilizations explained',
    'Archaeology': 'archaeology discoveries',
    'Ancient Technology': 'ancient technology',
    'Military History': 'military history explained',
    'World Records': 'world records amazing',
    'Disasters': 'disasters explained',
    'Natural Phenomena': 'natural phenomena explained',
    'Human Body': 'human body facts',
    'Medical Science': 'medical science explained',
    'Space Discoveries': 'space discoveries',
    'Ocean Mysteries': 'ocean mysteries',
    'Conspiracy Theories': 'conspiracy theories debunked',
    'Unsolved Mysteries': 'unsolved mysteries',
    'Horror Stories': 'horror true story',
    'Dark History': 'dark history',
    'Fascinating Stories': 'fascinating stories history',
    'Incredible Discoveries': 'incredible discoveries',
    'Micro Dramas': 'short drama story',
    'Short Stories': 'short story moral lesson',
    'Moral Stories': 'moral story lesson',
    'Philosophy': 'philosophy of life',
    'Personal Development': 'personal development tips',
    'Communication': 'communication skills tips',
    'Social Skills': 'social skills confidence',
    'Wealth': 'wealth building habits',
    'Success Stories': 'success story lessons',
}


FA_QUERY_HINTS = {
    'ایران و تاریخ ایران': 'تاریخ ایران',
    'حقایق عجیب ایران': 'حقایق عجیب ایران',
    'مهاجرت و زندگی خارج از ایران': 'مهاجرت و زندگی در خارج',
    'پول و اقتصاد روزمره': 'پول و ثروت',
    'هوش مصنوعی و تکنولوژی': 'هوش مصنوعی و تکنولوژی',
    'روانشناسی و رفتار انسان': 'روانشناسی رابطه و رفتار انسان',
    'عجایب و رازهای حل\u200cنشده': 'رازهای حل نشده',
    'علم و فضا': 'علم و فضا',
    'جغرافیا و کشورهای جهان': 'جغرافیا و کشورهای جهان',
    'فرهنگ و آداب ایرانی': 'فرهنگ و آداب ایرانی',
    'فوتبال و ورزش': 'فوتبال',
    'سینما و سریال': 'سینما و سریال',
    'داستان\u200cهای واقعی': 'داستان واقعی',
    'جنایت و پرونده\u200cهای معمایی': 'پرونده جنایتی معمایی',
    'تاریخ تاریک و اتفاقات عجیب تاریخی': 'تاریخ تاریک',
    'موفقیت و ثروت': 'موفقیت و ثروت',
    'کسب\u200cوکار و درآمد اینترنتی': 'کسب و کار اینترنتی',
    'مقایسه ایران با جهان': 'مقایسه ایران و جهان',
    'ایران\u200cشناسی و مناطق ناشناخته': 'مناطق ناشناخته ایران',
}


def query_for(niche, lang):
    """Search phrase used inside an approved niche."""
    hints = EN_QUERY_HINTS if lang == "en" else FA_QUERY_HINTS
    return hints.get(niche, niche)


# --------------------------------------------------------------------------- #
# Sources. Every one is optional: a dead source must never break discovery.
# --------------------------------------------------------------------------- #
HN_NICHES = {
    "AI", "Technology", "Science", "Space", "Software", "Coding", "Cybersecurity",
    "Robotics", "Future Technology", "Business", "Entrepreneurship", "Startups",
    "Marketing", "E-commerce", "Investing", "Cryptocurrency", "Real Estate",
    "Cars", "Luxury", "Internet Culture", "Social Media", "Artificial Intelligence",
}


def _quota_used_today():
    """search.list costs 100 quota units per call, so it is budgeted per day."""
    q = _json_load(QUOTA_PATH, {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if q.get("date") != today:
        return 0
    return int(q.get("yt_searches", 0) or 0)


def _quota_add(n=1):
    q = _json_load(QUOTA_PATH, {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if q.get("date") != today:
        q = {"date": today, "yt_searches": 0}
    q["yt_searches"] = int(q.get("yt_searches", 0) or 0) + n
    _json_save(QUOTA_PATH, q)


def _age_hours(published, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        when = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(1.0, (now - when).total_seconds() / 3600.0)
    except Exception:
        return 720.0


def from_youtube(niche, lang, days_back=30):
    """Videos currently climbing inside this niche, via the channel OAuth token."""
    if _quota_used_today() >= MAX_YT_SEARCHES_PER_DAY:
        _log("[discover] YouTube search budget spent today - skipping this niche")
        return []
    try:
        import analytics as A
        yt = A._youtube_client()
        since = datetime.now(timezone.utc) - timedelta(days=days_back)
        resp = yt.search().list(
            part="snippet", q=query_for(niche, lang), type="video", order="viewCount",
            publishedAfter=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            maxResults=VIDEOS_PER_SEARCH,
            relevanceLanguage="fa" if lang == "fa" else "en",
        ).execute()
    except Exception as e:
        _log(f"[discover] youtube search failed for {niche!r} ({e})")
        return []
    _quota_add()

    ids = [i["id"]["videoId"] for i in resp.get("items", []) if "id" in i]
    if not ids:
        return []
    try:
        detail = yt.videos().list(part="snippet,statistics", id=",".join(ids[:50])).execute()
    except Exception as e:
        _log(f"[discover] youtube stats failed ({e})")
        return []

    out = []
    for v in detail.get("items", []):
        st, sn = v.get("statistics", {}) or {}, v.get("snippet", {}) or {}
        views = int(st.get("viewCount", 0) or 0)
        pub = sn.get("publishedAt", "")
        age = _age_hours(pub)
        out.append({
            "niche": niche, "lang": lang, "title": sn.get("title", ""),
            "source": "youtube", "url": f"https://www.youtube.com/watch?v={v['id']}",
            "views": views, "likes": int(st.get("likeCount", 0) or 0),
            "comments": int(st.get("commentCount", 0) or 0),
            "age_hours": round(age, 1), "channel": sn.get("channelTitle", ""),
            "published_at": pub, "velocity": round(views / age, 2),
        })
    return out


def from_hackernews(niche, lang="en"):
    """Tech / business / science stories with proven engagement (EN only)."""
    if lang != "en":
        return []
    try:
        url = ("https://hn.algolia.com/api/v1/search_by_date?tags=story"
               "&numericFilters=points>60,num_comments>10&hitsPerPage=10")
        hits = json.loads(_get(url)).get("hits", [])
    except Exception as e:
        _log(f"[discover] hackernews failed ({e})")
        return []
    out = []
    for h in hits:
        title = (h.get("title") or "").strip()
        if not title:
            continue
        age = max(1.0, (datetime.now(timezone.utc).timestamp() - (h.get("created_at_i") or 0)) / 3600.0)
        pts = int(h.get("points") or 0)
        out.append({
            "niche": niche, "lang": lang, "title": title, "source": "hackernews",
            "url": h.get("url") or "https://news.ycombinator.com/item?id=" + str(h.get("objectID")),
            "views": pts * 100, "likes": pts, "comments": int(h.get("num_comments") or 0),
            "age_hours": round(age, 1), "channel": "HackerNews",
            "published_at": h.get("created_at", ""), "velocity": round(pts / age, 3),
        })
    return out


def from_news(niche, lang, limit=6, timeout=12):
    """Google News RSS - what people are reading about right now.

    Google's RSS endpoint is slow (multi-second, sometimes >20s), so the
    timeout is tight and the item count is small: news is a supporting
    signal, YouTube velocity is the primary one.
    """
    hl, gl, ceid = ("fa", "IR", "IR:fa") if lang == "fa" else ("en-US", "US", "US:en")
    q = urllib.parse.quote(query_for(niche, lang))
    try:
        body = _get(f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}",
                    timeout=timeout).decode("utf-8", "replace")
    except Exception as e:
        _log(f"[discover] news rss failed for {niche!r} ({e})")
        return []
    out = []
    for item in re.findall(r"<item>(.*?)</item>", body, re.S)[:limit]:
        def tag(name, blob=item):
            m = re.search(rf"<{name}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", blob, re.S)
            return m.group(1).strip() if m else ""
        title, link, pub = tag("title"), tag("link"), tag("pubDate")
        if not title:
            continue
        out.append({
            "niche": niche, "lang": lang, "title": title, "source": "news",
            "url": link, "views": 0, "likes": 0, "comments": 0,
            "age_hours": _age_hours(pub, datetime(2026, 1, 1, tzinfo=timezone.utc)),
            "channel": tag("source"), "published_at": pub, "velocity": 0.0,
        })
    return out


# --------------------------------------------------------------------------- #
# Niche selection - analytics decides WHICH approved niche we probe today
# --------------------------------------------------------------------------- #
def niches_to_probe(lang, count):
    """Approved niches for this language, best-scoring first, minus a cooldown."""
    import topics_niches as N
    pool = N.EN_NICHES if lang == "en" else N.FA_NICHES
    scores, cooling = {}, set()
    try:
        import analytics as AN
        scores = AN.load_scores()
        cooling = AN.recent_niches(lang, days=7)
    except Exception:
        pass

    def rank(niche):
        s = 1.0
        if scores:
            try:
                s = AN.family_score(lang, niche, scores)
            except Exception:
                s = 1.0
        if niche in cooling:
            s -= 0.5
        return -s

    return sorted(pool, key=rank)[:count]


# --------------------------------------------------------------------------- #
# Scoring + persistence
# --------------------------------------------------------------------------- #
def score(item):
    """Blend velocity, engagement and freshness into one comparable number."""
    vel = item.get("velocity") or 0.0
    views = item.get("views") or 0
    likes = item.get("likes") or 0
    comments = item.get("comments") or 0
    age_h = max(1.0, item.get("age_hours") or 24.0)

    vel_score = math.log10(vel + 1) * 10.0
    eng = (likes / views) if views else 0.0
    eng_score = min(20.0, eng * 100.0)
    talk_score = min(10.0, math.log10(comments + 1) * 4.0)
    fresh_score = max(0.0, 12.0 - math.log10(age_h + 1) * 2.5)
    return round(vel_score * 0.45 + eng_score * 0.30 + talk_score * 0.10 + fresh_score * 0.15, 2)


def discover(lang, niches=None, save=True):
    """Gather candidates for a language across sources and rank them."""
    target = list(niches) if niches is not None else niches_to_probe(lang, 3)
    candidates = []
    for niche in target:
        found = list(from_youtube(niche, lang))
        # Hacker News only covers tech / business / science. Firing it at
        # "History" or "Love" returned wildly off-niche stories, so it is gated.
        if niche in HN_NICHES:
            found += from_hackernews(niche, lang)
        # News RSS is keyword-scoped already, so it works for every niche.
        found += from_news(niche, lang)
        for item in found:
            item["heat"] = score(item)
        candidates += found
        _log(f"[discover] {lang} {niche!r}: {len(found)} candidates")

    seen, unique = set(), []
    for item in sorted(candidates, key=lambda x: -x.get("heat", 0.0)):
        key = _norm(item.get("title"))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)

    if save:
        pool = _json_load(POOL_PATH, {})
        pool[lang] = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "niches": target, "items": unique[:25],
        }
        _json_save(POOL_PATH, pool)
    return unique[:25]


def best_for(lang, exclude_titles=()):
    """Top discovery for a language, skipping anything we already covered."""
    items = (_json_load(POOL_PATH, {}).get(lang) or {}).get("items", [])
    blocked = {_norm(t) for t in exclude_titles}
    for item in items:
        if _norm(item.get("title")) not in blocked:
            return item
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    lang = argv[argv.index("--lang") + 1].lower() if "--lang" in argv else "en"
    count = int(argv[argv.index("--niches") + 1]) if "--niches" in argv else 3
    items = discover(lang, niches_to_probe(lang, count))
    _log("")
    _log(f"[discover] TOP {min(10, len(items))} for {lang!r}:")
    for it in items[:10]:
        _log(f"  heat={it['heat']:>6.2f} vel={it['velocity']:>8.2f} "
             f"[{it['source']:10}] {it['niche'][:20]:20} {it['title'][:42]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
