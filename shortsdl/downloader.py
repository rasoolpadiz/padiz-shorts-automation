"""دانلود موازی شورت‌ها با yt-dlp (با پشتیبانی از ادامه‌ی دانلود و آرشیو)."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yt_dlp

from .utils import ffmpeg_location, human_size, human_views

LOG = logging.getLogger("shortsdl.download")

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


def renumber_files(results: list[dict]) -> list[dict]:
    """فایل‌های موفق را به ترتیب بازدید از ۰۱ شماره‌گذاری مجدد می‌کند.

    ویدیوهایی که در دسترس نبودند حذف می‌شوند تا شماره‌ها پیوسته بمانند.
    """
    ok = sorted([r for r in results if r.get("file")], key=lambda r: r["rank"])
    for i, res in enumerate(ok, 1):
        path = Path(res["file"])
        vid = res["id"]
        for side in path.parent.glob(f"*_{vid}.*"):
            if "_" not in side.name:
                continue
            suffix = side.name.split("_", 1)[1]
            target = side.with_name(f"{i:02d}_{suffix}")
            if target != side:
                if target.exists():
                    target.unlink()
                side.rename(target)
        res["file"] = str(path.parent / f"{i:02d}_{path.name.split('_', 1)[1]}")
        res["rank"] = i
    return ok


def _find_existing(folder: Path, vid: str) -> Path | None:
    """اگر فایل این ویدیو قبلاً دانلود شده باشد، مسیرش را برمی‌گرداند."""
    for pattern in (f"*_{vid}.*", f"{vid}.*"):
        for p in folder.glob(pattern):
            if p.suffix.lower() in VIDEO_EXTS and p.stat().st_size > 1024:
                return p
    return None


class Downloader:
    """دانلودر با یک نمونه yt-dlp به ازای هر ترد."""

    def __init__(self, dl_cfg: dict, archive_path: Path, proxy: str | None = None,
                 cookies: str | None = None):
        self.cfg = dl_cfg or {}
        self.archive = Path(archive_path)
        self.proxy = proxy or self.cfg.get("proxy")
        self.cookies = cookies or self.cfg.get("cookies_file")
        self.ffmpeg = ffmpeg_location()
        self._local = threading.local()
        if not self.ffmpeg:
            LOG.warning("ffmpeg پیدا نشد؛ کیفیت‌های ترکیبی (مثل 1080p) ممکن است در دسترس نباشند.")

    # ------------------------------------------------------------------ #
    def _format_selector(self) -> str:
        """فرمت دانلود: بهترین کیفیت با سقفِ ضلع کوچک (نه ارتفاع).

        باگ واقعی: نسخه‌ی قبلی `[height<=1080]` داشت. برای ویدیوی عمودی که
        ارتفاعش ۱۹۲۰ است این شرط یعنی «فقط ۶۰۸x۱۰۸۰ را بگیر» — یک کلیپ
        ۱۰۸۰x۱۹۲۰ در دسترس بود ولی ۶۰۸ پیکسل عرض دانلود می‌شد. حالا سقف روی
        `res` (ضلع کوچک) اعمال می‌شود که برای افقی و عمودی هر دو درست است.
        """
        if self.ffmpeg:
            return "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b"
        return "b[ext=mp4]/b"

    def _format_sort(self) -> list[str]:
        r = int(self.cfg.get("max_res") or self.cfg.get("max_height") or 1080)
        return [f"res:{r}"]

    def _opts(self, folder: Path, rank: int) -> dict:
        opts = {
            "paths": {"home": str(folder)},
            "outtmpl": {"default": f"{rank:02d}_%(id)s.%(ext)s"},
            "format": self._format_selector(),
            "format_sort": self._format_sort(),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "ignoreerrors": False,
            "retries": int(self.cfg.get("retries") or 3),
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 4,
            "socket_timeout": 30,
            "download_archive": str(self.archive),
            "windowsfilenames": True,
            "writethumbnail": bool(self.cfg.get("write_thumbnail", True)),
            "writeinfojson": bool(self.cfg.get("write_info_json", True)),
        }
        if self.ffmpeg:
            opts["ffmpeg_location"] = self.ffmpeg
        # کلاینت‌های یوتیوب: اول web (کیفیت کامل ۱۰۸۰p)، اگر ویدیو در دسترس نبود
        # yt-dlp خودش android را هم امتحان می‌کند و فرمت‌ها ادغام می‌شوند.
        clients = self.cfg.get("player_clients") or ["default", "android"]
        opts["extractor_args"] = {"youtube": {"player_client": list(clients)}}
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.cookies:
            opts["cookiefile"] = self.cookies
        return opts

    def _ydl(self, folder: Path, rank: int) -> yt_dlp.YoutubeDL:
        # هر ترد نمونه‌ی خودش را می‌سازد (YoutubeDL ترد-امن نیست)
        ydl = getattr(self._local, "ydl", None)
        if ydl is None:
            ydl = yt_dlp.YoutubeDL(self._opts(folder, rank))
            self._local.ydl = ydl
        return ydl

    # ------------------------------------------------------------------ #
    def download_one(self, item: dict, rank: int, folder: Path) -> dict:
        vid = item["id"]
        result = {"id": vid, "rank": rank, "item": item, "file": None, "size": 0,
                  "error": None, "skipped": False}

        existing = _find_existing(folder, vid)
        if existing:
            result.update(file=str(existing), size=existing.stat().st_size, skipped=True)
            return result

        try:
            ydl = self._ydl(folder, rank)
            ydl.params["outtmpl"]["default"] = f"{rank:02d}_%(id)s.%(ext)s"
            ydl.extract_info(item["url"], download=True)
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc).splitlines()[0][:200]
            LOG.warning("#%02d دانلود نشد (%s): %s", rank, vid, result["error"])
            return result

        found = _find_existing(folder, vid)
        if found:
            result.update(file=str(found), size=found.stat().st_size)
        else:
            result["error"] = "فایل خروجی پیدا نشد"
        return result

    # ------------------------------------------------------------------ #
    def download_all(self, items: list[dict], folder: Path, workers: int = 3,
                     sleep_between: float = 0.0, target: int | None = None) -> list[dict]:
        """دانلود موازی؛ اگر target داده شود، پس از رسیدن به آن تعداد موفق متوقف می‌شود.

        این کار باعث می‌شود ویدیوهای حذف‌شده/محدودشده رد شوند و از لیست پایین‌تر
        جایگزین شوند تا در نهایت تعداد درخواستی کامل شود.
        """
        folder.mkdir(parents=True, exist_ok=True)
        results: list[dict] = []
        total = len(items)
        workers = max(1, min(int(workers or 1), 8))
        done = 0
        success = 0
        cursor = 0

        with ThreadPoolExecutor(max_workers=workers) as pool:
            while cursor < total and (target is None or success < target):
                size = workers if target is None else max(1, min(workers, target - success))
                chunk = list(enumerate(items[cursor:cursor + size], start=cursor + 1))
                cursor += len(chunk)
                futures = [pool.submit(self.download_one, it, rank, folder) for rank, it in chunk]
                if sleep_between:
                    time.sleep(sleep_between)
                for fut in as_completed(futures):
                    res = fut.result()
                    results.append(res)
                    done += 1
                    if res["file"]:
                        success += 1
                        state = "قبلاً موجود" if res["skipped"] else "دانلود شد"
                        LOG.info(
                            "[%d/%d] #%02d %s | %s | %s",
                            done, total, res["rank"],
                            human_views(res["item"].get("views")),
                            human_size(res["size"]), state,
                        )
                    else:
                        LOG.warning("[%d/%d] #%02d ناموفق — جایگزین می‌شود", done, total, res["rank"])

        results.sort(key=lambda r: r["rank"])
        ok = sum(1 for r in results if r["file"])
        LOG.info("خلاصه: %d فایل آماده شد (از %d تلاش) در %s", ok, len(results), folder)
        return results
