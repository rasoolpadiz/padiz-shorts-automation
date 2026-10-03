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

# Mining (owner directive 2026-10-03): pull the top-performing text online for
# the niche and use it as the source of the Short. ON by default; set
# PADIZ_MINE=0 to go back to pure discovery titles.
MUSIC_BY_LANG = {"en": "chill", "fa": "chill"}


def _mine_enabled():
    return os.environ.get("PADIZ_MINE", "1") not in ("0", "false", "no", "off")


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


def _prompt(lang, niche, discovery, source_text=""):
    wmin, wmax = _speech_range(lang)
    head = (
        "Turn ONE trending story into a YouTube Short that is a SINGLE full-screen "
        "slide (exactly one slide, no second page). Write a long narration - "
        "60-110 words - so the video runs about 40-70 seconds. "
        "Return ONLY valid JSON, no markdown, no commentary."
        if lang == "en" else
        "از این سوژهٔ داغ، یک شورت بساز که فقط و فقط یک صفحهٔ تمام‌صفحه دارد "
        "(دقیقاً یک اسلاید، نه صفحهٔ دوم). روایت را بلند بنویس - ۶۰ تا ۱۱۰ کلمه - "
        "تا ویدیو حدود ۴۰ تا ۷۰ ثانیه شود. "
        "فقط JSON معتبر برگردان، بدون توضیح اضافه."
    )
    # Exactly one slide: the old variable-length shape produced multi-page videos.
    shape = (
        '{"title": "...", "slides": ['
        '{"title": "...", "text": "...", "speech": "...", "image_query": "..."}]}'
    )
    rules = (
        f"Rules: title ends with ' #shorts'; each speech {wmin}-{wmax} words, "
        f"written at exactly {wmin}-{wmax} words (under {wmin - 10} is rejected); "
        "spoken naturally; the on-screen text is ONE punchy headline line (max 9 words); "
        "image_query is 3-5 words of a REAL photo; never mention other channels; "
        "FILL the full 45-60 seconds: cover the hook, the mechanism, 2-3 concrete "
        "examples and a takeaway. Ban filler like 'did you know', 'imagine that', "
        "'the part nobody expected', 'save and follow' - every sentence must add "
        "a fact the viewer did not have; "
        "HOOK LAW (slide 1): open with ONE hard shocking claim WITH a specific number "
        "or fact - pattern interrupt, NO greeting, NO 'hey guys', NO 'in this video', "
        "NO 'did you know'. Examples: 'Your brain lies to you 2 hours every night.' "
        "Slide 1 speech must contain a number or a concrete claim."
        if lang == "en" else
        f"قوانین: تیتر با « #shorts» تمام شود؛ بین {wmin} تا {wmax} کلمه در speech بنویس، "
        "محاوره‌ای؛ text فقط یک جملهٔ کوتاه روی تصویر (حداکثر ۸ کلمه)؛ "
        "image_query سه تا پنج کلمه توصیف عکس واقعی؛ نام کانال دیگران را نبر؛ "
        f"دقیقاً {wmin} تا {wmax} کلمه در speech بنویس (کمتر از {wmin - 10} کلمه رد می‌شود). "
        "متن را پر کن: قلاب با عدد، مکانیسم، دو تا سه مثال مشخص از متن مبدأ، و یک جمع‌بندی. "
        "جمله‌های پرکننده مثل «بخشی که هیچ‌کس انتظارش را نداشت»، «تصور کنید»، "
        "«ذخیره کن و دنبال کن» ممنوع - هر جمله باید یک واقعیت تازه بدهد؛ "
        "قانون قلاب (اسلاید ۱): با یک ادعای شوک‌آور و مشخص WITH عدد یا واقعیت شروع کن - "
        "بدون سلام، بدون «امروز می‌خوام»، بدون «در این ویدیو»، بدون «آیا می‌دانستید». "
        "مثال: «مغزت هر شب ۲ ساعت بهت دروغ می‌گه.» "
        "speech اسلاید ۱ حتماً باید عدد یا ادعای مشخص داشته باشد."
    )
    evidence = (
        f'Trending evidence (use as raw material, never copy verbatim):\n'
        f'- "{discovery.get("title")}" '
        f'({discovery.get("source", "")}, {discovery.get("views", 0):,} views, '
        f'{discovery.get("velocity", 0):,.0f} views/hour)'
    )

    mined = ""
    if source_text:
        # The repo only supplies the niche; this text is the top-performing
        # online content for it (owner directive 2026-10-03). It is the SOURCE
        # of the clip - build the slides from these facts.
        clip = source_text[:6000]
        mined = (
            "\n\nSOURCE MATERIAL (top-performing content found online for this niche):\n"
            f'"""\n{clip}\n"""\n'
            "Build the Short out of the strongest, most surprising facts in the SOURCE "
            "MATERIAL above. Keep the facts and numbers. Do not invent new ones, do not "
            "mention the source, and never quote a full sentence verbatim - rephrase "
            "them into your own slides. Cover the WHOLE source: if it lists 7 signs or "
            "5 reasons, cover them all instead of stopping at the first few."
        )

    return (
        f"You write Shorts for the channel \"Padiz Studio\". "
        f"Approved niche: **{niche}**.\n{evidence}{mined}\n\n{head}\n{shape}\n{rules}"
    )


