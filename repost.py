# -*- coding: utf-8 -*-
"""Repost pipeline — پل بین پروژه‌ی دانلودر (shortsdl) و آپلودر کانال.

MERGED PROJECT (2026-10-20)
---------------------------
پروژه‌ی `C:\\Users\\Allah\\Desktop\\yyy` (کشف + دانلود Shorts) داخل همین ریپو
ادغام شد تا همه‌ی کارها روی سرور و با یک کرون انجام شود. این فایل حلقه‌ی
گمشده است: ویدیوهایی که shortsdl پیدا و دانلود می‌کند را با همان توکن OAuth
و همان بودجه‌ی واحدی که بقیه‌ی ریپو استفاده می‌کند روی کانال منتشر می‌کند.

قواعد مهمی که رعایت می‌شود (همه از باگ‌های واقعی همین ریپو آمده‌اند):
  * سقف روزانه: حداکثر `per_day` آپلود ریپاست (پیش‌فرض ۲) — بیشتر از این
    باعث `uploadLimitExceeded` روی کانال جوان می‌شود.
  * بودجه‌ی API: هر آپلود ۱۶۰۰ واحد از ۱۰۰۰۰ واحد روز را می‌خورد. قبل از
    هر آپلود از yt_budget اجازه گرفته می‌شود؛ اگر واحد نماند، متوقف می‌شویم
    نه اینکه نیمه‌کاره بمانیم.
  * تکرار نشدن: هر شناسه در `repost_posted.json` ثبت می‌شود و دیگر هرگز
    آپلود نمی‌شود (چه فایل پاک شده باشد چه نه).
  * توکن مرده: قبل از دانلود (که وقت و پهنای باند می‌برد) چک می‌شود.
  * دیسک: بعد از آپلود موفق، فایل‌های ویدیو پاک می‌شوند (دستور مالک:
    هیچ آرشیوی روی سرور نماند).

Usage
-----
    python repost.py                      # ۲ ویدیو: کشف، دانلود، آپلود
    python repost.py --count 1            # فقط یکی
    python repost.py --dry-run            # فقط لیست کاندیداها، بدون دانلود
    python repost.py --no-upload          # دانلود کن ولی آپلود نکن (تست)
    python repost.py --markets persian    # از بازار فارسی
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from shortsdl import indexer  # noqa: E402
from shortsdl.config import load_config, resolve_path  # noqa: E402
from shortsdl.discover import discover_market  # noqa: E402
from shortsdl.downloader import Downloader  # noqa: E402
from shortsdl.utils import read_json, setup_logging, write_json  # noqa: E402

import curate  # noqa: E402   (فیلتر و امتیازدهی محتوا)
import media_check  # noqa: E402  (اعتبارسنجی فایل قبل از آپلود)
import transform  # noqa: E402  (تبدیل به ویدیوی تازه: روایت + تدوین)
import watermark  # noqa: E402  (مهر زدن آدرس کانال روی ویدیو)

# Child of the "shortsdl" logger on purpose: utils.setup_logging() configures
# "shortsdl" and its children, so a bare logging.getLogger("repost") would write
# to a logger with no handler and every message here would vanish from the log.
LOG = logging.getLogger("shortsdl.repost")

STATE_PATH = BASE_DIR / "repost_posted.json"
DEFAULT_PER_DAY = 2
TITLE_MAX = 100          # سقف یوتیوب
DESC_MAX = 5000


# --------------------------------------------------------------------------- #
# حالت (state)
# --------------------------------------------------------------------------- #
def load_state() -> list[dict]:
    data = read_json(STATE_PATH, default=[])
    return data if isinstance(data, list) else []


def save_state(records: list[dict]) -> None:
    write_json(STATE_PATH, records)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def posted_ids(records: list[dict]) -> set[str]:
    return {str(r.get("id")) for r in records if r.get("id")}


def count_today(records: list[dict]) -> int:
    """چند ریپاست امروز واقعاً «زنده» منتشر شد.

    رکوردهایی که `health == "dead"` دارند شمرده نمی‌شوند: یوتیوب فایل را
    نپذیرفته و ویدیو هرگز قابل پخش نشده. اگر این‌ها را بشماریم، یک آپلود
    خراب سهمیه‌ی روز را می‌سوزاند و روز بعد هم چیزی منتشر نمی‌شود —
    همان چیزی که ۲۰۲۶-۱۰-۲۱ اتفاق افتاد.
    """
    today = _today_utc()
    return sum(
        1 for r in records
        if str(r.get("posted_at", ""))[:10] == today
        and r.get("health") != "dead"
    )


def record_upload(video_id: str, item: dict, url: str, market: str) -> None:
    records = load_state()
    records.append({
        "id": video_id,
        "url": url,
        "market": market,
        "source_url": item.get("url", ""),
        "source_channel": item.get("channel", ""),
        "title": item.get("title", ""),
        "views": item.get("views") or 0,
        "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # pending → با `python upload_status.py --audit` به live/dead تبدیل
        # می‌شود. تا وقتی pending است جزو سهمیه حساب می‌شود (محافظه‌کارانه).
        "health": "pending",
    })
    save_state(records)


# --------------------------------------------------------------------------- #
# متادیتای آپلود
# --------------------------------------------------------------------------- #
_HASHTAG_RE = re.compile(r"#[\w\u0600-\u06FF]+")


def _clean_title(text: str) -> str:
    text = re.sub(r"[\r\n\t]+", " ", str(text or "")).strip()
    text = re.sub(r"\s{2,}", " ", text)
    return text


def build_meta(item: dict, rcfg: dict) -> tuple[str, str, list[str]]:
    """عنوان/توضیحات/تگ‌ها را از آیتم منبع می‌سازد.

    اعتباردهی به کانال اصلی عمدی است: هم اخلاقی است، هم ریسک شکایت/استرایک
    کپی‌رایت را کم می‌کند.
    """
    title = _clean_title(item.get("title")) or "ویدیو کوتاه"
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1].rstrip() + "…"

    channel = (item.get("channel") or "").strip()
    source = item.get("url") or f"https://www.youtube.com/shorts/{item.get('id', '')}"

    tags: list[str] = []
    for t in (rcfg.get("tags") or []):
        if t and t not in tags:
            tags.append(str(t))
    # هشتگ‌های خود عنوان هم به تگ‌ها اضافه شوند
    for h in _HASHTAG_RE.findall(title):
        tag = h.lstrip("#")
        if tag and tag not in tags:
            tags.append(tag)
    if "shorts" not in [t.lower() for t in tags]:
        tags.insert(0, "shorts")

    desc_tpl = rcfg.get("description_template") or (
        "{title}\n\n"
        "🎬 ویدیو از کانال اصلی: {channel}\n"
        "🔗 منبع: {source}\n\n"
        "برای ویدیوهای بیشتر سابسکرایب کنید.\n"
        "{hashtags}"
    )
    hashtags = " ".join(f"#{t}" for t in (rcfg.get("hashtags") or ["shorts", "viral"]))
    description = desc_tpl.format(
        title=title, channel=channel or "-", source=source, hashtags=hashtags
    )
    return title, description[:DESC_MAX], tags[:30]


# --------------------------------------------------------------------------- #
# کشف + دانلود
# --------------------------------------------------------------------------- #
def collect_candidates(markets: list[str], cfg: dict, skip: set[str], need: int) -> list[tuple[str, list[dict]]]:
    """برای هر بازار، کاندیداهای تازه (بدون تکرار) را برمی‌گرداند."""
    filters = cfg.get("filters", {})
    dcfg = cfg.get("discovery", {})
    dcfg_dl = cfg.get("download", {})
    per_query = int(dcfg.get("results_per_query", 25))
    # استخر بزرگ‌تر از تعداد موردنیاز: چون افقی/کم‌کیفیت/بی‌ربط‌ها رد می‌شوند و
    # باید جایگزین در دست باشد. کشف هزینه‌ی API ندارد (yt-dlp جست‌وجو می‌کند)،
    # پس ۲۰ کاندید گرفتن ارزان است.
    overfetch = max(int(dcfg.get("overfetch", 3) or 1), 10)
    limit = max(need * overfetch, need, 40)

    out: list[tuple[str, list[dict]]] = []
    for market in markets:
        mcfg = cfg["markets"].get(market)
        if not mcfg:
            LOG.error("بازار ناشناس: %s (موجود: %s)", market, ", ".join(cfg["markets"]))
            continue
        LOG.info("—" * 26)
        LOG.info("کشف بازار: %s", mcfg.get("label", market))
        items = discover_market(
            market,
            mcfg,
            filters,
            limit,
            results_per_query=per_query,
            request_delay=float(dcfg.get("request_delay", 0.3)),
            proxy=dcfg_dl.get("proxy"),
            cookies=dcfg_dl.get("cookies_file"),
            search_workers=int(dcfg.get("search_workers", 4)),
        )
        fresh = [it for it in items if str(it.get("id")) not in skip]
        # فیلتر ارزان روی عنوان/کانال، قبل از گرفتن متادیتا
        fresh = curate.prefilter(fresh, cfg.get("content", {}) or {})
        LOG.info("[%s] %d کاندید، %d مورد تازه و قابل بررسی (بقیه رد یا قبلاً منتشر شده)",
                 market, len(items), len(fresh))
        if fresh:
            out.append((market, fresh))
    return out


def _find_orphan_watermarked(folder: Path, video_id: str) -> Path | None:
    """نسخه‌ی تبدیل/مهرخورده‌ای که از اجرای قبلی جا مانده را پیدا می‌کند.

    سناریوی واقعی: پروسه بین «مهر زدن» و «آپلود» کشته شود (یا سرور ری‌استارت
    شود). فایل اصلی پاک شده، `<id>_wm.mp4` یا `<id>_tr.mp4` مانده و شناسه در
    آرشیو yt-dlp ثبت است. آن‌وقت `_find_existing` فایل اصلی را پیدا نمی‌کند و
    آرشیو هم اجازه‌ی دانلود دوباره نمی‌دهد → آن روز هیچ ریپاستی منتشر نمی‌شد.
    با این تابع، فایل آماده دوباره استفاده می‌شود.
    """
    for p in folder.glob(f"*_{video_id}_*.*"):
        if p.suffix.lower() in (".mp4", ".webm", ".mkv") and p.stat().st_size > 1024:
            return p
    return None


def download_item(item: dict, market: str, cfg: dict, outdir: Path,
                  dl_cache: dict) -> dict | None:
    """یک کاندید را دانلود می‌کند و نتیجه را برمی‌گرداند (None = نشد).

    فیلتر اصلی محتوا (افقی/کیفیت/قدمت/کلمات بلاک‌شده) قبلاً روی متادیتا انجام
    شده است؛ اینجا فقط یک بازبینی نهایی روی فایل واقعی انجام می‌شود، چون
    متادیتای یوتیوب گاهی رزولوشنی بالاتر از فرمت‌های واقعی اعلام می‌کند.
    """
    folder = outdir / market
    folder.mkdir(parents=True, exist_ok=True)
    vid = str(item.get("id"))

    orphan = _find_orphan_watermarked(folder, vid)
    if orphan:
        LOG.info("نسخه‌ی مهرخورده‌ی قبلی استفاده شد: %s", orphan.name)
        return {"id": vid, "rank": 1, "item": item, "file": str(orphan),
                "size": orphan.stat().st_size, "error": None, "skipped": True}

    dl = dl_cache.get(market)
    if dl is None:
        dcfg = cfg.get("download", {})
        dl = Downloader(
            dcfg,
            archive_path=outdir / ".download_archive.txt",
            proxy=dcfg.get("proxy"),
            cookies=dcfg.get("cookies_file"),
        )
        dl_cache[market] = dl

    results = dl.download_all([item], folder, workers=1, sleep_between=0, target=1)
    res = next((r for r in results if r.get("file")), None)
    if not res:
        return None

    w, h = watermark.probe_size(res["file"])
    min_res = int(
        (cfg.get("content", {}) or {}).get("min_res")
        or (cfg.get("filters", {}) or {}).get("min_height")
        or 720
    )
    if h <= w or min(w, h) < min_res:
        LOG.info("رد شد (ابعاد فایل %dx%d): %s", w, h, vid)
        unarchive(outdir / ".download_archive.txt", vid)
        cleanup_file(res["file"])
        return None
    return res


# --------------------------------------------------------------------------- #
# آپلود
# --------------------------------------------------------------------------- #
def verify_token() -> tuple[bool, str]:
    """توکن OAuth را قبل از خرج کردن وقت/پهنای باند چک می‌کند.

    Returns: (ok, channel_name_or_error)
    """
    try:
        import token_health
        ok, channel, err = token_health.check()
        return (True, channel) if ok else (False, err)
    except Exception as exc:  # noqa: BLE001
        return False, f"token check unavailable: {exc}"


def upload_one(file_path: str, item: dict, rcfg: dict) -> str | None:
    """یک ویدیو را آپلود می‌کند و URL نهایی را برمی‌گرداند (None = شکست)."""
    import pipeline

    title, description, tags = build_meta(item, rcfg)
    privacy = rcfg.get("privacy_status") or "public"
    category = str(rcfg.get("category_id") or "24")
    LOG.info("آپلود: %s", title[:70])
    LOG.info("  فایل: %s", Path(file_path).name)
    try:
        return pipeline.upload_to_youtube(
            video_path=file_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy,
            category_id=category,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.error("آپلود ناموفق (%s): %s", item.get("id"), str(exc)[:200])
        return None


def cleanup_file(file_path: str) -> None:
    """فایل ویدیو و فایل‌های جانبی‌اش را پاک می‌کند (بدون آرشیو روی سرور)."""
    p = Path(file_path)
    stem_prefix = p.name.split("_", 1)[-1].rsplit(".", 1)[0]  # 01_<id> -> <id>
    # نسخه‌ی مهرخورده «<id>_wm» نام دارد؛ همان شناسه را هدف بگیر تا فایل‌های
    # جانبی (webp/info.json) هم پاک شوند و چیزی روی سرور نماند.
    stem_prefix = re.sub(r"(_wm|_tr|-wm|_music)$", "", stem_prefix)
    for side in p.parent.glob(f"*{stem_prefix}*"):
        if side.is_file() and side.suffix.lower() in (".mp4", ".webm", ".mkv", ".m4a",
                                                      ".webp", ".jpg", ".json", ".part"):
            try:
                side.unlink()
            except OSError:
                pass


def unarchive(archive: Path, video_id: str) -> None:
    """شناسه را از آرشیو yt-dlp حذف می‌کند تا در اجرای بعد دوباره تلاش شود.

    بدون این کار، یک آپلودِ شکست‌خورده ویدیو را برای همیشه می‌سوزاند: فایلش پاک
    می‌شود، شناسه‌اش در `.download_archive.txt` می‌ماند و yt-dlp دیگر هرگز آن را
    دانلود نمی‌کند — یعنی ویدیو بی‌صدا از لیست حذف می‌شد.
    """
    try:
        if not archive.exists():
            return
        lines = archive.read_text(encoding="utf-8", errors="replace").splitlines()
        kept = [ln for ln in lines if not ln.strip().endswith(str(video_id))]
        if len(kept) != len(lines):
            archive.write_text("\n".join(kept) + "\n", encoding="utf-8")
            LOG.info("از آرشیو حذف شد تا دوباره تلاش شود: %s", video_id)
    except OSError as exc:
        LOG.warning("حذف از آرشیو ناموفق (%s): %s", video_id, exc)


# --------------------------------------------------------------------------- #
# اجرا
# --------------------------------------------------------------------------- #
def run(count: int, markets: list[str], dry_run: bool, no_upload: bool,
        force: bool, config_path: str | None = None) -> int:
    cfg = load_config(config_path)
    rcfg = cfg.get("repost", {}) or {}
    wm_cfg = cfg.get("watermark", {}) or {}
    tcfg = cfg.get("transform", {}) or {}
    outdir = resolve_path(cfg.get("output_dir") or "repost_out")
    setup_logging(outdir / "logs", verbose=bool(os.environ.get("REPOST_VERBOSE")))

    if not markets:
        markets = rcfg.get("markets") or ["trending", "global"]

    per_day = int(rcfg.get("per_day", DEFAULT_PER_DAY) or DEFAULT_PER_DAY)

    # پیش از شمارش سهمیه، سلامت آپلودهای قبلی بررسی می‌شود. ویدیویی که
    # یوتیوب فایلش را باز نکرده («آپلود مرده») نباید سهمیه‌ی امروز را
    # بخورد — همان اتفاقی که ۲۰۲۶-۱۰-۲۱ باعث شد هیچ ریپاستی منتشر نشود.
    if not dry_run and not no_upload:
        try:
            import upload_status
            upload_status.audit(upload_status.service())
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[audit] بررسی سلامت انجام نشد (%s)", str(exc)[:100])

    state = load_state()
    done_today = count_today(state)

    LOG.info("Repost | سقف امروز: %d/%d | خواسته‌شده: %d", done_today, per_day, count)

    if done_today >= per_day and not force:
        LOG.info("سقف روزانه‌ی ریپاست پر شده (%d/%d) — خروج امن.", done_today, per_day)
        return 0

    budget = per_day - done_today
    todo = min(count, budget)
    if todo <= 0:
        LOG.info("جایی برای آپلود امروز نمانده — خروج امن.")
        return 0

    # بودجه‌ی API: هر آپلود ۱۶۰۰ واحد. اگر واحد نماند، همان اول تسلیم می‌شویم.
    if not dry_run and not no_upload:
        try:
            import yt_budget as B
            affordable = B.uploads_affordable()
            LOG.info("[quota] %s", B.report())
            LOG.info("[quota] آپلود ممکن با بودجه‌ی باقی‌مانده: %d", affordable)
            if affordable < todo:
                LOG.warning("بودجه‌ی API فقط برای %d آپلود کافی است (خواسته: %d)", affordable, todo)
                todo = max(0, affordable)
            if todo == 0:
                LOG.error("بودجه‌ی API برای آپلود تمام شده — امروز ریپاست نمی‌کنیم.")
                return 0
        except Exception as exc:  # noqa: BLE001
            LOG.warning("بررسی بودجه ناموفق (%s) — با احتیاط ادامه می‌دهیم", exc)

    skip = posted_ids(state)

    if not dry_run and not no_upload:
        ok, channel = verify_token()
        if not ok:
            LOG.error("=" * 60)
            LOG.error("توکن یوتیوب مرده است: %s", channel)
            LOG.error("هیچ ویدیویی دانلود نشد، پس پهنای باند/بودجه هدر نرفت.")
            LOG.error("فیکس: python refresh_youtube_token.py  (راهنما: FIX_TOKEN_FA.md)")
            LOG.error("=" * 60)
            return 1
        LOG.info("[auth] توکن سالم است | کانال: %s", channel)

    candidates = collect_candidates(markets, cfg, skip, todo)
    if not candidates:
        LOG.warning("هیچ کاندیدای تازه‌ای پیدا نشد.")
        return 0

    # یک لیست تخت و بدون تکرار: یک ویدیو می‌تواند در دو بازار باشد و اگر
    # دوبار شمرده شود، ممکن است دوبار آپلود شود.
    flat, seen = [], set()
    for market, items in candidates:
        for it in items:
            vid = str(it.get("id"))
            if vid in seen:
                continue
            seen.add(vid)
            flat.append(dict(it, _market=market))
    LOG.info("[curate] %d کاندید یکتا از %d بازار", len(flat), len(candidates))

    # مرحله‌ی انتخاب: متادیتای کامل + فیلتر سخت + امتیاز «ترند بودن»
    content_cfg = cfg.get("content", {}) or {}
    if content_cfg.get("enabled", True):
        flat = curate.enrich(
            flat,
            workers=int(content_cfg.get("meta_workers", 4) or 4),
            timeout=int(content_cfg.get("meta_timeout", 25) or 25),
        )
        ranked = curate.rank(flat, content_cfg, want=max(todo * 3, 6))
    else:
        ranked = flat

    if not ranked:
        LOG.warning("بعد از فیلتر محتوا هیچ کاندیدای قابل‌انتشاری نماند.")
        return 0

    if dry_run:
        print(f"\n=== {len(ranked)} کاندید پذیرفته ===")
        for i, it in enumerate(ranked[:12], 1):
            print(f"{i:2d}. {it.get('score', 0):7.1f}  {it['id']}  "
                  f"{(it.get('title') or '')[:58]}")
        return 0

    uploaded = 0
    dl_cache: dict = {}
    per_market: dict[str, list[dict]] = {}

    for item in ranked:
        if uploaded >= todo:
            break
        market = item.get("_market") or markets[0]
        LOG.info("دانلود [%s] %s…", market, (item.get("title") or "")[:50])
        res = download_item(item, market, cfg, outdir, dl_cache)
        if not res:
            continue
        per_market.setdefault(market, []).append(res)

        if no_upload:
            LOG.info("[no-upload] آماده بود: %s (%s)", res["file"], item.get("id"))
            uploaded += 1
            continue

        # تبدیل به ویدیوی تازه — خواسته‌ی مالک برای امنیت درآمد: ریپاست خام
        # محتوای بازاستفاده‌شده است و صلاحیت درآمدزایی را از بین می‌برد.
        # transform خودش پلاک کانال را هم می‌نشاند، پس مسیر watermark جداگانه
        # اجرا نمی‌شود (وگرنه دو بار کدگذاری و دو مهر می‌خورد).
        if tcfg.get("enabled", True):
            made = transform.build(
                res["file"], item, tcfg,
                niche=item.get("niche") or item.get("query"),
            )
            if not made:
                LOG.error("تبدیل انجام نشد — این ویدیو آپلود نمی‌شود: %s",
                          item.get("id"))
                unarchive(outdir / ".download_archive.txt", str(item["id"]))
                cleanup_file(res["file"])
                continue
            res["file"] = made
            res["transformed"] = True
        elif wm_cfg.get("enabled", True):
            # مسیر قدیمی: فقط مهر زدن، بدون روایت/تدوین. فقط اگر transform
            # در کانفیگ خاموش شده باشد به اینجا می‌رسیم.
            marked = watermark.apply(res["file"], wm_cfg)
            if marked is None:
                LOG.error("مهر زدن شکست خورد (on_error=fail) — این ویدیو رد شد")
                cleanup_file(res["file"])
                continue
            res["file"] = marked

        # اعتبارسنجی نهایی: فایلی که یوتیوب نمی‌تواند باز کند نباید آپلود شود.
        # دو ویدیوی ۲۰۲۶-۱۰-۲۰ همین‌جا رد می‌شدند (container=None در سمت
        # یوتیوب، duration=P0D، ۹ ساعت گیر روی processing).
        chk = media_check.probe(res["file"])
        if not chk["ok"]:
            LOG.error("فایل سالم نیست — آپلود نمی‌شود: %s (%s)",
                      Path(res["file"]).name, chk["reason"])
            unarchive(outdir / ".download_archive.txt", str(item["id"]))
            cleanup_file(res["file"])
            continue
        LOG.info("  اعتبارسنجی: %s", chk["reason"])

        url = upload_one(res["file"], item, rcfg)
        if not url:
            # آپلود شکست خورد: فایل را نگه نمی‌داریم (دیسک) ولی شناسه را از
            # آرشیو درمی‌آوریم تا اجرای بعد دوباره شانس داشته باشد.
            unarchive(outdir / ".download_archive.txt", str(item["id"]))
            cleanup_file(res["file"])
            continue

        uploaded += 1
        record_upload(str(item["id"]), item, url, market)
        LOG.info("✅ منتشر شد: %s", url)
        if not rcfg.get("keep_files"):
            cleanup_file(res["file"])

    for market, results in per_market.items():
        folder = outdir / market
        rows = indexer.build_rows(market, [r["item"] for r in results], results)
        indexer.write_csv(folder / "index.csv", rows)
        indexer.write_json(folder / "index.json", rows)

    LOG.info("—" * 26)
    LOG.info("پایان ریپاست: %d از %d آپلود شد (امروز: %d/%d)",
             uploaded, todo, count_today(load_state()), per_day)
    return 0 if uploaded or no_upload or dry_run else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="repost",
        description="دانلود و انتشار خودکار Shorts پیدا‌شده توسط shortsdl روی کانال",
    )
    p.add_argument("--count", type=int, default=None,
                   help=f"تعداد ویدیو در این اجرا (پیش‌فرض: per_day از کانفیگ = {DEFAULT_PER_DAY})")
    p.add_argument("--markets", default=None,
                   help="بازارها با کاما: trending,global,persian (پیش‌فرض: از کانفیگ)")
    p.add_argument("--config", default=None, help="مسیر shortsdl_config.json")
    p.add_argument("--dry-run", action="store_true", help="فقط لیست کاندیداها")
    p.add_argument("--no-upload", action="store_true", help="دانلود کن ولی آپلود نکن")
    p.add_argument("--force", action="store_true", help="نادیده گرفتن سقف روزانه")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    rcfg = cfg.get("repost", {}) or {}

    count = args.count if args.count is not None else int(rcfg.get("per_day", DEFAULT_PER_DAY))
    markets = [m.strip() for m in (args.markets or "").split(",") if m.strip()]
    if not markets:
        markets = rcfg.get("markets") or ["trending", "global"]

    return run(
        count=max(1, count),
        markets=markets,
        dry_run=args.dry_run,
        no_upload=args.no_upload,
        force=args.force,
        config_path=args.config,
    )


if __name__ == "__main__":
    raise SystemExit(main())
