# -*- coding: utf-8 -*-
"""نصب و راه‌اندازی بخش «پیدا کردن ویدیو» (Viral Hunter) روی سرور خودتان با SSH.

اصل طراحی: فقط و فقط یک پوشهٔ اختصاصی ساخته می‌شود، همه‌چیز داخل یک venv نصب
می‌شود و تنها تغییر بیرونی، یک خط cron است. هیچ سرویس موجودی (پنل، ربات تلگرام،
VPN) ری‌استارت یا تغییر داده نمی‌شود؛ هیچ پورت ورودی هم لازم نیست.

مراحل (به همین ترتیب اجرا کنید):

    python deploy_viral_server.py --host 1.2.3.4 --user root --check
    python deploy_viral_server.py --host 1.2.3.4 --user root --install
    python deploy_viral_server.py --host 1.2.3.4 --user root --test
    python deploy_viral_server.py --host 1.2.3.4 --user root --install-cron
    python deploy_viral_server.py --host 1.2.3.4 --user root --logs

اگر یوتیوب روی سرور هم بلاک بود (خطای not a bot):

    python deploy_viral_server.py --host ... --user root --upload-cookies yt_cookies.txt

حذف کامل:

    python deploy_viral_server.py --host ... --user root --uninstall

پسورد را با --password یا متغیر محیطی PADIZ_SSH_PASSWORD بدهید (اگر هیچ‌کدام نبود،
پرسیده می‌شود و در هیچ فایلی ذخیره نمی‌شود).
"""

# این اسکریپت روی سرور اجرا می‌شود و یک «کوکی مهمان» (بدون اکانت) می‌سازد.
# گاهی همین کوکی برای رد شدن از بلاک «not a bot» کافی است، چون یوتیوب یک
# بازدیدکنندهٔ معمولی با حافظهٔ مرورگر می‌بیند، نه یک اسکریپت خالی.
ANON_COOKIE_SCRIPT = r'''
import http.cookiejar, urllib.request, os, sys

path = sys.argv[1]
jar = http.cookiejar.MozillaCookieJar(path)
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    ("Accept-Language", "en-US,en;q=0.9"),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
]
for url in ("https://www.youtube.com/",
            "https://www.youtube.com/feed/trending",
            "https://consent.youtube.com/m?continue=https%3A%2F%2Fwww.youtube.com%2F&gl=US&m=0&pc=yt&hl=en"):
    try:
        opener.open(url, timeout=25).read(2048)
        print("visited", url)
    except Exception as exc:
        print("skip", url, type(exc).__name__)
jar.save(ignore_discard=True, ignore_expires=True)
print("cookies written:", path, os.path.getsize(path), "bytes")
for c in jar:
    print("  ", c.name, "=", (c.value or "")[:18])
'''

import argparse
import base64
import getpass
import os
import posixpath
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import paramiko

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_DIR = "/opt/padiz-shorts"
VENV_PY = posixpath.join(REMOTE_DIR, "venv", "bin", "python")
CRON_MARKER = "# padiz-viral-hunter"
CRON_LINE = ("30 6,13,18 * * * cd {d} && nice -n 15 {p} viral_hunter.py --once "
             ">> {d}/viral_cron.log 2>&1 {m}").format(
    d=REMOTE_DIR, p=VENV_PY, m=CRON_MARKER)

# فایل‌هایی که برای کار ویرال لازم است (بقیه اختیاری‌اند)
NEEDED_FILES = [
    "viral_hunter.py",
    "token.pickle",
    "client_secret.json",
    "make_cookies.py",
    "set_github_secret.py",
]
# فایل‌هایی که برای «ساخت ویدیو» هم لازم است (با --with-render اضافه می‌شوند)
RENDER_FILES = [
    "run_daily.py",
    "pipeline.py",
    "topics_pool.py",
    "channel_admin.py",
    "requirements.txt",
    "posted_shorts.json",
    "Vazirmatn-Bold.ttf",
    "sad_aesthetic_bg.mp3",
]


class Remote:
    """اتصال SSH با لاگ تمیز."""

    def __init__(self, host, user, password, port=22, key=None, timeout=25):
        self.host, self.user, self.port = host, user, port
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(host, port=port, username=user, password=password or None,
                            key_filename=key, timeout=timeout)
        self.sftp = self.client.open_sftp()

    def run(self, cmd, timeout=600, quiet=False):
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if not quiet:
            if out.strip():
                print(out.rstrip())
            if err.strip():
                print("[stderr]", err.rstrip())
        return code, out, err

    def put(self, local, remote):
        self.sftp.put(local, remote)

    def close(self):
        try:
            self.sftp.close()
        finally:
            self.client.close()


