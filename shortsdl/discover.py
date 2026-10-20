"""کشف کاندیداهای Short و رتبه‌بندی آن‌ها بر اساس تعداد بازدید.

روش کار:
    از جست‌وجوی خود یوتیوب با پارامتر `sp=CAMSAhgB` استفاده می‌کنیم که یعنی
    «مرتب‌سازی بر اساس تعداد بازدید + فقط ویدیوهای کوتاه (زیر ۴ دقیقه)».
    به این ترتیب نتایج هر کوئری از پربازدیدترین شورت‌های همان موضوع شروع می‌شوند.

    سپس همه‌ی نتایج یکتا می‌شوند، فیلترهای مدت/بازدید اعمال و بر اساس بازدید
    نزولی مرتب می‌شوند. برای بازار فارسی، فیلتر «خط فارسی» هم اعمال می‌شود تا
    محتوای غیرفارسی حذف شود.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlencode

import yt_dlp

from .utils import human_duration, human_views

LOG = logging.getLogger("shortsdl.discover")

# sp: sort=view_count (08 03) + duration=short (12 02 18 01)
SP_VIEWS_SHORT = "CAMSAhgB"
# sp: فقط مرتب‌سازی بر اساس بازدید (بدون فیلتر مدت)
SP_VIEWS = "CAM%3D"

SEARCH_URL = "https://www.youtube.com/results"

# مقادیر مجاز فیلترهای یوتیوب
SORT_BY = {"relevance": 0, "rating": 1, "date": 2, "views": 3}
UPLOAD_DATE = {"hour": 1, "today": 2, "week": 3, "month": 4, "year": 5}
DURATION = {"short": 1, "long": 2, "medium": 3}


def _varint(value: int) -> bytes:
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        out += bytes([byte | (0x80 if value else 0)])
        if not value:
            return out


def build_sp(sort: str | None = None, upload: str | None = None,
             duration: str | None = None) -> str:
    """پارامتر `sp` یوتیوب را از فیلترهای خوانا می‌سازد (protobuf + base64).

    مثال: build_sp("views", None, "short") == "CAMSAhgB"
    ترند = پربازدیدترین‌های این هفته:  build_sp("views", "week", "short")
    """
    msg = b""
    if sort:
        msg += b"\x08" + _varint(SORT_BY[sort])
    inner = b""
    if upload:
        inner += b"\x08" + _varint(UPLOAD_DATE[upload])   # فیلد ۱: تاریخ آپلود
    if duration:
        inner += b"\x18" + _varint(DURATION[duration])    # فیلد ۳: مدت
    if inner:
        msg += b"\x12" + _varint(len(inner)) + inner
    return base64.urlsafe_b64encode(msg).decode().rstrip("=")

# حروف خط عربی/فارسی
_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN = re.compile(r"[A-Za-z]")


def _ydl_opts(proxy: str | None, cookies: str | None, count: int) -> dict:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": False,
        "playlistend": int(count),
        "socket_timeout": 25,
        "geo_bypass": True,
        "extract_flat": "in_playlist",
    }
    if proxy:
        opts["proxy"] = proxy
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def search(
    query: str,
    count: int,
    sp: str | None = SP_VIEWS_SHORT,
    gl: str | None = None,
    hl: str | None = None,
    proxy: str | None = None,
    cookies: str | None = None,
) -> list[dict]:
    """جست‌وجوی یوتیوب با مرتب‌سازی بر اساس بازدید و برگرداندن نتایج سطحی."""
    params = {"search_query": query}
    if sp:
        params["sp"] = sp
    if gl:
        params["gl"] = gl
    if hl:
        params["hl"] = hl
    url = f"{SEARCH_URL}?{urlencode(params)}"

    try:
        with yt_dlp.YoutubeDL(_ydl_opts(proxy, cookies, count)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("جست‌وجو ناموفق بود (%s): %s", query, exc)
        return []
    return list((info or {}).get("entries") or [])


def looks_persian(*texts: str) -> bool:
    """آیا متن (عنوان/کانال) عمدتاً فارسی/عربی است؟"""
    text = " ".join(t for t in texts if t)
    if not text.strip():
        return False
    arabic = len(_ARABIC_SCRIPT.findall(text))
    latin = len(_LATIN.findall(text))
    if arabic == 0:
        return False
    return arabic >= max(2, latin)


def _normalize(entry: dict, query: str) -> dict | None:
    vid = entry.get("id")
    if not vid or len(str(vid)) != 11:
        return None
    return {
        "id": vid,
        "title": (entry.get("title") or "").strip(),
        "channel": entry.get("channel") or entry.get("uploader") or "",
        "views": entry.get("view_count") or 0,
        "duration": entry.get("duration"),
        "url": f"https://www.youtube.com/shorts/{vid}",
        "live_status": entry.get("live_status"),
        "query": query,
    }


def discover_market(
    market: str,
    market_cfg: dict,
    filters: dict,
    limit: int,
    results_per_query: int = 25,
    request_delay: float = 1.0,
    proxy: str | None = None,
    cookies: str | None = None,
    search_workers: int = 4,
) -> list[dict]:
    """کاندیداهای یک بازار (global/persian) را جمع و بر اساس بازدید مرتب می‌کند."""
    queries = market_cfg.get("queries") or []
    max_dur = market_cfg.get("max_duration_sec", filters.get("max_duration_sec") or 180)
    min_views = filters.get("min_views") or 0
    skip_live = filters.get("skip_live", True)
    if market_cfg.get("filters_sp"):
        f = market_cfg["filters_sp"]
        sp = build_sp(f.get("sort"), f.get("upload"), f.get("duration"))
    else:
        sp = market_cfg.get("sp", SP_VIEWS_SHORT)
    gl = market_cfg.get("region_code")
    hl = market_cfg.get("relevance_language")
    script = (market_cfg.get("require_script") or "").lower()
    url_template = market_cfg.get("url_template", "https://www.youtube.com/shorts/{id}")
    LOG.info("[%s] فیلتر جست‌وجو: sp=%s", market, sp)

    found: dict[str, dict] = {}

    def _one(query: str) -> tuple[str, list[dict]]:
        return query, search(query, results_per_query, sp=sp, gl=gl, hl=hl,
                             proxy=proxy, cookies=cookies)

    # جست‌وجوها موازی اجرا می‌شوند تا کشف سریع تمام شود
    with ThreadPoolExecutor(max_workers=max(1, min(search_workers, len(queries) or 1))) as pool:
        futures = [pool.submit(_one, q) for q in queries]
        for i, fut in enumerate(as_completed(futures), 1):
            query, raw = fut.result()
            LOG.info("[%s] جست‌وجو %d/%d: %s (%d نتیجه)", market, i, len(queries), query, len(raw))
            kept = 0
            for entry in raw:
                item = _normalize(entry, query)
                if not item:
                    continue
                item["url"] = url_template.format(id=item["id"])
                if skip_live and item["live_status"] in ("is_live", "is_upcoming"):
                    continue
                if max_dur and item["duration"] and item["duration"] > max_dur:
                    continue
                if item["views"] and item["views"] < min_views:
                    continue
                if script == "persian" and not looks_persian(item["title"], item["channel"]):
                    continue
                kept += 1
                prev = found.get(item["id"])
                if prev is None or (item["views"] or 0) > (prev["views"] or 0):
                    found[item["id"]] = item
            LOG.debug("[%s] %d نتیجه خام، %d مورد قابل قبول", market, len(raw), kept)
        if request_delay:
            time.sleep(request_delay)

    ranked = sorted(found.values(), key=lambda x: (x.get("views") or 0), reverse=True)
    top = ranked[:limit]
    LOG.info(
        "[%s] %d کاندید یکتا؛ %d مورد انتخاب شد (پربازدیدترین: %s بازدید)",
        market,
        len(ranked),
        len(top),
        human_views(top[0]["views"]) if top else "-",
    )
    for idx, item in enumerate(top, 1):
        LOG.debug(
            "[%s] #%02d %s | %s | %s",
            market, idx, human_views(item["views"]), human_duration(item["duration"]), item["title"][:60],
        )
    return top
