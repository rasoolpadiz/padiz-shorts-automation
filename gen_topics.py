# -*- coding: utf-8 -*-
"""Turn an approved niche into a complete, ready-to-render long-form topic.

The owner supplies the niche lists (topics_niches.py: 85 EN / 19 FA). This module
writes full 14-scene topics into topics_generated/ so the daily runner always has
fresh material and never repeats a topic.

Design rules baked into the prompt (DESIGN_SPEC.md):
  * scene 1 is a 0-15s cold open: pattern interrupt -> beat -> promise
  * every 3-4 scenes there is a curiosity gap or a list promise
  * scenes breathe: 14 scenes x ~90-100 words of narration = ~8-10 minutes
    (at ~150wpm, 8-10 min = 1200-1500 words, so 14 x ~95 = ~1330 words)
  * Persian narration is written for the ear, not for the page
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import topics_niches as N

HERE = os.path.dirname(os.path.abspath(__file__))
GEN_DIR = os.path.join(HERE, "topics_generated")
USED_NICHES = os.path.join(GEN_DIR, "used_niches.json")

SCENES = 14
# Target words per scene when the writer is generating. At ~150wpm an 8-10 min
# video needs 1200-1500 words, so 14 scenes x ~90-100 words = ~1260-1400 words.
WORDS_PER_SCENE = {"en": 95, "fa": 90}
MAX_WORDS_PER_SCENE = {"en": 160, "fa": 150}

HOOK_EN = """\
OPEN with a cold open that wins the first 15 seconds:
- sentence 1: a hard, specific, slightly shocking claim or number (no "in this video")
- sentence 2: a short beat that reframes it
- sentence 3: the promise - exactly what the viewer gets and by when
No greeting, no "hey guys", no channel name. Write it to be spoken out loud."""

HOOK_FA = """\
شروع ویدیو باید ۱۵ ثانیهٔ اول را بگیرد:
- جملهٔ اول: یک ادعای مشخص و شوک‌آور (عدد یا واقعیت) — بدون «سلام» و بدون «در این ویدیو»
- جملهٔ دوم: یک مکث کوتاه که زاویه را عوض می‌کند
- جملهٔ سوم: وعدهٔ ویدیو — دقیقاً چه چیزی و تا چه حد
لحن محاوره‌ای و طبیعی، مثل حرف زدن با یک دوست. برای گوش نوشته شود نه برای صفحه."""


def _json_load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _json_save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _slug(text, ascii_only=True):
    if ascii_only:
        s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
        return s or "topic"
    s = re.sub(r"[^\w\u0600-\u06FF]+", "_", str(text), flags=re.UNICODE).strip("_")
    return s or "topic"


def niche_queue(lang):
    """Niches still unused, ordered so proven winners are made more often.

    Owner directive 2026-10-01: "ویدیوهایی که بازدید می‌خورند را بیشتر کن".
    A niche is promoted when its real YouTube score is above the channel median;
    a niche that has been used recently is only demoted, never hard-blocked, so
    a proven winner can come back after the cooldown.

    If analytics_history.json is missing (first run, or the collector failed) the
    owner's approved order is returned untouched - the old behaviour.
    """
    used = _json_load(USED_NICHES, {})
    pool = N.EN_NICHES if lang == "en" else N.FA_NICHES
    used_set = set(used.get(lang, []))

    try:
        import analytics as A
        scores = A.load_scores()
    except Exception:
        scores = {}
    if not scores:
        return [x for x in pool if x not in used_set]

    # Never re-pick something published in the last couple of weeks.
    try:
        import analytics as A
        cooling = A.recent_niches(lang, days=7)
    except Exception:
        cooling = set()

    def rank(niche):
        score = A.family_score(lang, niche, scores) if scores else 1.0
        if niche in cooling:
            score -= 0.5          # deprioritise, not block
        return -score

    candidates = [x for x in pool if x not in used_set or x in cooling]
    if not candidates:
        candidates = list(pool)
    return sorted(candidates, key=rank)


def mark_niche_used(lang, niche):
    used = _json_load(USED_NICHES, {})
    used.setdefault(lang, [])
    if niche not in used[lang]:
        used[lang].append(niche)
    _json_save(USED_NICHES, used)



def _fallback_scene(idx, lang, niche):
    """Enhanced fallback scenes with compelling storytelling structure."""
    
    # Persian enhanced content with proper pacing and emotional hooks
    if lang == "fa":
        scenes_fa = {
            1: {
                "title": "حقیقتی که یادتان رفت",
                "text": "۸۵ درصد آدم‌ها این را درک نمی‌کنند",
                "image_query": f"{niche} محل کار واقعی",
                "speech": "۸۵ درصد مردم یک اشتباه اساسی درباره‌ی این موضوع می‌کنند. نتیجه‌ش؟ سال‌ها وقت تلف می‌شود. اما وقتی می‌فهمی اینجا چی اتفاق می‌افتد، همه چیز تغییر می‌کنه.",
            },
            2: {
                "title": "چرا اهمیت دارد",
                "text": "هزینهٔ نفهمیدن این موضوع",
                "image_query": f"{niche} اثر منفی",
                "speech": "اگر برای ۶ ماه دیگر این را نادیده بگیری، هزینه‌اش سالانه ۵۰۰ هزار تومان می‌شه. ولی بیشتر آدم‌ها تا وقتی مسئله بزرگ شه، اقدام نمی‌کنند.",
            },
            3: {
                "title": "مکانیزم اصلی",
                "text": "چگونه این اتفاق می‌افتد",
                "image_query": f"{niche} ساختار",
                "speech": "عمل درخت‌ها اینجوریه: ابتدا کوچک شروع می‌شه، بعد خیلی سریع رشد می‌کنه، و وقتی می‌خوای کنترلش کنی، خیلی دیره.",
            },
            4: {
                "title": "مثال واقعی ۱",
                "text": "اتفاقی که در سال ۲۰۲۳ افتاد",
                "image_query": f"{niche} کاربرد عملی",
                "speech": "یک کارمند تک‌رو بود که موارد این مسئله را درست مدیریت کرد. در ۳ ماه، بهره‌وری ۴۰ درصد بالا رفت. دنبال کردن چه بود؟ تنها سه قاعدهٔ ساده.",
            },
            5: {
                "title": "قاعدهٔ اول",
                "text": "نقطهٔ شروع",
                "image_query": f"{niche} ابتدایی",
                "speech": "قاعدهٔ اول اینه: قبل‌تر از هر کاری، مشکل و‌جود دارد؟ اکثریت بدون فکر، عجله می‌کنند. غلط.",
            },
            6: {
                "title": "قاعدهٔ دوم",
                "text": "اجرای درست",
                "image_query": f"{niche} فرآیند",
                "speech": "دوم: اجرا را به شکل‌های مختلف امتحان کن. هر وضعیت منحصر‌به‌فرد است. اگر کپی کردی، آن کار نمی‌کنه.",
            },
            7: {
                "title": "قاعدهٔ سوم",
                "text": "نتیجه‌گیری و سازگاری",
                "image_query": f"{niche} نتیجه‌ای بهتر",
                "speech": "سوم: نتایج را اندازه بگیر. اگر بهتر شد، ادامه بده. اگر نه، چرا‌ی آن را بفهم و تغییر بده.",
            },
            8: {
                "title": "غافل‌گیری",
                "text": "چیزی که تصور نمی‌کنی",
                "image_query": f"{niche} غیرمنتظره",
                "speech": "حالا به یک موضوع غیرمنتظره می‌رسیم: اکثر سازمان‌ها درست‌ترین روش را انتخاب نمی‌کنند. اونا راه‌ای را انتخاب می‌کنند که سریع‌ترینه، حتی اگر مضره باشه.",
            },
            9: {
                "title": "آمار واقعی",
                "text": "تحقیقات نشان داده‌اند",
                "image_query": f"{niche} آمار و داده",
                "speech": "براساس تحقیقات ۲۰۲۴، ۷۲ درصد شرکت‌هایی که به‌درستی اجرا کردند، در بازار رقابتی ۲۵ درصد جلوتر رفتند.",
            },
            10: {
                "title": "افزایش شدت",
                "text": "وقتی چیزها پیچیده‌تر می‌شوند",
                "image_query": f"{niche} چالش‌های پیشرفته",
                "speech": "اما درست اینجاست که مسئله پیچیده‌تر می‌شه. چرا؟ زیرا محیط تغییر می‌کنه. دیروز‌ی راه، امروز کار نمی‌کنه.",
            },
            11: {
                "title": "شکاف کنجکاوی",
                "text": "چگونه بازگشت می‌آید",
                "image_query": f"{niche} انطباق",
                "speech": "سوال پیش می‌آید: پس اگر شرایط تغییر کنه، من باید هر بار صفر شروع کنم؟ جواب: نه. یک ساختار بنیادین وجود داره که تغییر نمی‌کنه.",
            },
            12: {
                "title": "اصل بنیادین",
                "text": "قانون تغییرناپذیر",
                "image_query": f"{niche} اساس",
                "speech": "این اصل اینه: پایه‌ی قوی بماند، بقیه‌ی طراحی را بازنویسی کن. اینطور کار می‌کنه در هر شرایطی.",
            },
            13: {
                "title": "مثال دوم",
                "text": "شرکتی که ۲۰۰ نفری است",
                "image_query": f"{niche} تیم بزرگ",
                "speech": "یک شرکت ۲۰۰ نفری این اصل رو پیاده کرد. نتیجه: در ۹ ماه، نرخ بازده کارکنان ۶۰ درصد رشد پیدا کرد.",
            },
            14: {
                "title": "اقدام مشخص",
                "text": "یک کاری بکن الآن",
                "image_query": f"{niche} اقدام فوری",
                "speech": "اگر امروز شروع کنی، سی روز بعد خودت معمول نیست. سال بعد؟ تقریباً شناخت‌نشدنی. پس امروز فقط یک کاری کن. اگر موافق بودی اینجا رو دنبال کن، سابسکرایب کن و زنگ را فعال کن تا تغییر را ببینی.",
            },
        }
        
        if idx in scenes_fa:
            return scenes_fa[idx]
        else:
            # Fallback for any missing scene
            return {
                "title": f"بخش {idx}: {niche}",
                "text": f"نقطهٔ {idx} برای فهم {niche}",
                "image_query": f"{niche} بخش {idx}",
                "speech": f"در این بخش درباره‌ی جنبهٔ {idx}ام از {niche} صحبت می‌کنیم. این نقطه برای درک کامل موضوع کلیدی است.",
            }
    
    # English fallback (improved)
    if lang == "en":
        return {
            "title": f"Part {idx}: {niche}",
            "text": f"The hidden {niche.lower()} factor",
            "image_query": f"{niche.lower()} real world application",
            "speech": (f"Here's the part most people miss about {niche.lower()}. "
                       f"When you finally see it, it's obvious. But almost nobody acts. "
                       f"Let's walk through exactly what happens when you do it right. "
                       f"Most people learn this the hard way - you're about to get it in 90 seconds."),
        }
    
    return {}


def validate(topic, lang):
    """Hard checks - a topic that fails these must never reach the renderer."""
    problems = []
    if not topic or not topic.get("title"):
        problems.append("missing title")
    scenes = (topic or {}).get("scenes") or []
    # Legacy 22-scene topics (hand-written, already published style) still pass:
    # only NEW generation is fixed at 14. Anything far outside both is rejected.
    if len(scenes) not in (SCENES, 22):
        problems.append(f"expected {SCENES} scenes, got {len(scenes)}")
    for i, s in enumerate(scenes, 1):
        if not s.get("speech", "").strip():
            problems.append(f"scene {i} has no speech")
        if not s.get("image_query", "").strip():
            problems.append(f"scene {i} has no image_query")
        words = len(str(s.get("speech", "")).split())
        if words > MAX_WORDS_PER_SCENE[lang]:
            problems.append(f"scene {i} too long ({words} words)")
        # Floor 50 words/scene: 14 NEW scenes x 50 = 700 min floor guard would be
        # too short alone, but MIN_TOTAL_WORDS (1200) does the real 8-min job;
        # legacy 22-scene files (~65w/scene) must not trip here.
        if words < 50:
            problems.append(f"scene {i} too short ({words} words, need 50+)")
    if len({s.get("image_query", "") for s in scenes}) < len(scenes) * 0.8:
        problems.append("image queries are too repetitive")
    return problems



def _research_brief(lang, niche):
    """What discovery found online inside this niche, as a writer's brief.

    Owner directive 2026-10-01: stop handing the writer a bare niche - give it
    the story that is actually hot right now. Returns "" when nothing is cached,
    so the writer behaves exactly as before.
    """
    try:
        import discover as D
        items = (D._json_load(D.POOL_PATH, {}).get(lang) or {}).get("items", [])
    except Exception:
        return ""
    picked = [i for i in items if i.get("niche") == niche][:5]
    if not picked:
        picked = items[:5]
    if not picked:
        return ""
    lines = []
    for it in picked:
        vel = it.get("velocity") or 0
        lines.append(
            f'- "{it["title"]}" ({it.get("source","")}, {it.get("views",0):,} views,'
            f' {vel:,.0f} views/hour)'
        )
    head = (
        'REAL-WORLD RESEARCH (found online today, use as raw material - do NOT copy '
        'these videos, do NOT mention other channels or their titles):\n'
        if lang == "en" else
        'تحقیق واقعی (امروز از اینترنت پیدا شده - مادهٔ خام توست، ویدیوها را کپی نکن و اسم کانال\u200cهای دیگر را نبر):\n'
    )
    tail = (
        "\nTurn the strongest of these angles into an ORIGINAL story for our own "
        "audience. Add your own analysis, numbers and examples."
        if lang == "en" else
        '\nقویت\u200cترین زاویه را به داستانی تازه برای مخاطب خودمان تبدیل کن. تحلیل، عدد و مثال خودت را اضافه کن.'
    )

    return head + "\n".join(lines) + tail


def _prompt(lang, niche):
    w = WORDS_PER_SCENE[lang]
    hook = HOOK_EN if lang == "en" else HOOK_FA
    if lang == "en":
        shape = f"""Write a long-form video script in NATIVE, CONVERSATIONAL English.
