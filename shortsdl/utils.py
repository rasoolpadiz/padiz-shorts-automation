"""ابزارهای کمکی مشترک: لاگ، فرمت‌دهی اعداد، پیدا کردن ffmpeg، ادغام تنظیمات."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("shortsdl")


# --------------------------------------------------------------------------- #
# لاگ
# --------------------------------------------------------------------------- #
def setup_logging(log_dir: Path | None = None, verbose: bool = False) -> None:
    """لاگ را روی کنسول (و در صورت نیاز فایل) تنظیم می‌کند."""
    # جلوگیری از خطای کدگذاری کاراکترهای فارسی در کنسول ویندوز
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")

    root = logging.getLogger("shortsdl")
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(
            log_dir / f"run-{datetime.now():%Y%m%d-%H%M%S}.log", encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
        root.addHandler(fh)


# --------------------------------------------------------------------------- #
# فرمت‌دهی
# --------------------------------------------------------------------------- #
def human_views(n) -> str:
    """۱۲۳۴۵۶۷ -> 1.2M"""
    if n in (None, "", 0):
        return "-"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def human_duration(seconds) -> str:
    if not seconds:
        return "-"
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "-"
    return f"{s // 60}:{s % 60:02d}"


def human_size(num_bytes) -> str:
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return "-"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_name(text: str, maxlen: int = 80) -> str:
    """نام فایل امن (فقط برای فایل‌های جانبی مثل عنوان‌ها)."""
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", str(text or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:maxlen] or "untitled"


# --------------------------------------------------------------------------- #
# ffmpeg
# --------------------------------------------------------------------------- #
def ffmpeg_location() -> str | None:
    """مسیر ffmpeg را برمی‌گرداند (imageio-ffmpeg یا نصب سیستمی)."""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


# --------------------------------------------------------------------------- #
# تنظیمات
# --------------------------------------------------------------------------- #
def deep_merge(base: dict, override: dict) -> dict:
    """ادغام بازگشتی دیکشنری‌ها (override روی base)."""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def read_json(path: Path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
