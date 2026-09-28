# -*- coding: utf-8 -*-
"""اجرا/زمان‌بندی بخش «پیدا کردن ویدیو» روی همین کامپیوتر ویندوزی.

چرا این گزینه؟ IP این کامپیوتر توسط یوتیوب بلاک نیست (تست شد: دانلود موفق).
پس اگر کامپیوتر در آن ساعت‌ها روشن باشد، هیچ کوکی و هیچ تنظیم دیگری لازم نیست.

    python setup_windows_schedule.py --list             # تسک‌های فعلی
    python setup_windows_schedule.py --install          # ثبت ۳ اجرای روزانه
    python setup_windows_schedule.py --install --times 10:30,15:30,20:30
    python setup_windows_schedule.py --run-now          # همین حالا یک اجرا (تست)
    python setup_windows_schedule.py --remove           # حذف تسک‌ها

نکتهٔ مهم: سهمیهٔ روزانهٔ YouTube Data API ده‌هزار واحد است و هر آپلود ۱۶۰۰ واحد
می‌خورد؛ پس تعداد کل آپلودهای روز (گیت‌هاب + این کامپیوتر) را زیر ۶ نگه دارید.
"""

import argparse
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TASK_PREFIX = "PadizViralHunter"
RUNNER_BAT = os.path.join(BASE_DIR, "run_viral_windows.bat")
DEFAULT_TIMES = ["10:30", "15:30", "20:30"]

RUNNER_BAT_CONTENT = """@echo off
REM اجرای بخش «پیدا کردن ویدیو» - لاگ در viral_windows.log نوشته می‌شود
cd /d "{base}"
"{python}" -u viral_hunter.py --once >> "{base}\\viral_windows.log" 2>&1
"""
