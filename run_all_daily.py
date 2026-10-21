# -*- coding: utf-8 -*-
"""run_all_daily.py — تنها نقطه‌ی ورود روزانه‌ی پروژه‌ی ادغام‌شده.

قبل از ادغام، دو پروژه‌ی جدا بود:
  1) `youtube_pipeline` — تولید شورت فارسی + آپلود با توکن کانال
  2) `yyy` (shortsdl)   — کشف و دانلود Shorts پر‌بازدید

حالا هر دو در همین ریپو هستند و این فایل ترتیب درست اجرا را تضمین می‌کند:

    مرحله ۱ — ریپاست: ویدیوهای ترند پیدا/دانلود و تبدیل و منتشر می‌شوند
    مرحله ۲ — شورت فارسی: محتوای ساخته‌شده‌ی خودمان با سهمیه‌ی باقی‌مانده

**هر دو طرف سهم تضمین‌شده دارند.** `repost.per_day` سهم ریپاست را قطعی
می‌کند (پیش‌فرض ۲) و شورت‌های اصلی با آنچه از سقف روزانه باقی می‌ماند اجرا
می‌شوند. ترتیب اجرا با `daily.repost_first` کنترل می‌شود و فقط تعیین می‌کند
اگر وسط روز سهمیه تنگ شد، کدام مرحله کامل اجرا شده باشد.

سقف مشترک: MAX_UPLOADS_PER_DAY (پیش‌فرض ۵). هر آپلود ۱۶۰۰ واحد از ۱۰۰۰۰
واحد روزانه‌ی YouTube Data API را می‌خورد، پس ۵ آپلود = ۸۰۰۰ واحد و ۲۰۰۰
واحد برای بقیه‌ی کارها می‌ماند. ۶ آپلود = ۹۶۰۰ واحد که با یک retry تمام
بودجه را می‌سوزاند — عمداً یک پله پایین‌تر ایستاده‌ایم.

Usage
-----
    python run_all_daily.py                 # هر دو مرحله
    python run_all_daily.py --only repost   # فقط ریپاست
    python run_all_daily.py --only shorts   # فقط شورت فارسی
    python run_all_daily.py --dry-run       # بدون آپلود (تست)
    python run_all_daily.py --repost-count 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

MAX_UPLOADS_PER_DAY = int(os.environ.get("MAX_UPLOADS_PER_DAY", "5"))
SHORTS_FILE = BASE_DIR / "posted_shorts.json"
REPOST_FILE = BASE_DIR / "repost_posted.json"


def _max_uploads() -> int:
    """سقف روزانه: env > کانفیگ (`daily.max_uploads`) > پیش‌فرض ۵."""
    if os.environ.get("MAX_UPLOADS_PER_DAY"):
        return int(os.environ["MAX_UPLOADS_PER_DAY"])
    try:
        from shortsdl.config import load_config
        v = (load_config().get("daily") or {}).get("max_uploads")
        if v:
            return max(1, int(v))
    except Exception:
        pass
    return MAX_UPLOADS_PER_DAY


def _log(msg: str) -> None:
    print(msg, flush=True)


def _count_today(path: Path) -> int:
    """تعداد رکوردهای امروز (UTC) در یک فایل state."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(data, list):
        return 0
    return sum(1 for r in data if str((r or {}).get("posted_at", ""))[:10] == today)


def uploads_today() -> int:
    return _count_today(SHORTS_FILE) + _count_today(REPOST_FILE)


def _banner(title: str) -> None:
    _log("=" * 62)
    _log(f"  {title}")
    _log("=" * 62)


def step_repost(count: int, dry_run: bool) -> int:
    _banner(f"ریپاست تبدیل‌شده ({count} ویدیو)")
    try:
        import repost
    except Exception as exc:  # noqa: BLE001
        _log(f"[repost] import failed: {type(exc).__name__}: {exc}")
        return 1

    # بررسی سلامت آپلودهای قبلی داخل خود repost.run() انجام می‌شود
    # (upload_status.audit) تا حتی اجرای دستی هم سهمیه‌ی مرده نداشته باشد.
    try:
        return repost.run(
            count=count,
            markets=[],           # از کانفیگ خوانده می‌شود
            dry_run=dry_run,
            no_upload=False,
            force=False,
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"[repost] failed: {type(exc).__name__}: {exc}")
        return 1


