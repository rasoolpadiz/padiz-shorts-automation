#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اعتبارسنجی فایل ویدیو قبل از آپلود — جلوگیری از «آپلود مرده».

چرا لازم است
------------
دو ویدیویی که ۲۰۲۶-۱۰-۲۰ آپلود شدند و ۹ ساعت روی «processing» ماندند،
از دید یوتیوب این‌طور بودند:

    container = None   videoStreams = []   duration = P0D

یعنی یوتیوب بایت‌ها را گرفت ولی نتوانست فایل را باز کند. چنین آپلودی
سهمیه‌ی ۱۶۰۰ واحدی را می‌خورد، در تاریخچه ثبت می‌شود، ولی هرگز قابل پخش
نمی‌شود. این ماژول همان چیزی را که یوتیوب نمی‌تواند بخواند، قبل از آپلود
تشخیص می‌دهد.

    python media_check.py file.mp4
"""
import json
import os
import re
import subprocess
import sys

_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VID_RE = re.compile(r"Stream #\d+:\d+.*?: Video: ([A-Za-z0-9_]+).*?(\d{2,5})x(\d{2,5})")
_AUD_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: ([A-Za-z0-9_]+)")


def ffmpeg_path() -> str:
    """همان مسیریابی watermark.py — یک منبع حقیقت برای مسیر ffmpeg."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        import shutil
        return shutil.which("ffmpeg") or "ffmpeg"


def probe(path: str, timeout: int = 60) -> dict:
    """مشخصات فایل را برمی‌گرداند. `ok=False` یعنی «آپلود نکن».

    کلیدهای خروجی:
        ok, reason, duration, width, height, vcodec, acodec, size, has_audio
    """
    out = {"ok": False, "reason": "", "duration": 0.0, "width": 0, "height": 0,
           "vcodec": "", "acodec": "", "size": 0, "has_audio": False}
    if not path or not os.path.exists(path):
        out["reason"] = "فایل وجود ندارد"
        return out

    out["size"] = os.path.getsize(path)
    if out["size"] < 10_000:
        out["reason"] = "فایل خیلی کوچک است (%d بایت)" % out["size"]
        return out

    try:
        res = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-i", path],
            capture_output=True, text=True, errors="replace", timeout=timeout,
        )
        info = (res.stderr or "") + (res.stdout or "")
    except Exception as exc:  # noqa: BLE001
        out["reason"] = "ffmpeg اجرا نشد: %s" % str(exc)[:100]
        return out

    m = _DUR_RE.search(info)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        out["duration"] = h * 3600 + mi * 60 + s

    v = _VID_RE.search(info)
    if v:
        out["vcodec"] = v.group(1)
        out["width"] = int(v.group(2))
        out["height"] = int(v.group(3))

    a = _AUD_RE.search(info)
    if a:
        out["acodec"] = a.group(1)
        out["has_audio"] = True

    if not out["vcodec"] or out["width"] < 2 or out["height"] < 2:
        out["reason"] = "جریان ویدیویی قابل خواندن نیست"
        return out
    if out["duration"] < 3.0:
        out["reason"] = "مدت ویدیو خیلی کوتاه است (%.1f ثانیه)" % out["duration"]
        return out

    out["ok"] = True
    out["reason"] = "سالم (%.1fs، %dx%d، %s)" % (
        out["duration"], out["width"], out["height"], out["vcodec"])
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python media_check.py <file> [file...]")
        return 2
    bad = 0
    for p in argv:
        r = probe(p)
        mark = "OK  " if r["ok"] else "BAD "
        if not r["ok"]:
            bad += 1
        print("%s %s\n     %s" % (mark, os.path.basename(p), r["reason"]))
    if len(argv) > 1:
        print(json.dumps({"checked": len(argv), "bad": bad}, ensure_ascii=False))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