Exactly {SCENES} scenes. Each scene's "speech" must be {w}-110 words when spoken
comfortably - that is what gets the video to 8-10 minutes
(14 scenes x ~95 words = ~1330 words = ~8.9 min at 150wpm).

Scene roles must follow this retention shape:
  1  cold open (see below) - the most important scene
  2  why this matters / the cost of ignoring it
  3  the core mechanism or the rule
  4-7  the main body: concrete, specific, one idea per scene
  8  the first payoff or a surprising reveal
  9-11  more body, escalate, add a curiosity gap
  12  the counter-argument, then why it still wins
  13  the practical fixes / takeaways + long-term payoff
  14  a concrete call to action

{hook}

Writing rules:
- short punchy sentences, spoken out loud, contractions everywhere
- NO filler ("in this video", "let's dive in", "without further ado")
- concrete numbers and named examples instead of vague claims
- every scene opens on a new idea - never a continuation
- "title": 2-5 words, punchy, no emoji
- "text": ONE short on-screen line, max 9 words
- "image_query": 3-5 words describing a REAL photograph of a real place or object.
  Never a diagram, chart, map, scan, document, newspaper or infographic."""
    else:
        shape = f"""یک متن ویدیوی بلند به زبان فارسی طبیعی و محاوره‌ای بنویس.