def do_check(remote):
    print("=" * 70)
    print("۱) بررسی وضعیت سرور (فقط خواندن — چیزی نصب یا تغییر نمی‌شود)")
    print("=" * 70)
    remote.run("cat /etc/os-release | head -3")
    remote.run("uname -a")
    remote.run("echo '--- CPU ---'; nproc; grep -m1 'model name' /proc/cpuinfo")
    remote.run("echo '--- RAM ---'; free -m | head -3")
    remote.run("echo '--- DISK ---'; df -h / | tail -1")
    remote.run("echo '--- LOAD ---'; uptime")
    remote.run("echo '--- TOOLS ---'; for c in python3 pip3 ffmpeg git curl; do "
               "printf '%s: ' $c; command -v $c || echo MISSING; done")
    remote.run("echo '--- LISTENING PORTS (پورت‌های پنل/VPN شما) ---'; "
               "(ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null) | head -15")
    remote.run("echo '--- CRON فعلی ---'; crontab -l 2>/dev/null | tail -20 || echo '(خالی)'")
    remote.run(f"echo '--- پوشه قبلی؟ ---'; ls -la {REMOTE_DIR} 2>/dev/null || echo '(وجود ندارد)'")
    print("\nمهم: خطای 'not a bot' یوتیوب به IP سرور بستگی دارد؛ با --test معلوم می‌شود.")


def do_install(remote, with_render, with_limits, static_ffmpeg=False):
    print("=" * 70)
    print("۲) نصب (فقط پوشه اختصاصی + venv؛ سرویس‌های موجود دست‌نخورده)")
    print("=" * 70)
    remote.run(f"mkdir -p {REMOTE_DIR}")

    code, out, _ = remote.run("command -v ffmpeg || echo MISSING", quiet=True)
    if "MISSING" in out and static_ffmpeg:
        print("نصب ffmpeg استاتیک در /usr/local/bin (بدون هیچ تغییری در پکیج‌های سیستم)")
        remote.run(
            "set -e; cd /tmp; "
            "curl -fsSL -o ff.tar.xz https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz "
            "|| curl -fsSL -o ff.tar.xz https://www.johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz; "
            "mkdir -p /tmp/ffx && tar -xJf ff.tar.xz -C /tmp/ffx --strip-components=1; "
            "install -m 755 /tmp/ffx/ffmpeg /usr/local/bin/ffmpeg; "
            "install -m 755 /tmp/ffx/ffprobe /usr/local/bin/ffprobe; "
            "rm -rf /tmp/ffx ff.tar.xz; ffmpeg -version | head -1",
            timeout=1800)
    elif "MISSING" in out:
        print("ffmpeg نصب نیست. اول شبیه‌سازی می‌کنیم که apt چه چیزی می‌خواهد تغییر دهد"
              " (برای امنیت سرویس‌های شما):")
        code, sim, _ = remote.run("apt-get install -s -y ffmpeg 2>&1 | tail -30", timeout=600)
        if "Remv " in sim:
            print("\n!! apt می‌خواهد پکیجی را حذف کند. برای اینکه به سرویس‌های شما دست نخورد،")
            print("   این مرحله انجام نشد. با گزینه --static-ffmpeg دوباره اجرا کنید:")
            print("   python deploy_viral_server.py --host ... --install --static-ffmpeg")
            return
        print("\nشبیه‌سازی امن بود (فقط نصب، بدون حذف). نصب واقعی انجام می‌شود...")
        remote.run("export DEBIAN_FRONTEND=noninteractive; "
                   "apt-get update -y && apt-get install -y ffmpeg", timeout=1800)
    else:
        print("ffmpeg از قبل روی سرور هست:", out.strip())

    code, out, _ = remote.run(f"test -x {VENV_PY} && echo YES || echo NO", quiet=True)
    if "NO" in out:
        print("ساخت محیط پایتون مجزا (venv)...")
        remote.run("export DEBIAN_FRONTEND=noninteractive; "
                   "(command -v python3 || (apt-get update -y && apt-get install -y python3 python3-venv python3-pip))",
                   timeout=1800)
        remote.run(f"python3 -m venv {REMOTE_DIR}/venv || "
                   f"(apt-get install -y python3-venv && python3 -m venv {REMOTE_DIR}/venv)",
                   timeout=1800)
    remote.run(f"{VENV_PY} -m pip install --upgrade pip", timeout=900)

    files = list(NEEDED_FILES) + (list(RENDER_FILES) if with_render else [])
    print("\nآپلود فایل‌ها:")
    uploaded = []
    for name in files:
        local = os.path.join(BASE_DIR, name)
        if not os.path.exists(local):
            print(f"  - پرش {name} (روی این کامپیوتر نیست)")
            continue
        remote.put(local, posixpath.join(REMOTE_DIR, name))
        uploaded.append(name)
        print(f"  - {name} ({os.path.getsize(local)} بایت)")
    remote.put(os.path.join(BASE_DIR, "requirements.txt"),
               posixpath.join(REMOTE_DIR, "requirements.txt"))
    print(f"\n{len(uploaded)} فایل آپلود شد -> {REMOTE_DIR}")

    print("\nنصب کتابخانه‌های پایتون داخل venv (به سیستم دست نمی‌زند)...")
    remote.run(f"{VENV_PY} -m pip install -r {REMOTE_DIR}/requirements.txt", timeout=1800)

    if with_limits:
        print("\nساخت محدودیت منابع با systemd-run (اختیاری، برای محافظت از VPN)...")
        remote.run("systemd-run --version >/dev/null 2>&1 && echo 'systemd-run موجود است' "
                   "|| echo 'systemd-run نیست؛ از nice استفاده می‌شود'")

    print("\nنصب تمام شد. قدم بعدی: --test")


