# -*- coding: utf-8 -*-
"""Generate brand-new Shorts from today's internet discoveries.

Owner directive (2026-10-01): Shorts must no longer come only from a fixed
13+8 pool. When the static pool runs dry, the writer takes the hottest story
found by discover.py inside an APPROVED niche and turns it into a 3-slide
Short - fully automatically, no one hands it a text.

Quota discipline (the free Gemini tier survives ~10 TTS calls a day, and the
long video already eats ~4 of them):
  * Each run builds AT MOST 2 fresh Shorts (configurable via max_fresh).
  * Text generation is 1 Gemini call per Short. TTS happens later in the
    normal render path (1 batched call). A failed generation never blocks the
    static pool: run_daily falls back exactly as before.
  * Template fallback exists but is marked fallback=True, so it is only used
    when nothing better exists.
"""
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GEN_DIR = os.path.join(BASE_DIR, "shorts_generated")

MAX_FRESH_PER_RUN = int(os.environ.get("SHORTS_MAX_FRESH", "2"))

MUSIC_BY_LANG = {"en": "chill", "fa": "chill"}


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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _prompt(lang, niche, discovery):
    wmin, wmax = _speech_range(lang)
    head = (
        "Turn ONE trending story into a 3-slide YouTube Short. "
        "Return ONLY valid JSON, no markdown, no commentary."
        if lang == "en" else
        "از این سوژهٔ داغ، یک شورت ۳ اسلایدی بساز. "
        "فقط JSON معتبر برگردان، بدون توضیح اضافه."
    )
    shape = (
        '{"title": "...", "slides": ['
        '{"title": "...", "text": "...", "speech": "..."}, '
        '{"title": "...", "text": "...", "speech": "..."}, '
        '{"title": "...", "text": "...", "speech": "..."}]}'
    )
    rules = (
        f"Rules: title ends with ' #shorts'; each speech {wmin}-{wmax} words, "
        "spoken naturally; each text is ONE punchy on-screen line (max 9 words); "
        "image_query is 3-5 words of a REAL photo; never mention other channels; "
        "slide 1 is the hook - the single wildest line, no greeting."
        if lang == "en" else
        f"قوانین: تیتر با « #shorts» تمام شود؛ هر speech بین {wmin} تا {wmax} کلمه، "
        "محاوره‌ای؛ هر text فقط یک جملهٔ کوتاه روی تصویر (حداکثر ۸ کلمه)؛ "
        "image_query سه تا پنج کلمه توصیف عکس واقعی؛ نام کانال دیگران را نبر؛ "
        "اسلاید اول قلاب است - تک‌جملهٔ عجیب، بدون سلام و مقدمه."
    )
    evidence = (
        f'Trending evidence (use as raw material, never copy verbatim):\n'
        f'- "{discovery.get("title")}" '
        f'({discovery.get("source", "")}, {discovery.get("views", 0):,} views, '
        f'{discovery.get("velocity", 0):,.0f} views/hour)'
    )
    return (
        f"You write Shorts for the channel \"Padiz Studio\". "
        f"Approved niche: **{niche}**.\n{evidence}\n\n{head}\n{shape}\n{rules}"
    )


def _call_gemini(prompt, api_key):
    """One text-generation call. Returns the raw response string or ''."""
    import urllib.request
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-2.0-flash:generateContent?key=" + api_key)
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except Exception as e:
        _log(f"[genshorts] gemini text failed ({e})")
        return ""


def _extract_json(text):
    text = str(text or "")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _valid(data, lang):
    """Three complete slides in the right length band - enforced, not trusted."""
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        return False
    if len(data["slides"]) != 3:
        return False
    wmin, wmax = _speech_range(lang)
    for s in data["slides"]:
        if not isinstance(s, dict):
            return False
        if not s.get("title") or not s.get("text"):
            return False
        words = _words(s.get("speech"))
        if words < wmin - 2:
            return False
        if words > wmax + 8:
            return False
    if not data.get("title"):
        return False
    return True