def step_shorts(dry_run: bool) -> int:
    _banner("شورت فارسی (ساخت خودمان)")
    if dry_run:
        _log("[shorts] dry-run: run_daily.py اجرا نمی‌شود.")
        return 0
    try:
        import run_daily
    except Exception as exc:  # noqa: BLE001
        _log(f"[shorts] import failed: {type(exc).__name__}: {exc}")
        return 1
    try:
        run_daily.main()
        return 0
    except SystemExit as exc:          # run_daily روی خطای توکن exit می‌کند
        code = exc.code if isinstance(exc.code, int) else 1
        _log(f"[shorts] exited with {code}")
        return code
    except Exception as exc:  # noqa: BLE001
        _log(f"[shorts] failed: {type(exc).__name__}: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="run_all_daily",
        description="اجرای روزانه‌ی کامل: ریپاست + شورت فارسی",
    )
    p.add_argument("--only", choices=["all", "repost", "shorts"], default="all",
                   help="کدام مرحله اجرا شود (پیش‌فرض: all)")
    p.add_argument("--repost-count", type=int, default=None,
                   help="تعداد ویدیوی ریپاست در این اجرا (پیش‌فرض: per_day کانفیگ)")
    p.add_argument("--dry-run", action="store_true", help="بدون آپلود")
    args = p.parse_args(argv)

    _banner(f"اجرای روزانه — {datetime.now().astimezone():%Y-%m-%d %H:%M} "
            f"({os.name})")
    cap = _max_uploads()
    done = uploads_today()
    _log(f"[cap] آپلودهای امروز: {done}/{cap}")

    if done >= cap and not args.dry_run:
        _log(f"[cap] سقف آپلود روزانه پر شده ({done}/{cap}) — خروج امن.")
        return 0

    repost_count = args.repost_count
    repost_first = True
    if repost_count is None:
        try:
            from shortsdl.config import load_config
            cfg = load_config()
            repost_count = int((cfg.get("repost") or {}).get("per_day", 2))
            repost_first = bool((cfg.get("daily") or {}).get("repost_first", True))
        except Exception:
            repost_count = 2

    room = cap - done
    repost_count = min(repost_count, room) if not args.dry_run else repost_count
    _log(f"[plan] ترتیب: {'ریپاست اول' if repost_first else 'شورت اول'} | "
         f"ریپاست (تبدیل‌شده): {repost_count} | "
         f"شورت اصلی: {'بله' if args.only in ('all', 'shorts') else 'خیر'}")

    rc = 0

    def do_repost() -> int:
        """ریپاست با سهم تضمین‌شده‌ی خودش (per_day)."""
        if args.only not in ("all", "repost") or repost_count <= 0:
            return 0
        left = cap - uploads_today()
        if not args.dry_run and left <= 0:
            _log("[repost] سهمیه‌ای نمانده — رد شد.")
            return 0
        n = repost_count if args.dry_run else min(repost_count, left)
        return step_repost(n, args.dry_run)

    def do_shorts() -> int:
        """شورت ساخته‌ی خودمان با آنچه از سهمیه باقی مانده."""
        if args.only not in ("all", "shorts"):
            return 0
        if not args.dry_run and (cap - uploads_today()) <= 0:
            _log("[shorts] سهمیه‌ای برای شورت نمانده — رد شد.")
            return 0
        return step_shorts(args.dry_run)

    # ترتیب از کانفیگ می‌آید (`daily.repost_first`). پیش‌فرض: ریپاست اول،
    # چون ویدیوهای ترند بازدید می‌آورند و خواسته‌ی مالک این است که سهمشان
    # تضمین باشد — نه اینکه فقط وقتی جا ماند اجرا شوند.
    for step in ((do_repost, do_shorts) if repost_first
                 else (do_shorts, do_repost)):
        rc |= step()

    _banner(f"پایان — آپلودهای امروز: {uploads_today()}/{cap}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