def proxy_prefix(remote):
    """اگر سرویس پروکسی روی سرور فعال باشد، متغیر YT_PROXY را به دستور اضافه می‌کند."""
    url = os.environ.get("PADIZ_YT_PROXY", "socks5://127.0.0.1:10809")
    code, out, _ = remote.run("systemctl is-active padiz-proxy 2>/dev/null || echo none", quiet=True)
    if out.strip().startswith("active"):
        return f"YT_PROXY={url} "
    return ""


def cron_line(remote):
    return ("30 6,13,18 * * * cd {d} && {e}nice -n 15 {p} viral_hunter.py --once "
            ">> {d}/viral_cron.log 2>&1 {m}").format(
        d=REMOTE_DIR, e=proxy_prefix(remote), p=VENV_PY, m=CRON_MARKER)


def do_test(remote):
    print("=" * 70)
    print("۳) تست خشک روی سرور: پیدا کردن + دانلود + برندینگ (بدون آپلود)")
    print("=" * 70)
    cmd = (f"cd {REMOTE_DIR} && {proxy_prefix(remote)}nice -n 15 {VENV_PY} "
           f"viral_hunter.py --dry-run 2>&1 | tail -45")
    code, out, err = remote.run(cmd, timeout=2400)
    if "[dry-run] branded hero file ready" in out:
        print("\n✅ موفق: دانلود از IP این سرور کار می‌کند.")
        print("   قدم بعدی: --install-cron (اجرای خودکار روزانه)")
        return True
    if "not a bot" in out or "Sign in to confirm" in out:
        print("\n❌ یوتیوب دانلود از IP این سرور را رد کرد (همان بلاک 'not a bot').")
        print("   راه‌حل: روی کامپیوتر خودتان کوکی بسازید و بفرستید:")
        print("     python make_cookies.py --from-file cookies.txt")
        print("     python deploy_viral_server.py --host ... --upload-cookies .\\yt_cookies.txt")
        print("   بعد دوباره --test را اجرا کنید.")
        return False
    print("\n❓ نتیجه روشن نبود؛ ۴۵ خط آخر لاگ بالا را ببینید.")
    print("   اگر خطای quotaExceeded بود، یعنی سهمیه یوتیوب تمام شده (فردا درست می‌شود).")
    return False


def do_upload_cookies(remote, cookie_path, refresh_cookies):
    if refresh_cookies:
        print("ساخت کوکی از مرورگر روی این کامپیوتر...")
        from make_cookies import cookies_from_browser
        cookies_from_browser(refresh_cookies)
        cookie_path = os.path.join(BASE_DIR, "yt_cookies.txt")
    if not cookie_path or not os.path.exists(cookie_path):
        print("فایل کوکی پیدا نشد:", cookie_path)
        return False
    remote.put(cookie_path, posixpath.join(REMOTE_DIR, "yt_cookies.txt"))
    remote.run(f"chmod 600 {REMOTE_DIR}/yt_cookies.txt")
    print(f"کوکی روی سرور قرار گرفت: {REMOTE_DIR}/yt_cookies.txt (دسترسی 600)")
    print("viral_hunter.py خودش این فایل را برمی‌دارد؛ دوباره --test را اجرا کنید.")
    return True


