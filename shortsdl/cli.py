"""خط فرمان پروژه: کشف، دانلود و ساخت گزارش."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import indexer
from .config import PROJECT_ROOT, load_config, resolve_path
from .discover import discover_market
from .downloader import Downloader, renumber_files
from .utils import human_views, read_json, setup_logging, write_json

LOG = logging.getLogger("shortsdl")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shortsdl",
        description="دانلود پربازدیدترین YouTube Shorts (جهانی و فارسی)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""مثال‌ها:
  python run.py                          # هر دو بازار با تنظیمات config.json
  python run.py --limit 50               # ۵۰ شورت از هر بازار
  python run.py --markets persian        # فقط فارسی
  python run.py --dry-run                # فقط لیست پربازدیدها، بدون دانلود
""",
    )
    p.add_argument("--markets", default="all", help="global,persian یا all (پیش‌فرض: all)")
    p.add_argument("--limit", type=int, help="تعداد شورت هر بازار")
    p.add_argument("--outdir", help="پوشه‌ی خروجی (پیش‌فرض: output)")
    p.add_argument("--config", help="مسیر فایل config.json")
    p.add_argument("--max-height", type=int, help="حداکثر ارتفاع ویدیو (پیش‌فرض: 1080)")
    p.add_argument("--workers", type=int, help="تعداد دانلود هم‌زمان (پیش‌فرض: 3)")
    p.add_argument("--min-views", type=int, help="حداقل تعداد بازدید")
    p.add_argument("--max-duration", type=int, help="حداکثر مدت شورت به ثانیه")
    p.add_argument("--per-query", type=int, help="تعداد نتیجه‌ی هر جست‌وجو")
    p.add_argument("--proxy", help="پراکسی مثل http://127.0.0.1:8080")
    p.add_argument("--cookies", help="مسیر فایل cookies.txt (برای ویدیوهای محدود)")
    p.add_argument("--dry-run", action="store_true", help="فقط کشف و نمایش لیست، بدون دانلود")
    p.add_argument("--fast", action="store_true",
                   help="حالت سریع: کیفیت ۷۲۰p، دانلود موازی‌تر، جست‌وجوی سبک‌تر")
    p.add_argument("--refresh", action="store_true",
                   help="نادیده گرفتن کش کاندیداها و جست‌وجوی مجدد")
    p.add_argument("--verbose", "-v", action="store_true", help="لاگ کامل")
    return p