def _call_gemini(prompt, api_key):
    """One text-generation call. Returns the raw response string or ''.

    Tries newest model first: Google retires old model names (2026-10 the hardcoded
    gemini-2.0-flash returned 404 and every Short fell back to the template), so
    the same fallback list gen_topics.py uses is applied here.
    """
    import urllib.request
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    last_err = ""
    # Only names verified to exist on the live API (2026-10). gemini-3.8-flash
    # is NOT a real text model - it 404s - which silently pushed every Short
    # onto the meaningless template. Verify with:
    #   GET /v1beta/models?key=... and read the "name" fields.
    for model in ("gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                  "gemini-3-flash-preview", "gemini-flash-latest",
                  "gemini-2.5-flash"):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key=" + api_key)
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except Exception as e:
            last_err = str(e)
            # 429/400 quota or auth: trying other models will not help.
            if "429" in last_err or "API key" in last_err:
                break
            continue
    if last_err:
        _log(f"[genshorts] gemini text failed ({last_err})")
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


def _reject_reason(data, lang):
    """Return '' when the draft is publishable, else why it was refused.

    Splitting the verdict out of _valid() lets the caller log the exact rule the
    model broke AND re-ask with that reason, instead of silently dropping to the
    template.
    """
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        return "the JSON has no 'slides' array"
    slides = data["slides"]
    if len(slides) != 1:
        return f"it has {len(slides)} slides; you must write EXACTLY one full-screen slide"
    wmin, wmax = _speech_range(lang)
    filler = ("بخشی که هیچ", "انتظارش را نداشت", "تصور کنید",
              "ذخیره کن و دنبال کن", "نکتهٔ کلیدی", "چرا مهمه",
              "the part nobody expected", "imagine that", "save and follow")
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            return f"slide {i + 1} is not an object"
        if not s.get("title") or not s.get("text"):
            return f"slide {i + 1} is missing its title or on-screen text"
        speech = str(s.get("speech") or "")
        words = _words(speech)
        if words < wmin - 10:
            return (f"the narration is only {words} words - "
                    f"write at least {wmin - 10} words of real content")
        if words > wmax + 15:
            return f"the narration is {words} words - cut it to {wmax}"
        low = speech.lower()
        if any(f in low for f in filler):
            return (f"slide {i + 1} narration is filler like '{filler[0]}' - "
                    "replace it with an actual fact")
        if i == 0:
            banned = ("hello", "hey guys", "in this video", "did you know",
                      "سلام", "امروز می‌خوام", "امروز میخوام", "در این ویدیو",
                      "آیا می‌دانستید", "آیا میدانستید", "میدونی چیه")
            if any(b in low for b in banned):
                return "slide 1 starts with a greeting - open with the shocking claim instead"
            import re as _re
            if not _re.search(r"\d|[۰-۹]", speech):
                return "slide 1 narration has no number or concrete claim"
    if not data.get("title"):
        return "the JSON has no title"
    return ""