def _normalize(data, lang, niche, discovery, topic_id):
    """Pool-compatible shape: identical to a static FACTS_POOL entry."""
    data["id"] = topic_id
    data["lang"] = lang
    data["niche"] = niche
    data["category"] = niche
    data["music"] = MUSIC_BY_LANG.get(lang, "chill")
    data["voice_index"] = 0
    data["fallback"] = bool(data.get("fallback", False))
    try:
        data["discovered_from"] = str(discovery.get("title", ""))[:80]
    except Exception:
        data["discovered_from"] = ""
    data.setdefault("description", "")
    data.setdefault("tags", ["shorts", "padiz_studio"])
    data["title"] = str(data["title"]).strip()
    if "#shorts" not in data["title"].lower():
        data["title"] += " #shorts"
    for s in data["slides"]:
        s["image_query"] = s.get("image_query") or f"{niche} real photo"
    return data


def _template(lang, niche, discovery, topic_id):
    """Last resort: a renderable Short from the story, clearly marked fallback."""
    title = str(discovery.get("title") or niche)[:60].strip()
    # Keep the spoken hook tight even when the discovered title is long.
    # Slides 2-3 are fixed voice seconds; slide 1 carries the story.
    words = str(title).split()
    spoken = " ".join(words[:9])
    if lang == "en":
        slides = [
            {"title": "Did you know?",
             "text": title[:60],
             "speech": f"Here is what everyone is talking about: {spoken}. Stay with me.",
             "image_query": f"{niche} real photo"},
            {"title": "The key detail",
             "text": "The part nobody expected.",
             "speech": f"The surprising part is what happened next, and it changes how you see {niche.lower()}.",
             "image_query": f"{niche} real world"},
            {"title": "Why it matters",
             "text": "Save this and follow for more.",
             "speech": f"If you find this fascinating, follow Padiz Studio for the full story every day.",
             "image_query": f"{niche} closeup photo"},
        ]
        data = {"title": f"{title} #shorts", "slides": slides,
                "description": f"{title}\n\nPadiz Studio #shorts",
                "tags": ["shorts", niche.replace(" ", "_").lower(), "padiz_studio"],
                "fallback": True}
    else:
        slides = [
            {"title": "میدونی چیه؟",
             "text": title[:60],
             "speech": f"این چیزیه که همه دارن درباره‌اش حرف میزنن: {spoken}. بمون ببین.",
             "image_query": f"{niche} عکس واقعی"},
            {"title": "نکتهٔ کلیدی",
             "text": "بخشی که هیچ‌کس انتظارش را نداشت.",
             "speech": f"قسمت غافلگیرکننده چیزیه که بعدش اتفاق افتاد، و نگاهت را به {niche} عوض می‌کنه.",
             "image_query": f"{niche} دنیای واقعی"},
            {"title": "چرا مهمه؟",
             "text": "ذخیره کن و دنبال کن.",
             "speech": f"اگه برات جالب بود، پادیز استودیو را دنبال کن تا هر روز داستان کامل را ببینی.",
             "image_query": f"{niche} عکس واقعی"},
        ]
        data = {"title": f"{title} #shorts", "slides": slides,
                "description": f"{title}\n\nپادیز استودیو #shorts",
                "tags": ["shorts", "padiz_studio"],
                "fallback": True}
    return _normalize(data, lang, niche, discovery, topic_id)


def _slug(text):
    s = re.sub(r"[^a-z0-9\u0600-\u06FF]+", "_", str(text).lower(),
               flags=re.UNICODE).strip("_")
    return re.sub(r"_+", "_", s)[:32] or "story"


def _words(text):
    return len(str(text or "").split())


def _speech_range(lang, slides=3):
    """Words per slide so the Short lands in the 25-50s sweet spot."""
    # Template speech has fixed filler around the hook, so give slide-1 room.
    return (8, 22) if lang == "fa" else (10, 24)


