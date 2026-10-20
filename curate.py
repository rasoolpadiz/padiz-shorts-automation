# -*- coding: utf-8 -*-
"""curate.py — انتخاب «بهترین» ویدیو از میان کاندیداهای خام.

مشکلی که این ماژول حل می‌کند:
    نسخه‌ی اول ریپاست فقط «تعداد بازدید کل» را می‌دید. نتیجه‌اش این بود که
    محتوای کودکان و بازآپلودهای قدیمی همیشه بالا می‌آمدند و اولین ویدیویی که
    روی کانال رفت «Teamwork Toy Rescue: Clean Doll» بود — از نظر مالک کانال
    کاملاً بی‌معنی.

منطق جدید، سه لایه:

  ۱) فیلتر سخت (verdict) — چیزی که اصلاً نباید منتشر شود:
     افقی، کم‌کیفیت، خیلی قدیمی، کم‌بازدید، لایک‌نسبت پایین، محتوای کودکان/
     تریلر/موزیک‌ویدیو/تبلیغ هوش مصنوعی، کانال بلاک‌شده، age-restricted.

  ۲) امتیاز (score) — «ترند» یعنی سرعت، نه حجم:
        velocity   = بازدید / سن ویدیو به روز   ← معیار اصلی
        engagement = لایک / بازدید
        freshness  = پاداش کوچک برای تازگی
     یک ویدیوی ۵ میلیونی ۳ روزه از یک ۵۰ میلیونی ۲ ساله بهتر است.

  ۳) رتبه‌بندی نهایی و برگرداندن لیست مرتب‌شده.

متادیتا از خود یوتیوب گرفته می‌شود (yt-dlp، بدون دانلود) چون جست‌وجوی سطحی
تاریخ آپلود و تعداد لایک را نمی‌دهد.
"""

from __future__ import annotations

import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yt_dlp

LOG = logging.getLogger("shortsdl.curate")

# محتوایی که تجربه‌ی کانال را خراب می‌کند. عمداً در کانفیگ قابل تغییر است،
# ولی پیش‌فرض‌ها از روی همان ویدیویی نوشته شده که مالک کانال رد کرد.
DEFAULT_BLOCKED_KEYWORDS = [
    # کودکان / اسباب‌بازی / انیمیشن آموزشی
    "nursery", "cocomelon", "kids song", "kid song", "for kids", "toddler",
    "baby shark", "peppa", "blippi", "cartoon", "play doh", "playdoh",
    "surprise egg", "doll", "toy", "toys", "learn colors", "abc song",
    "wheels on the bus", "baby", "babies",
    # تریلر / فیلم / موزیک‌ویدیو
    "official trailer", "trailer", "teaser", "full movie", "movie clip",
    "music video", "official video", "lyrics", "full song", "audio song",
    "netflix", "prime video", "disney",
    # اسلای هوش مصنوعی و تبلیغات
    "#ai", "ai generated", "ai video", "ai comedy", "ai ad", "made with ai",
    "midjourney", "sora",
    # اسپم
    "free fire", "garena", "link in bio", "whatsapp", "telegram",
    "subscribe my", "sub4sub",
]

DEFAULTS = {
    "enabled": True,
    "max_age_days": 21,
    "min_views": 200_000,
    "min_like_ratio": 0.004,     # ۰.۴٪ — زیر این، ویدیو حسابی دیده نشده
    "min_res": 720,              # ضلع کوچک
    "max_duration_sec": 180,
    "blocked_keywords": DEFAULT_BLOCKED_KEYWORDS,
    "blocked_channels": [],
    "meta_workers": 4,
    "meta_timeout": 25,
    # وزن‌ها (قابل تنظیم؛ برای شفاف بودن در لاگ چاپ می‌شوند)
    "w_velocity": 10.0,
    "w_engagement": 120.0,
    "w_freshness": 0.6,
}


# --------------------------------------------------------------------------- #
# متادیتا
# --------------------------------------------------------------------------- #
def _ydl_opts(timeout: int) -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": int(timeout),
        "extract_flat": False,
    }