def _print_list(market_label: str, items: list[dict]) -> None:
    print(f"\n=== {market_label} — {len(items)} مورد ===")
    for i, it in enumerate(items, 1):
        print(f"{i:2d}. {human_views(it.get('views')):>7}  {it['id']}  {it['title'][:60]}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    cfg = load_config(args.config)
    outdir = resolve_path(args.outdir or cfg["output_dir"])
    setup_logging(outdir / "logs", verbose=args.verbose)

    # اعمال بازنویسی‌های خط فرمان روی تنظیمات
    if args.limit:
        cfg["per_market_limit"] = args.limit
    if args.max_height:
        cfg["download"]["max_height"] = args.max_height
    if args.workers:
        cfg["download"]["workers"] = args.workers
    if args.min_views is not None:
        cfg["filters"]["min_views"] = args.min_views
    if args.max_duration:
        cfg["filters"]["max_duration_sec"] = args.max_duration
    if args.per_query:
        cfg["discovery"]["results_per_query"] = args.per_query
    if args.proxy:
        cfg["download"]["proxy"] = args.proxy
    if args.cookies:
        cfg["download"]["cookies_file"] = args.cookies
    if args.fast:
        cfg["download"]["max_height"] = min(int(cfg["download"]["max_height"]), 720)
        cfg["download"]["workers"] = max(int(cfg["download"]["workers"]), 5)
        cfg["discovery"]["results_per_query"] = min(int(cfg["discovery"]["results_per_query"]), 15)

    markets_cfg = cfg["markets"]
    wanted = list(markets_cfg) if args.markets.strip().lower() == "all" else [
        m.strip() for m in args.markets.split(",") if m.strip()
    ]
    unknown = [m for m in wanted if m not in markets_cfg]
    if unknown:
        LOG.error("بازار ناشناس: %s (موجود: %s)", ", ".join(unknown), ", ".join(markets_cfg))
        return 2

    outdir.mkdir(parents=True, exist_ok=True)
    LOG.info("پوشه خروجی: %s", outdir)
    LOG.info("بازارها: %s | سقف هر بازار: %d", ", ".join(wanted), cfg["per_market_limit"])

    downloader = Downloader(
        cfg["download"],
        archive_path=outdir / ".download_archive.txt",
        proxy=args.proxy,
        cookies=args.cookies,
    )

    sections: list[tuple[str, str, list[dict]]] = []
    all_rows: list[dict] = []
    # چند برابر تعداد درخواستی کاندید جمع کنیم تا اگر بعضی ویدیوها در دسترس
    # نبودند، از پایین لیست جایگزین شوند و تعداد نهایی کامل شود.
    overfetch = int(cfg["discovery"].get("overfetch", 3) or 1)
    pool_size = max(cfg["per_market_limit"], cfg["per_market_limit"] * overfetch)

    try:
        for market in wanted:
            mcfg = markets_cfg[market]
            label = mcfg.get("label", market)
            LOG.info("—" * 30)
            LOG.info("بازار: %s", label)

            need = cfg["per_market_limit"] if args.dry_run else pool_size
            cache_file = outdir / market / "candidates.json"
            ttl_min = int(cfg["discovery"].get("cache_minutes", 30) or 0)
            cached = None if args.refresh else read_json(cache_file, default=None)
            fresh = cache_file.exists() and ttl_min > 0 and (
                time.time() - cache_file.stat().st_mtime) < ttl_min * 60
            if cached and fresh and len(cached) >= cfg["per_market_limit"]:
                items = cached[:need]
                LOG.info("[%s] استفاده از کش کاندیداها (%d مورد) — برای جست‌وجوی مجدد: --refresh",
                         market, len(items))
            else:
                items = discover_market(
                    market,
                    mcfg,
                    cfg["filters"],
                    need,
                    results_per_query=cfg["discovery"]["results_per_query"],
                    request_delay=cfg["discovery"]["request_delay"],
                    proxy=cfg["download"].get("proxy"),
                    cookies=cfg["download"].get("cookies_file"),
                    search_workers=int(cfg["discovery"].get("search_workers", 4)),
                )
                write_json(cache_file, items)

            if not items:
                LOG.warning("هیچ کاندیدایی برای %s پیدا نشد.", label)
                continue

            if args.dry_run:
                _print_list(label, items)
                continue

            results = downloader.download_all(
                items,
                outdir / market,
                workers=cfg["download"]["workers"],
                sleep_between=cfg["download"].get("sleep_between", 0),
                target=cfg["per_market_limit"],
            )

            ok_results = renumber_files(results)
            attempted = [r["item"] for r in ok_results]
            rows = indexer.build_rows(market, attempted, ok_results)
            indexer.write_csv(outdir / market / "index.csv", rows)
            indexer.write_json(outdir / market / "index.json", rows)
            sections.append((market, label, rows))
            all_rows.extend(rows)

    except KeyboardInterrupt:
        LOG.warning("متوقف شد توسط کاربر. فایل‌های دانلودشده حفظ می‌شوند.")
        return 130

    if all_rows:
        # بازارهایی که در این اجرا نبودند ولی خروجی قبلی دارند هم در گزارش بیایند
        seen = {m for m, _, _ in sections}
        for folder in sorted(outdir.iterdir()):
            if folder.is_dir() and folder.name not in seen and (folder / "index.json").exists():
                rows = read_json(folder / "index.json", default=[]) or []
                if rows:
                    label = (markets_cfg.get(folder.name) or {}).get("label", folder.name)
                    sections.append((folder.name, label, rows))
                    all_rows.extend(rows)

        indexer.write_csv(outdir / "all_shorts.csv", all_rows)
        indexer.write_json(outdir / "all_shorts.json", all_rows)
        indexer.write_report(outdir / "report.html", sections)
        ok = sum(1 for r in all_rows if r["status"] == "ok")
        LOG.info("—" * 30)
        LOG.info("تمام شد: %d از %d فایل دانلود شد.", ok, len(all_rows))
        LOG.info("گزارش: %s", outdir / "report.html")
        print(f"\nپوشه خروجی: {outdir}")
        print(f"گزارش HTML: {outdir / 'report.html'}")
        print(f"ایندکس اکسل‌خوان: {outdir / 'all_shorts.csv'}")
    elif args.dry_run:
        print("\nحالت آزمایشی: چیزی دانلود نشد.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