def _covered_titles():
    """Titles already on the channel or in the static pools - never repeat."""
    titles = set()
    try:
        from topics_pool import FACTS_POOL
        from topics_pool_en import FACTS_POOL_EN
        for item in list(FACTS_POOL) + list(FACTS_POOL_EN):
            titles.add(_slug(item.get("title", "")))
    except Exception:
        pass
    for name in os.listdir(GEN_DIR) if os.path.isdir(GEN_DIR) else []:
        if name.endswith(".json"):
            d = _json_load(os.path.join(GEN_DIR, name), {})
            if d.get("title"):
                titles.add(_slug(d["title"]))
    return titles


def load_generated():
    """Dynamic Shorts currently on disk, oldest first."""
    if not os.path.isdir(GEN_DIR):
        return []
    out = []
    for name in sorted(os.listdir(GEN_DIR)):
        if not name.endswith(".json"):
            continue
        d = _json_load(os.path.join(GEN_DIR, name), None)
        if d and isinstance(d.get("slides"), list) and len(d["slides"]) == 3:
            out.append(d)
    return out


def build_short(lang, niche=None, discovery=None, api_key=None, dry_run=False):
    """Write one new Short JSON from a discovery. Never raises."""
    api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    covered = _covered_titles()

    if discovery is None:
        try:
            import discover as D
            if niche is None:
                niche = D.niches_to_probe(lang, 1)[0]
            discovery = D.best_for(lang) or {}
        except Exception as e:
            _log(f"[genshorts] discovery unavailable ({e})")
            discovery = {}
    niche = niche or discovery.get("niche") or ("AI" if lang == "en" else "AI")

    suffix = _slug(discovery.get("title", ""))[:22] or "story"
    topic_id = f"{lang}_auto_{_slug(niche)[:20]}_{suffix}"
    if topic_id in covered or _slug(discovery.get("title", "")) in covered:
        _log("[genshorts] this story is already covered - skipping")
        return None

    data = None
    gem_key = (api_key or "").strip()
    gem_title = str((discovery or {}).get("title") or "") if isinstance(discovery, dict) else ""
    if gem_key and gem_title:
        data = _extract_json(_call_gemini(_prompt(lang, niche, discovery), gem_key))
        if not isinstance(data, dict) or not _valid(data, lang):
            if isinstance(data, dict):
                _log("[genshorts] generation rejected (wrong shape) - trying template")
            data = None

    if data is None:
        if not gem_title:
            _log("[genshorts] nothing to say - skipping")
            return None
        tpl = _template(lang, niche, discovery, topic_id)
        data = tpl if isinstance(tpl, dict) else None
        if data is None:
            _log("[genshorts] template failed - skipping")
            return None
        data["fallback"] = True
        _log("[genshorts] gemini text unavailable - used template (marked fallback)")

    data = _normalize(data, lang, niche, discovery, topic_id)
    if not dry_run:
        _json_save(os.path.join(GEN_DIR, f"{topic_id}.json"), data)
        _log(f"[genshorts] saved {topic_id} (fallback={data['fallback']})")
    return data


def top_up(lang, count):
    """Ensure `count` fresh dynamic Shorts exist for this language."""
    existing = [t for t in load_generated()
                if t.get("lang") == lang and not t.get("posted")]
    need = max(0, count - len(existing))
    made = []
    for _ in range(min(need, MAX_FRESH_PER_RUN)):
        try:
            item = build_short(lang)
        except Exception as e:
            _log(f"[genshorts] build failed ({e})")
            item = None
        if item:
            made.append(item)
    return made


def mark_posted(topic_id):
    """A dynamic Short went out - it must never come back."""
    path = os.path.join(GEN_DIR, f"{topic_id}.json")
    d = _json_load(path, None)
    if d is not None:
        d["posted"] = True
        _json_save(path, d)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    lang = "en"
    if "--lang" in argv:
        lang = argv[argv.index("--lang") + 1].lower()
    if "--list" in argv or not argv:
        for t in load_generated():
            status = "posted" if t.get("posted") else "FRESH"
            _log(f"{t['id']:44} {t['lang']:3} {status:6}  "
                 f"{t.get('niche','')[:26]:26}  {t.get('title','')[:44]}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