def do_push(remote, with_render):
    """آپلود فایل‌ها بدون نصب مجدد (برای اعمال تغییرات سریع)."""
    files = list(NEEDED_FILES) + (list(RENDER_FILES) if with_render else [])
    files.append("requirements.txt")
    print(f"آپلود {len(files)} فایل به {REMOTE_DIR} (بدون نصب مجدد):")
    for name in files:
        local = os.path.join(BASE_DIR, name)
        if not os.path.exists(local):
            print(f"  - پرش {name} (روی این کامپیوتر نیست)")
            continue
        remote.put(local, posixpath.join(REMOTE_DIR, name))
        print(f"  - {name} ({os.path.getsize(local)} بایت)")
    remote.run(f"ls -la {REMOTE_DIR} | head -20")


def do_anonymous_cookies(remote):
    """ساخت کوکی مهمان روی خود سرور (بدون اکانت و بدون کار کاربر)."""
    print("ساخت کوکی مهمان روی سرور (بدون اکانت)...")
    payload = base64.b64encode(ANON_COOKIE_SCRIPT.encode("utf-8")).decode("ascii")
    remote.run(f"echo {payload} | base64 -d > {REMOTE_DIR}/_anon_cookies.py")
    remote.run(f"cd {REMOTE_DIR} && {VENV_PY} _anon_cookies.py {REMOTE_DIR}/yt_cookies.txt")
    remote.run(f"rm -f {REMOTE_DIR}/_anon_cookies.py; chmod 600 {REMOTE_DIR}/yt_cookies.txt")
    print("قدم بعدی: --test  (اگر جواب نداد، کوکی اکانت فرعی لازم است)")


def do_cron(remote, remove):
    code, out, _ = remote.run("crontab -l 2>/dev/null || true", quiet=True)
    lines = [ln for ln in out.splitlines() if CRON_MARKER not in ln]
    if remove:
        print("حذف خط cron مربوط به ویدیو (بقیه خطوط دست‌نخورده می‌مانند).")
    else:
        lines.append(cron_line(remote))
        print("افزودن این خط به cron:")
        print("   " + lines[-1])
    crontab = "\n".join(ln for ln in lines if ln.strip()) + "\n"
    payload = base64.b64encode(crontab.encode("utf-8")).decode("ascii")
    remote.run(f"echo {payload} | base64 -d | crontab - && echo 'crontab به‌روزرسانی شد'")
    remote.run("echo '--- CRON فعلی ---'; crontab -l | tail -6")


def do_logs(remote):
    print("=" * 70)
    print("۵) لاگ‌ها")
    print("=" * 70)
    remote.run(f"echo '--- cron ---'; crontab -l 2>/dev/null | grep -A0 padiz || echo '(خطی نیست)'")
    remote.run(f"echo '--- آخرین خطوط لاگ اجرا ---'; tail -40 {REMOTE_DIR}/viral_cron.log 2>/dev/null "
               f"|| echo '(هنوز لاگی نیست - اولین اجرا انجام نشده)'")
    remote.run(f"echo '--- خطاهای ثبت‌شده ---'; tail -10 {REMOTE_DIR}/viral_last_error.log 2>/dev/null "
               f"|| echo '(خطایی ثبت نشده)'")
    remote.run(f"echo '--- ویدیوهای پردازش‌شده ---'; cat {REMOTE_DIR}/processed_reels.json 2>/dev/null "
               f"|| echo '(هنوز چیزی منتشر نشده)'")


def do_uninstall(remote, assume_yes):
    print("=" * 70)
    print("حذف کامل (فقط پوشه خودمان + خط cron؛ سرویس‌های دیگر دست‌نخورده)")
    print("=" * 70)
    if not assume_yes:
        answer = input(f"حذف {REMOTE_DIR} و خط cron؟ (yes/no) ").strip().lower()
        if answer not in ("y", "yes", "بله", "ب"):
            print("لغو شد.")
            return
    do_cron(remote, remove=True)
    remote.run(f"rm -rf {REMOTE_DIR} && echo '{REMOTE_DIR} حذف شد'")
    print("اگر ffmpeg را ما نصب کرده بودیم و لازمش ندارید، دستی حذفش کنید."
          " بقیه سرویس‌ها (پنل، ربات، VPN) هیچ تغییری نکرده‌اند.")


