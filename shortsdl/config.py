"""تنظیمات پیش‌فرض و بارگذاری config.json."""

from __future__ import annotations

from pathlib import Path

from .utils import deep_merge, read_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Merged into the Padiz repo: the downloader keeps its own config file so it can
# never collide with the publishing settings (or a future config.json).
CONFIG_NAME = "shortsdl_config.json"

DEFAULT_CONFIG: dict = {
    "output_dir": "repost_out",
    "per_market_limit": 25,
    "markets": {
        "global": {
            "label": "جهانی (Global)",
            "region_code": "US",
            "relevance_language": "en",
            "sp": "CAMSAhgB",
            "queries": [
                "#shorts",
                "shorts",
                "satisfying video",
                "cute animals",
                "funny video",
                "dance challenge",
                "football skills",
                "life hacks",
                "asmr",
                "magic tricks",
            ],
        },
        "persian": {
            "label": "فارسی (Persian)",
            "region_code": "IR",
            "relevance_language": "fa",
            "sp": "CAMSAhgB",
            "require_script": "persian",
            "queries": [
                "خنده دار",
                "کلیپ خنده دار",
                "طنز ایرانی",
                "ویدیو خنده دار",
                "شعر",
                "آشپزی",
                "حیوانات",
                "سرگرمی",
                "فان",
                "کلیپ کوتاه",
            ],
        },
        "trending": {
            "label": "ترند جهانی (این هفته)",
            "region_code": "US",
            "relevance_language": "en",
            "filters_sp": {"sort": "views", "upload": "week"},
            "queries": [
                "shorts", "viral", "trending", "challenge", "funny", "dance",
                "music", "food", "football", "animals", "satisfying", "asmr",
                "prank", "magic", "recipe",
            ],
        },
    },
    "filters": {
        "max_duration_sec": 180,
        "min_views": 0,
        "skip_live": True,
        # Shorts must be vertical. Search with the "short" duration filter still
        # returns landscape clips (a 1920x1080 trailer came back as result #1 on
        # a real trending query), so repost.py re-checks the real dimensions
        # after download and rejects anything wider than it is tall.
        "require_vertical": True,
    },
    # Merged repost pipeline: the channel handle is burned onto every downloaded
    # Short before upload (watermark.py).
    "watermark": {
        "enabled": True,
        "text": "@padiz_studio",
        "position": "top",
        "margin_pct": 5.0,
        "font_pct": 2.6,
        "opacity": 0.88,
        "preset": "veryfast",
        "crf": 23,
        "on_error": "skip",
    },
    "download": {
        "max_height": 1080,
        "workers": 3,
        "retries": 3,
        "sleep_between": 1.0,
        "cookies_file": None,
        "proxy": None,
        "player_clients": ["default", "android"],
        "write_thumbnail": True,
        "write_info_json": True,
    },
    "discovery": {
        "results_per_query": 25,
        "request_delay": 0.3,
        "search_workers": 4,
        "overfetch": 3,
        "cache_minutes": 30,
    },
}


def load_config(path: str | Path | None = None) -> dict:
    """config.json را می‌خواند و روی مقادیر پیش‌فرض ادغام می‌کند."""
    if path:
        cfg_path = Path(path)
    else:
        cfg_path = PROJECT_ROOT / CONFIG_NAME
        if not cfg_path.exists():
            cfg_path = PROJECT_ROOT / "config.json"
    user_cfg = read_json(cfg_path, default={}) or {}
    return deep_merge(DEFAULT_CONFIG, user_cfg)


def resolve_path(value: str | Path, base: Path | None = None) -> Path:
    """مسیرهای نسبی را نسبت به ریشه پروژه مطلق می‌کند."""
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = (base or PROJECT_ROOT) / p
    return p.resolve()