دقیقاً {SCENES} صحنه. هر صحنه «speech» باید {w} تا ۱۱۰ کلمه باشد تا گفتار طبیعی به
۸ تا ۱۰ دقیقه برسد (۱۴ صحنه × ~۹۰ کلمه = ~۱۲۶۰ کلمه) - همین متن‌ها خوانده می‌شوند، پس برای گوش نوشته شود.

ساختار نگهدارندهٔ توجه:
  ۱  شروع سرد (پایین) - مهم‌ترین صحنه
  ۲  چرا مهم است / هزینهٔ نادیده گرفتنش
  ۳  مکانیزم یا قانون اصلی
  ۴-۷  بدنهٔ اصلی: ملموس، مشخص، هر صحنه یک ایده
  ۸  اولین نتیجه یا یک غافلگیری
  ۹-۱۱ ادامهٔ بدنه با شدت بیشتر و شکاف کنجکاوی
  ۱۲  ضدِArgument و دلیل اینکه باز هم درست است
  ۱۳  راه‌حل‌ها و نکات عملی + نتیجهٔ بلندمدت
  ۱۴  دعوت به اقدام مشخص

{hook}

قواعد نگارش:
- جمله‌های کوتاه و محاوره‌ای، مخصوص گفتن با صدای بلند
- بدون «سلام» ، «بچه‌ها» ، «در این ویدیو» ، «بریم که ببینیم»
- عدد و مثال مشخص به‌جای ادعای کلی
- هر صحنه با ایدهٔ تازه شروع شود
- «title»: ۲ تا ۴ کلمه، کوبنده، بدون ایموجی
- «text»: فقط یک جملهٔ کوتاه روی تصویر، حداکثر ۸ کلمه
- «image_query»: ۳ تا ۵ کلمه توصیف عکس واقعی از یک مکان یا شیء واقعی.
  هرگز نمودار، چارت، نقشه، اسکن، سند، روزنامه یا اینفوگرافیک نباشد."""
    brief = _research_brief(lang, niche)
    research_block = f"\n{brief}\n" if brief else ""
    return f"""You are the head writer for a high-retention YouTube channel.