def _valid(data, lang):
    """4-7 substantive slides within the speech band - enforced, not trusted."""
    return not _reject_reason(data, lang)


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
    data.setdefault("tags", ["shorts", "padiz_studio"])
    data["title"] = str(data["title"]).strip()
    if "#shorts" not in data["title"].lower():
        data["title"] += " #shorts"
    # Hook-y title guard: keep the #shorts suffix glued at the very end and
    # cap the visible hook at ~70 chars so the first 5 words stay punchy.
    else:
        data["title"] = re.sub(r"\s*#shorts\s*", "", data["title"],
                               flags=re.I).strip() + " #shorts"
    for s in data["slides"]:
        s["image_query"] = s.get("image_query") or f"{niche} real photo"
    # --- SEO packaging (never empty / never missing tags) -------------------
    hook = re.sub(r"\s*#shorts\s*", "", data["title"], flags=re.I).strip()
    if lang == "fa":
        cta = "👇 نظرت رو کامنت کن! 🔔 سابسکرایب کن تا ویدیوی بعدی رو از دست ندی!"
        tags = ["#shorts", "#فارسی", "#ترند", "#پادیز",
                "#دانستنی", "#فکت", "#padiz_studio"]
        desc = (f"{hook}\n\n{cta}\n\n🌟 پادیز استودیو | کلیپ‌های روزانه\n"
                f"👉 https://instagram.com/padiz_studio\n\n"
                + " ".join(tags))
    else:
        cta = "👇 Comment below! 🔔 Subscribe so you never miss the next one!"
        tags = ["#shorts", "#trending", "#facts", "#viral", "#padiz_studio"]
        desc = (f"{hook}\n\n{cta}\n\n🌟 Padiz Studio | daily clips\n"
                f"👉 https://instagram.com/padiz_studio\n\n"
                + " ".join(tags))
    data["description"] = desc
    seen, merged = set(), []
    for t in list(data.get("tags") or []) + [t.lstrip("#") for t in tags]:
        tl = str(t).strip().lower()
        if tl and tl not in seen:
            seen.add(tl)
            merged.append(t)
    data["tags"] = merged[:15]
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
            {"title": "2 Hours of Lies!",
             "text": title[:60],
             "speech": f"Your brain lies to you 2 hours every night: {spoken}. Stay with me.",
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
            {"title": "۲ ساعت دروغ هر شب!",
             "text": title[:60],
             "speech": f"مغزت هر شب ۲ ساعت بهت دروغ می‌گه: {spoken}. بمون تا بگم چطور.",
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


def _speech_range(lang, slides=1):
    """Words for the single-slide narration, targeting a 40-70 second Short.

    The video length follows the audio automatically (pipeline.render derives
    each clip's duration from its TTS audio), so the range IS the runtime.
    """
    return (60, 110) if lang == "fa" else (60, 115)


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
        if not (d and isinstance(d.get("slides"), list)):
            continue
        # Was `== 3`, which silently discarded every single-slide Short (the
        # pipeline now writes exactly one full-screen slide), so the mined
        # drafts never reached the channel. Only require at least one slide.
        if len(d["slides"]) < 1:
            continue
        out.append(d)
    return out


def query_fallback(niche, lang):
    """Readable stand-in when a mined source came back without a title."""
    return str(niche or ("Online article" if lang == "en" else "مقالهٔ اینترنتی"))


def build_short(lang, niche=None, discovery=None, api_key=None, dry_run=False):
    """Write one new Short JSON from a discovery. Never raises."""
    api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    covered = _covered_titles()

    if discovery is None:
        try:
            import discover as D
            if niche is None:
                niche = D.niches_to_probe(lang, 1)[0]
            # Walk the ranked pool and take the first story NOT yet covered;
            # otherwise one already-made top item blocks every future Short.
            pool = (D._json_load(D.POOL_PATH, {}).get(lang) or {}).get("items", [])
            discovery = next(
                (it for it in pool
                 if _slug(it.get("title", "")) not in covered), None)
            discovery = discovery or D.best_for(lang) or {}
        except Exception as e:
            _log(f"[genshorts] discovery unavailable ({e})")
            discovery = {}
    niche = niche or discovery.get("niche") or ""
    if not niche:
        try:
            import discover as D
            niche = D.niches_to_probe(lang, 1)[0]
        except Exception:
            niche = "Interesting Facts" if lang == "en" else "دانستنی"

    # OWNER DIRECTIVE 2026-10-03: the repo only supplies the NICHE. The content
    # of the Short must come from the top-performing content found online for
    # that niche - so pull the best source text BEFORE writing.
    source_text = ""
    mined_meta = {}
    if _mine_enabled():
        try:
            import content_mine as CM
            mined = CM.mine(niche, lang)
            if mined:
                source_text = mined.get("text", "")
                # Explicit flag: run_daily gates on this. Deriving "was it
                # mined?" from a title string failed whenever a source had an
                # empty title, which silently blocked every Persian publish.
                mined_meta = {
                    "mined": True,
                    "mined_from": mined.get("source_title") or query_fallback(niche, lang),
                    "mined_url": mined.get("source_url", ""),
                    "mined_views": mined.get("views", 0),
                }
                _log(f"[genshorts] mined {mined.get('words')} words "
                     f"from {mined.get('views'):,} views")
        except Exception as e:
            _log(f"[genshorts] mining unavailable ({type(e).__name__}: {str(e)[:110]})")

    # The mined source IS the content of this Short, so its title wins over a
    # stale discovery-pool headline (which pointed at a different story).
    if source_text and mined_meta.get("mined_from"):
        discovery = dict(discovery or {})
        discovery["title"] = mined_meta["mined_from"]
        discovery.setdefault("niche", niche)
        discovery["source"] = "mined"
        discovery["views"] = mined_meta.get("mined_views", 0)
        discovery.setdefault("velocity", 0)

    suffix = _slug(discovery.get("title", ""))[:22] or (_slug(source_text)[:22] or "story")
    topic_id = f"{lang}_auto_{_slug(niche)[:20]}_{suffix}"
    if topic_id in covered:
        _log("[genshorts] this story is already covered - skipping")
        return None

    data = None
    gem_key = (api_key or "").strip()
    gem_title = str((discovery or {}).get("title") or "") if isinstance(discovery, dict) else ""
    if gem_key and (gem_title or source_text):
        prompt = _prompt(lang, niche, discovery, source_text=source_text)
        # Two attempts: a draft that misses one rule (usually a slide a couple of
        # words short) is worth one retry with the reason attached rather than
        # falling straight to the template.
        for attempt in (1, 2):
            data = _extract_json(_call_gemini(prompt, gem_key))
            reason = _reject_reason(data, lang) if data else "no JSON returned"
            if not reason:
                break
            _log(f"[genshorts] draft rejected ({reason})"
                 + ("" if attempt == 2 else " - retrying once"))
            if attempt == 2:
                data = None
            else:
                prompt += (
                    "\n\nIMPORTANT - your previous attempt was REJECTED because: "
                    + reason + ". Fix exactly that and return the corrected JSON only."
                )

    if data is None:
        # Owner directive 2026-10-03: the hand-written template is BANNED. Writing
        # filler ("the part nobody expected" / "save and follow") is worse than
        # publishing nothing, so a failed draft simply produces no Short.
        _log("[genshorts] gemini draft rejected twice - skipping this topic "
             "instead of using the banned template")
        return None

    data = _normalize(data, lang, niche, discovery, topic_id)
    data.update(mined_meta)
    if not dry_run:
        _json_save(os.path.join(GEN_DIR, f"{topic_id}.json"), data)
        _log(f"[genshorts] saved {topic_id} (fallback={data['fallback']})")
    return data


def top_up(lang, count):
    """Ensure `count` fresh dynamic Shorts exist for this language.

    Owner directive 2026-10-03: the repo supplies the NICHE, the internet
    supplies the content. So the niche list comes from topics_niches (the
    channel's approved list) and content_mine pulls the text - the old
    discovery_pool title is only a fallback when mining is off.
    """
    # Only PUBLISHABLE drafts count toward the target. Old drafts written before
    # mining was wired up carry no mined_from, and run_daily refuses those - so
    # counting them made top_up report "0 new" on an empty, unpublishable stock.
    existing = [t for t in load_generated()
                if t.get("lang") == lang and not t.get("posted")
                and not t.get("fallback") and (t.get("mined") or t.get("mined_from"))]
    if len(existing) < count:
        _log(f"[genshorts] {lang}: {len(existing)} publishable draft(s), "
             f"need {count - len(existing)} more")
    need = max(0, count - len(existing))
    made = []
    for _ in range(min(need, MAX_FRESH_PER_RUN)):
        try:
            item = _build_from_repo_niche(lang) if _mine_enabled() else build_short(lang)
        except Exception as e:
            _log(f"[genshorts] build failed ({e})")
            item = None
        if item:
            made.append(item)
    if not made:
        _log(f"[genshorts] {lang}: every approved niche failed to mine - "
             "nothing publishable this run")
    return made


def _norm_niche(s):
    """Loose niche key: folds ZWNJ, Arabic/Persian letter variants, punctuation.

    The analytics snapshot and topics_niches.py disagree on spelling in places
    ("حیات وحش و شگفتی‌های طبیعت" vs the repo's shorter forms, English casing,
    "The Psychology of Money" vs "money"). Folding them here is what makes the
    ranking actually connect to real data instead of matching 2 of 20.
    """
    s = str(s or "").strip().lower()
    s = s.replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    s = s.replace("ي", "ی").replace("ك", "ک")   # Arabic -> Persian
    s = s.replace("‌", " ")
    s = re.sub(r"^(the|a|an)\s+", "", s)
    s = re.sub(r"[^\w\s؀-ۿ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _niche_performance(lang):
    """Real per-niche performance of THIS channel, as a lookup that tolerates
    spelling differences between the analytics snapshot and the repo niche list.
    """
    try:
        import analytics as A
        raw = A.load_scores() or {}
    except Exception:
        raw = {}
    if not raw:
        # Fall back to the raw snapshot keys ("lang|niche" strings).
        try:
            import json
            hist = json.load(open("analytics_history.json", encoding="utf-8"))
            for k, v in (hist.get("scores") or {}).items():
                if "|" in k:
                    l, n = k.split("|", 1)
                    raw[(l, n)] = v
        except Exception:
            pass
    return {(_norm_niche(n), l): float(v) for (l, n), v in raw.items()}


def score_for(scores, lang, niche):
    """Exact key, then folded key, then a token-overlap best guess."""
    key = (_norm_niche(niche), lang)
    if key in scores:
        return scores[key]
    nk = _norm_niche(niche)
    if not nk:
        return 0.0
    tokens = {t for t in nk.split() if len(t) > 2}
    best, best_hits = 0.0, 0
    for (other, olang), val in scores.items():
        if olang != lang or not val:
            continue
        ot = {t for t in other.split() if len(t) > 2}
        hits = len(tokens & ot)
        if hits > best_hits or (hits == best_hits and hits and val > best):
            best, best_hits = val, hits
    # Need real overlap, not a single accidental word.
    return best if best_hits >= max(1, len(tokens) // 2) else 0.0


def _repo_niche_queue(lang):
    """Approved niches from the repo, ranked by what the channel already does
    well on, then least-recently-mined so nothing is starved.

    2026-10-03: was a plain round-robin (niches_to_probe order), which ignored
    the analytics entirely. Now proven performers are mined first, and the
    weakest niches keep a floor so they are still sampled occasionally.
    """
    try:
        import discover as D
        niches = list(D.niches_to_probe(lang, 40))
    except Exception:
        try:
            import topics_niches as N
            niches = list(N.EN_NICHES if lang == "en" else N.FA_NICHES)
        except Exception:
            return []

    scores = _niche_performance(lang)

    def rank(niche):
        return -score_for(scores, lang, niche)

    ranked = sorted(niches, key=rank)
    if scores:
        best = [n for n in ranked if score_for(scores, lang, n) > 0]
        rest = [n for n in ranked if score_for(scores, lang, n) <= 0]
        _log(f"[genshorts] niche ranking ({lang}): "
             + ", ".join(f"{n[:20]}={score_for(scores, lang, n):.1f}" for n in best[:5])
             + f" | {len(rest)} unproven after")
        ranked = best + rest
    return ranked[:6]


def _already_mined(niche):
    """Have we already made a Short from this niche? Avoids grinding one niche."""
    tag = _slug(niche)[:20]
    for t in load_generated():
        if t.get("lang") and tag and tag in str(t.get("id", "")):
            return True
    return False


def _build_from_repo_niche(lang):
    """Pick an approved niche from the repo and mine its best online text."""
    for niche in _repo_niche_queue(lang):
        if _already_mined(niche):
            continue
        item = build_short(lang, niche=niche)
        if item:
            return item
        _log(f"[genshorts] {niche!r} produced nothing - trying next niche")
    return None


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