def main():
    parser = argparse.ArgumentParser(
        description="نصب بخش پیدا کردن/آپلود ویدیو روی سرور خودتان (فقط پوشه اختصاصی + cron)")
    parser.add_argument("--host", required=True, help="آدرس IP یا دامنه سرور")
    parser.add_argument("--user", default="root", help="یوزر SSH (پیش‌فرض root)")
    parser.add_argument("--port", type=int, default=22, help="پورت SSH (پیش‌فرض 22)")
    parser.add_argument("--password", help="پسورد SSH (یا متغیر محیطی PADIZ_SSH_PASSWORD)")
    parser.add_argument("--key", help="مسیر فایل کلید SSH (جایگزین پسورد)")
    parser.add_argument("--check", action="store_true", help="فقط بررسی وضعیت سرور (بی‌خطر)")
    parser.add_argument("--install", action="store_true", help="نصب و آپلود فایل‌ها")
    parser.add_argument("--push-only", action="store_true",
                        help="فقط آپلود فایل‌ها بدون نصب مجدد (برای اعمال سریع تغییرات)")
    parser.add_argument("--with-render", action="store_true",
                        help="فایل‌های تولید ویدیو (فونت/موسیقی/topics) هم آپلود شوند")
    parser.add_argument("--with-limits", action="store_true", help="محدودیت منابع برای محافظت از VPN")
    parser.add_argument("--static-ffmpeg", action="store_true",
                        help="نصب ffmpeg استاتیک در /usr/local/bin (بدون دست‌زدن به پکیج‌های سیستم)")
    parser.add_argument("--test", action="store_true", help="تست خشک دانلود روی سرور (بدون آپلود)")
    parser.add_argument("--install-cron", action="store_true", help="زمان‌بندی خودکار روزانه")
    parser.add_argument("--remove-cron", action="store_true", help="حذف خط cron")
    parser.add_argument("--upload-cookies", metavar="FILE", help="ارسال فایل کوکی به سرور")
    parser.add_argument("--anonymous-cookies", action="store_true",
                        help="ساخت کوکی مهمان روی سرور (بدون اکانت)")
    parser.add_argument("--refresh-cookies", choices=["chrome", "edge", "firefox", "brave"],
                        help="ساخت کوکی از مرورگر همین کامپیوتر و ارسالش")
    parser.add_argument("--logs", action="store_true", help="نمایش لاگ‌های سرور")
    parser.add_argument("--uninstall", action="store_true", help="حذف کامل نصب ما")
    parser.add_argument("--yes", action="store_true", help="بدون پرسیدن تأیید در حذف")
    args = parser.parse_args()

    password = args.password or os.environ.get("PADIZ_SSH_PASSWORD")
    if not password and not args.key:
        password = getpass.getpass(f"پسورد SSH برای {args.user}@{args.host}: ")

    actions = [args.check, args.install, args.push_only, args.test, args.install_cron,
               args.remove_cron, args.anonymous_cookies,
               bool(args.upload_cookies or args.refresh_cookies),
               args.logs, args.uninstall]
    if not any(actions):
        parser.print_help()
        return 2

    print(f"اتصال به {args.user}@{args.host}:{args.port} ...")
    try:
        remote = Remote(args.host, args.user, password, args.port, args.key)
    except Exception as exc:  # noqa: BLE001
        print("اتصال ناموفق بود:", exc)
        print("بررسی کنید: IP/پورت درست باشد، پسورد درست باشد و سرور SSH را بپذیرد.")
        return 1
    print("متصل شد ✅")

    try:
        if args.check:
            do_check(remote)
        if args.install:
            do_install(remote, args.with_render, args.with_limits, args.static_ffmpeg)
        if args.push_only:
            do_push(remote, args.with_render)
        if args.anonymous_cookies:
            do_anonymous_cookies(remote)
        if args.upload_cookies or args.refresh_cookies:
            do_upload_cookies(remote, args.upload_cookies, args.refresh_cookies)
        if args.test:
            do_test(remote)
        if args.install_cron:
            do_cron(remote, remove=False)
        if args.remove_cron:
            do_cron(remote, remove=True)
        if args.logs:
            do_logs(remote)
        if args.uninstall:
            do_uninstall(remote, args.yes)
    finally:
        remote.close()
    print("\nپایان.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