def fetch_meta(item: dict, timeout: int = 25) -> dict:
    """متادیتای کامل یک ویدیو را می‌گیرد و روی خودِ item ادغام می‌کند."""
    url = item.get("url") or f"https://www.youtube.com/shorts/{item.get('id')}"
    try:
        with yt_dlp.YoutubeDL(_ydl_opts(timeout)) as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except Exception as exc:  # noqa: BLE001
        item["meta_error"] = str(exc).splitlines()[0][:120]
        item["meta_ok"] = False
        return item

    item["meta_ok"] = True
    item["title"] = info.get("title") or item.get("title") or ""
    item["channel"] = info.get("channel") or item.get("channel") or ""
    item["views"] = info.get("view_count") or item.get("views") or 0
    item["likes"] = info.get("like_count") or 0
    item["comments"] = info.get("comment_count") or 0
    item["duration"] = info.get("duration") or item.get("duration") or 0
    item["width"] = info.get("width") or 0
    item["height"] = info.get("height") or 0
    item["upload_ts"] = info.get("timestamp") or 0
    item["upload_date"] = info.get("upload_date") or ""
    item["age_limit"] = info.get("age_limit") or 0
    item["was_live"] = bool(info.get("was_live"))
    item["followers"] = info.get("channel_follower_count") or 0
    item["categories"] = info.get("categories") or []
    item["tags"] = (info.get("tags") or [])[:15]
    return item


def enrich(items: list[dict], workers: int = 4, timeout: int = 25) -> list[dict]:
    """متادیتای همه‌ی کاندیداها را موازی می‌گیرد."""
    if not items:
        return []
    out: list[dict] = []
    workers = max(1, min(int(workers or 1), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_meta, dict(it), timeout): it for it in items}
        for fut in as_completed(futures):
            try:
                out.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                LOG.debug("متادیتا ناموفق: %s", exc)
    ok = sum(1 for it in out if it.get("meta_ok"))
    LOG.info("[curate] متادیتای %d از %d کاندید گرفته شد", ok, len(items))
    return out


# --------------------------------------------------------------------------- #
# پیش‌فیلتر ارزان (قبل از گرفتن متادیتا)
# --------------------------------------------------------------------------- #
def prefilter(items: list[dict], cfg: dict) -> list[dict]:
    """فیلتر سریع روی داده‌ی سطحی جست‌وجو (بدون شبکه).

    چرا لازم است: `discover_market` بر اساس بازدید خام مرتب می‌کند و فقط ۲۰
    نتیجه‌ی اول را برمی‌گرداند. اگر آن ۲۰ نتیجه همه محتوای کودکان باشند،
    ویدیوی خوبی که رتبه‌ی ۶۰ است هرگز به مرحله‌ی امتیازدهی نمی‌رسد. این فیلتر
    عنوان/کانال را همان‌جا رد می‌کند تا استخر واقعاً «محتوای قابل استفاده»
    باشد و متادیتا هم برای ویدیوهای بی‌فایده گرفته نشود.
    """
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    kws = [str(k).strip().lower() for k in (c.get("blocked_keywords") or []) if str(k).strip()]
    blocked_ch = {str(x).strip().lower() for x in (c.get("blocked_channels") or [])}
    max_dur = float(c.get("max_duration_sec", 180))

    out = []
    for it in items:
        blob = f"{it.get('title') or ''} {it.get('channel') or ''}".lower()
        if any(k in blob for k in kws):
            continue
        if (it.get("channel") or "").strip().lower() in blocked_ch:
            continue
        dur = it.get("duration")
        if dur and float(dur) > max_dur:
            continue
        out.append(it)
    return out


# --------------------------------------------------------------------------- #
# فیلتر سخت
# --------------------------------------------------------------------------- #
def _text_blob(item: dict) -> str:
    parts = [item.get("title") or "", item.get("channel") or ""]
    parts.extend(item.get("tags") or [])
    parts.extend(item.get("categories") or [])
    return " ".join(parts).lower()


def verdict(item: dict, cfg: dict, now: float | None = None) -> tuple[bool, str]:
    """(قابل انتشار؟, دلیل رد) — دلیل برای لاگ است."""
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    now = now or time.time()

    if not item.get("meta_ok"):
        return False, f"متادیتا نیامد ({item.get('meta_error', '?')})"

    w, h = int(item.get("width") or 0), int(item.get("height") or 0)
    if not w or not h:
        return False, "ابعاد نامعلوم"
    if h <= w:
        return False, f"افقی {w}x{h}"
    if min(w, h) < int(c["min_res"]):
        return False, f"کیفیت پایین {w}x{h} < {c['min_res']}p"

    dur = float(item.get("duration") or 0)
    if dur <= 0:
        return False, "مدت نامعلوم"
    if dur > float(c["max_duration_sec"]):
        return False, f"بلندتر از {c['max_duration_sec']}s ({int(dur)}s)"

    views = int(item.get("views") or 0)
    if views < int(c["min_views"]):
        return False, f"بازدید کم ({views:,})"

    ts = int(item.get("upload_ts") or 0)
    if ts:
        age_days = max(0.0, (now - ts) / 86400.0)
        if age_days > float(c["max_age_days"]):
            return False, f"قدیمی ({age_days:.0f} روز)"

    likes = int(item.get("likes") or 0)
    if views and likes:
        ratio = likes / views
        if ratio < float(c["min_like_ratio"]):
            return False, f"نسبت لایک پایین ({ratio*100:.2f}%)"

    if int(item.get("age_limit") or 0) > 0:
        return False, "محدود به سن"
    if item.get("was_live"):
        return False, "پخش زنده"

    blob = _text_blob(item)
    for kw in (c.get("blocked_keywords") or []):
        k = str(kw).strip().lower()
        if k and k in blob:
            return False, f"کلمه‌ی بلاک‌شده «{k}»"

    channel = (item.get("channel") or "").strip().lower()
    for bc in (c.get("blocked_channels") or []):
        b = str(bc).strip().lower()
        if b and b == channel:
            return False, f"کانال بلاک‌شده «{b}»"

    return True, ""


