# -*- coding: utf-8 -*-
"""ساخت فایل کوکی یوتیوب برای عبور از خطای «Sign in to confirm you're not a bot».

چرا لازم است؟
    یوتیوب دانلود با yt-dlp از IPهای دیتاسنتر (سرور GitHub Actions، اکثر VPSها)
    را با پیام «Sign in to confirm you're not a bot» رد می‌کند. اگر کوکی یک اکانت
    (ترجیحاً اکانت فرعی/بی‌ارزش) را در اختیار yt-dlp بگذاریم، این بلاک برداشته
    می‌شود. ویدیوهایی که با IP ایران/خانگی دانلود می‌شوند معمولاً این مشکل را
    ندارند؛ پس اگر اسکریپت را روی PC خودتان اجرا می‌کنید، همین فایل اختیاری است.

استفاده:
    python make_cookies.py --from-file cookies.txt     # فایل خروجی افزونه مرورگر
    python make_cookies.py --browser chrome            # خواندن مستقیم از مرورگر
    python make_cookies.py --from-file cookies.txt --pat <GITHUB_PAT>   # ثبت خودکار سکرت

خروجی:
    yt_cookies.txt        فایل کوکی در کنار اسکریپت (viral_hunter.py خودش برمی‌دارد)
    yt_cookies_b64.txt    همان محتوا به‌صورت base64 برای سکرت GitHub

روش دستی ثبت سکرت: GitHub -> repo -> Settings -> Secrets and variables ->
Actions -> New repository secret -> Name: YT_COOKIES_B64
"""

import argparse
import base64
import os
import sys

import yt_dlp

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_PATH = os.path.join(BASE_DIR, "yt_cookies.txt")
B64_PATH = os.path.join(BASE_DIR, "yt_cookies_b64.txt")
SAMPLE_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def cookies_from_browser(browser):
    """خواندن کوکی‌های مرورگر با همان کدی که yt-dlp استفاده می‌کند."""
    from yt_dlp.cookies import extract_cookies_from_browser

    jar = extract_cookies_from_browser(browser)
    jar.save(COOKIE_PATH, ignore_discard=True, ignore_expires=True)
    return COOKIE_PATH


def verify(path):
    """فقط متادیتا می‌گیرد (دانلودی انجام نمی‌شود) تا معتبر بودن کوکی را ثابت کند."""
    opts = {"quiet": True, "no_warnings": True, "cookiefile": path,
            "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(SAMPLE_VIDEO, download=False)
        print("  PASS  کوکی‌ها پذیرفته شدند (نمونه:", info.get("title"), ")")
        return True
    except Exception as exc:  # noqa: BLE001
        print("  FAIL  yt-dlp کوکی را قبول نکرد:", str(exc)[:250])
        return False



def publish_secret(base64_value, pat):
    """ثبت سکرت با همان کد رمزگذاری set_github_secret.py (بدون تکرار کد)."""
    import urllib.error

    from set_github_secret import OWNER, REPO, encrypt_secret, github_request

    try:
        _, key_info = github_request(
            f"https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/public-key", pat
        )
    except urllib.error.HTTPError as e:
        print(f"دریافت کلید عمومی مخزن ناموفق بود (HTTP {e.code}).")
        print("توکن باید دسترسی Secrets: read and write داشته باشد.")
        return False

    try:
        status, _ = github_request(
            f"https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/YT_COOKIES_B64",
            pat,
            method="PUT",
            payload={
                "encrypted_value": encrypt_secret(key_info["key"], base64_value),
                "key_id": key_info["key_id"],
            },
        )
    except urllib.error.HTTPError as e:
        print(f"ثبت سکرت ناموفق بود (HTTP {e.code}).")
        return False

    if status in (201, 204):
        print(f"سکرت YT_COOKIES_B64 در {OWNER}/{REPO} ثبت شد.")
        return True
    print(f"پاسخ غیرمنتظره از GitHub: HTTP {status}")
    return False


def main():
    parser = argparse.ArgumentParser(description="ساخت yt_cookies.txt برای yt-dlp")
    parser.add_argument("--from-file", help="فایل cookies.txt خروجی افزونه مرورگر")
    parser.add_argument("--browser", choices=["chrome", "edge", "firefox", "brave", "opera"],
                        help="خواندن مستقیم کوکی از مرورگر (مرورگر باید بسته باشد)")
    parser.add_argument("--pat", help="توکن گیت‌هاب برای ثبت خودکار سکرت YT_COOKIES_B64")
    parser.add_argument("--no-verify", action="store_true", help="بدون تست کردن کوکی‌ها")
    args = parser.parse_args()

    if not args.from_file and not args.browser:
        parser.print_help()
        return 2

    if args.from_file:
        if not os.path.exists(args.from_file):
            print("فایل پیدا نشد:", args.from_file)
            return 2
        with open(args.from_file, "rb") as src, open(COOKIE_PATH, "wb") as dst:
            dst.write(src.read())
        print("کوکی‌ها کپی شدند ->", COOKIE_PATH)
    else:
        try:
            cookies_from_browser(args.browser)
            print(f"کوکی‌های {args.browser} خوانده شد -> {COOKIE_PATH}")
        except Exception as exc:  # noqa: BLE001
            print("خواندن کوکی از مرورگر ناموفق بود:", str(exc)[:250])
            print("راه ساده‌تر: افزونه «Get cookies.txt LOCALLY» را نصب کنید،")
            print("در حالت Incognito وارد youtube.com شوید، فایل را ذخیره کنید و")
            print("اسکریپت را با --from-file اجرا کنید.")
            return 1

    text = open(COOKIE_PATH, "r", encoding="utf-8", errors="replace").read()
    yt_count = sum(1 for line in text.splitlines()
                   if "youtube.com" in line and not line.startswith("#"))
    print(f"تعداد کوکی‌های یوتیوب در فایل: {yt_count}")
    if yt_count == 0:
        print("هشدار: هیچ کوکی youtube.com در فایل نیست؛ قبل از ساخت فایل وارد")
        print("youtube.com شوید و یک‌بار صفحه را باز کنید.")

    if not args.no_verify:
        verify(COOKIE_PATH)
        print("نکته: تست بالا فقط معتبر بودن کوکی را نشان می‌دهد؛ برداشته شدن بلاک")
        print("IP فقط روی همان سروری مشخص می‌شود که بلاک شده است.")

    b64 = base64.b64encode(open(COOKIE_PATH, "rb").read()).decode("ascii")
    with open(B64_PATH, "w", encoding="ascii") as fh:
        fh.write(b64)
    print(f"\nمقدار base64 در {B64_PATH} ذخیره شد ({len(b64)} کاراکتر).")
    print("روش دستی: GitHub -> Settings -> Secrets and variables -> Actions ->")
    print("New repository secret -> Name: YT_COOKIES_B64 -> محتوای فایل بالا.")
    print("روش خودکار: python make_cookies.py --from-file cookies.txt --pat <PAT>")

    if args.pat:
        publish_secret(b64, args.pat)
    return 0


if __name__ == "__main__":
    sys.exit(main())