Channel: "Padiz Studio". Approved content niche for this video: **{niche}**.
{research_block}
{shape}

Return ONLY valid JSON, no markdown fence, no commentary, in exactly this shape:

{{
  "title": "...",
  "thumbnail_text": "2-4 words, all caps, max 22 characters",
  "series": "...",
  "hook": "the single opening line, spoken first",
  "description": "3 short paragraphs separated by blank lines. First line states the "
                 "value. Last line says what the channel is about.",
  "cta": "one sentence",
  "tags": ["tag", "tag", "tag", "tag", "tag", "tag", "tag", "tag", "tag", "tag"],
  "scenes": [
    {{"title": "...", "text": "...", "speech": "...", "image_query": "..."}}
  ]
}}"""


def _call_gemini(prompt, api_key):
    from google import genai
    from google.genai import types as genai_types
    client = genai.Client(api_key=api_key)
    # Use the latest models first - older models are deprecated
    for model in ("gemini-3.8-flash", "gemini-2.5-flash-preview", "gemini-2.0-flash"):
        try:
            r = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=1.0,
                ),
            )
            if r.text:
                return r.text
        except Exception as e:
            print(f"[gen] {model} failed: {e}")
    return None


def _extract_json(text):
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None


def build_topic(lang, niche=None, api_key=None, dry_run=False):
    """Create one ready-to-render topic and save it. Never raises."""
    api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if niche is None:
        queue = niche_queue(lang)
        # Every approved niche used: recycle the list from the start.
        niche = queue[0] if queue else (N.EN_NICHES if lang == "en" else N.FA_NICHES)[0]

    print(f"[gen] building {lang} topic from niche: {niche}")
    data = None
    if api_key:
        data = _extract_json(_call_gemini(_prompt(lang, niche), api_key))
    else:
        print("[gen] no GEMINI_API_KEY - using template fallback")

    problems = validate(data, lang)
    if problems:
        print(f"[gen] generation rejected ({'; '.join(problems[:4])}) - using template")
        data = None

    if data is None:
        data = {
            "title": f"{niche}: The Full Picture" if lang == "en" else f"{niche}؛ تصویر کامل",
            "thumbnail_text": niche[:20] if lang == "en" else niche[:14],
            "series": niche,
            "hook": "",
            "description": (f"An in-depth look at {niche}." if lang == "en"
                            else f"نگاهی عمیق به {niche}."),
            "cta": "Subscribe for more." if lang == "en" else "برای ویدیوهای بیشتر سابسکرایب کنید.",
            "tags": [niche],
            "scenes": [_fallback_scene(i, lang, niche) for i in range(1, SCENES + 1)],
        }

    data.update({
        "id": f"{lang}_long_{_slug(niche)[:28]}",
        "lang": lang,
        "niche": niche,
        "series": data.get("series") or niche,
        "voice_index": 0,
        "music": "cinematic",
        "privacy": "public",
        # A template topic is a last resort - the runner refuses to publish it
        # unless the owner explicitly allows it, so the channel never gets filler.
        "fallback": bool(problems),
    })
    if not data.get("hook"):
        data["hook"] = data["scenes"][0].get("speech", "")[:180]

    if not dry_run:
        _json_save(os.path.join(GEN_DIR, f"{data['id']}.json"), data)
        mark_niche_used(lang, niche)
        print(f"[gen] saved {data['id']} ({len(data['scenes'])} scenes)")
    return data


def load_generated():
    """Every generated topic currently on disk."""
    if not os.path.isdir(GEN_DIR):
        return []
    out = []
    for name in sorted(os.listdir(GEN_DIR)):
        if name.endswith(".json") and not name.startswith("used_niches"):
            t = _json_load(os.path.join(GEN_DIR, name), None)
            if t and t.get("scenes"):
                out.append(t)
    return out


if __name__ == "__main__":
    lang = sys.argv[1] if len(sys.argv) > 1 else "en"
    niche = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    t = build_topic(lang, niche, dry_run="--dry" in sys.argv)
    print(json.dumps({"id": t["id"], "title": t["title"], "scenes": len(t["scenes"])},
                     ensure_ascii=False))