# --------------------------------------------------------------------------- #
# امتیاز
# --------------------------------------------------------------------------- #
def score(item: dict, cfg: dict, now: float | None = None) -> float:
    """امتیاز «ترند بودن». بزرگ‌تر = بهتر."""
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    now = now or time.time()

    views = max(1, int(item.get("views") or 0))
    ts = int(item.get("upload_ts") or 0)
    age_days = max(0.25, (now - ts) / 86400.0) if ts else 30.0
    velocity = views / age_days                     # بازدید در روز
    likes = int(item.get("likes") or 0)
    engagement = (likes / views) if views else 0.0

    s = float(c["w_velocity"]) * math.log10(max(velocity, 1.0))
    s += float(c["w_engagement"]) * engagement
    s += float(c["w_freshness"]) * max(0.0, float(c["max_age_days"]) - age_days)
    return s


def rank(items: list[dict], cfg: dict, want: int | None = None) -> list[dict]:
    """کاندیداها را فیلتر، امتیازدهی و مرتب می‌کند.

    تنوع عمدی است: بدون آن، چهار کاندید برتر از چهار کانال «فکت فضایی» می‌آمدند
    و کانال یک‌شبه تبدیل می‌شد به کانال فکت فضایی. حالا در ابتدای لیست حداکثر
    یکی از هر کانال و یکی از هر کوئری می‌آید؛ بقیه به‌عنوان ذخیره (اگر دانلود
    یا آپلود اولی شکست خورد) بعد از آن‌ها می‌آیند.
    """
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    now = time.time()

    kept, rejected = [], []
    for it in items:
        ok, why = verdict(it, c, now)
        if ok:
            it["score"] = round(score(it, c, now), 2)
            it["velocity"] = int((it.get("views") or 0) / max(0.25, (now - int(it.get("upload_ts") or 0)) / 86400.0)) if it.get("upload_ts") else 0
            kept.append(it)
        else:
            it["reject"] = why
            rejected.append(it)

    kept.sort(key=lambda x: x["score"], reverse=True)
    rejected.sort(key=lambda x: x.get("views") or 0, reverse=True)

    # تنوع: اول انتخاب متنوع، بعد بقیه به‌عنوان ذخیره
    if c.get("diversify", True):
        max_ch = int(c.get("max_per_channel", 1) or 1)
        max_q = int(c.get("max_per_niche", 1) or 1)
        head, rest = [], []
        ch_seen: dict[str, int] = {}
        q_seen: dict[str, int] = {}
        for it in kept:
            ch = (it.get("channel") or "").strip().lower()
            # گروه موضوعی (niche) ملاک است، نه متن کوئری: «۶ کوئری طنز» یک
            # موضوع‌اند و نباید شش جا اشغال کنند.
            q = (it.get("niche") or it.get("query") or "").strip().lower()
            if ch_seen.get(ch, 0) >= max_ch or q_seen.get(q, 0) >= max_q:
                rest.append(it)
                continue
            head.append(it)
            ch_seen[ch] = ch_seen.get(ch, 0) + 1
            q_seen[q] = q_seen.get(q, 0) + 1
        kept = head + rest

    LOG.info("[curate] %d کاندید پذیرفته، %d رد شد", len(kept), len(rejected))
    for it in kept[: (want or 5)]:
        LOG.info("  ✔ %6.1f | %4.1fM/روز | %-14s | %s…",
                 it["score"], (it.get("velocity") or 0) / 1e6,
                 (it.get("niche") or it.get("query") or "")[:14], (it.get("title") or "")[:44])
    for it in rejected[:6]:
        LOG.info("  ✘ %-34s | %s…", it.get("reject", "?"), (it.get("title") or "")[:38])
    return kept
