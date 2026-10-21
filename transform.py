# -*- coding: utf-8 -*-
"""transform.py — تبدیل ویدیوی دانلودشده به یک ویدیوی تازه (نه ریپاست خام).

چرا این ماژول وجود دارد
-----------------------
مهر زدن لوگو کافی نیست. یوتیوب در سیاست «محتوای بازاستفاده‌شده» (reused
content) صریح می‌گوید کانالی که کارش دوباره‌آپلود کردن محتوای دیگران است
صلاحیت درآمدزایی ندارد — حتی با واترمارک، حتی با اعتباردهی در توضیحات.
پس اگر هدف درآمد است، ویدیو باید واقعاً «اثر تازه» باشد.

این ماژول چهار تغییر واقعی روی کلیپ اعمال می‌کند:

  1. **روایت فارسی (voice-over)** — یک متن فارسی درباره‌ی همان کلیپ نوشته
     می‌شود و با TTS خوانده می‌شود. این «صدای مؤلف» است: چیزی که از خودمان
     اضافه شده و در فایل اصلی وجود نداشت.
  2. **جایگزینی صدا** — صدای اصلی حذف (یا تا حد ambience کم) می‌شود. این
     هم Content ID صوتی را از بین می‌برد، هم تغییر واقعی است.
  3. **تدوین تصویر** — punch-in (بزرگ‌نمایی و برش) تا کادربندی از اصل متفاوت
     باشد، به‌علاوه‌ی کارت تیتر اختصاصی در ابتدا و کارت CTA در انتها.
  4. **مهر کانال** — پلاک `@padiz` که watermark.py می‌سازد.

نتیجه یک فایل با مدت، صدا، کادربندی و لایه‌های گرافیکی متفاوت است.

قاعده‌ی خطا
-----------
`on_error`:
  * `"next"` (پیش‌فرض) — اگر تبدیل شکست خورد، این ویدیو آپلود **نمی‌شود** و
    سراغ کاندیدای بعدی می‌رویم. برای درآمد امن‌تر است: بهتر است یک روز یک
    ویدیو کمتر منتشر شود تا یک ریپاست خام روی کانال برود.
  * `"raw"` — فایل اصلی (مهرخورده) آپلود شود. فقط برای دیباگ.

Usage
-----
    python transform.py in.mp4 -o out.mp4 --niche comedy
    python transform.py in.mp4 --no-narration        # فقط تدوین تصویر
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from PIL import Image, ImageDraw  # noqa: E402

# Child of the "shortsdl" logger on purpose — utils.setup_logging() configures
# that tree, so a bare logger name here would produce no output at all.
LOG = logging.getLogger("shortsdl.transform")

ACCENT = (255, 45, 85)          # صورتی برند (همان watermark.py)
PANEL = (10, 10, 14)            # مشکی دودی
WHITE = (255, 255, 255)
SS = 2                          # supersampling برای متن‌های بزرگ

DEFAULTS = {
    "enabled": True,
    "narration": {
        "enabled": True,
        # اگر روایت ساخته نشود چه شود؟
        #   "upload" = با تدوین تصویری (punch-in + کارت‌ها + برند) منتشر شود و
        #              صدای اصلی حفظ شود. پیش‌فرض: ویدیو از دست نمی‌رود.
        #   "skip"   = منتشر نشود. امن‌ترین حالت برای درآمد، ولی اگر TTS روی
        #              سرور کار نکند یعنی روزی صفر ویدیو منتشر می‌شود.
        # `required` فقط برای سازگاری با نسخه‌های قبلی نگه داشته شده است.
        "on_fail": "upload",
        "required": True,
        "backends": ["edge", "gemini"],   # به همین ترتیب امتحان می‌شوند
        "voice": "fa-IR-FaridNeural",
        "rate": "+0%",
        "delay_ms": 350,        # روایت کمی بعد از شروع تصویر
    },
    "visual": {
        "punch_in": 1.10,       # ۱.۰ = خاموش. ۱.۱ = ده درصد بزرگ‌نمایی و برش
        "hook_sec": 1.6,        # مدت نمایش کارت تیتر
        "outro_sec": 1.9,       # مدت نمایش کارت CTA
        "fps": 30,
        "brand": "PADIZ",
        "handle": "@padiz",
        "cta": "سابسکرایب کن",
    },
    "audio": {
        "original_volume": 0.0,  # ۰ = صدای اصلی کاملاً حذف (امن‌ترین)
    },
    "crf": 22,
    "preset": "veryfast",
    "on_error": "next",         # next | raw
}


# --------------------------------------------------------------------------- #
# متن روایت
# --------------------------------------------------------------------------- #
# هشتگ/اموجی در متن گفتاری خوانده نمی‌شود، پس قبل از TTS پاک می‌شود.
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2B00-\u2BFF"
    "\U0001F1E6-\U0001F1FF\u2190-\u21FF]+"
)
_HASHTAG_RE = re.compile(r"[#@][\w\u0600-\u06FF_]+")

HOOKS = {
    "comedy": ["اینو تا آخر ببین", "نمیتونی نخندی", "این کلیپ رو از دست نده"],
    "satisfying": ["چشمات رو به این بدوز", "آرامش محض", "بهترین بخش روزت"],
    "sports": ["این حرکت رو ببین", "باورت میشه", "این لحظه تکرار نمیشه"],
    "facts": ["اینو احتمالاً نمیدونستی", "یه نکته‌ی عجیب", "مغزت رو منفجر می‌کنه"],
    "": ["اینو ببین", "بهترین کلیپ امروز", "این یکی خاصه"],
}

BODIES = {
    "comedy": [
        "بعضی وقت‌ها دنیا خودش کمدی می‌نویسه و ما فقط تماشا می‌کنیم.",
        "همین یه لحظه‌ی کوچیک می‌تونه کل روزت رو بسازه. تا آخر ببین.",
        "این لحظه‌ها ساختگی نیستن؛ واقعاً اتفاق افتادن و کسی به‌موقع دوربین داشت.",
    ],
    "satisfying": [
        "این کلیپ‌ها برای وقتیه که مغزت به استراحت نیاز داره. فقط نگاه کن.",
        "دقیقاً همین نظم و ترتیب، آرام‌ترین حس دنیاست.",
        "صدا رو کم کن، نفس بکش و بذار این نظم کار خودش رو بکنه.",
    ],
    "sports": [
        "این حرکت توی هزار بار تکرار هم اتفاق نمی‌افته.",
        "سرعت، دقت و یه ذره شانس؛ این چیزیه که ورزش رو دیدنی می‌کنه.",
        "لحظه‌ای که همه‌ی تمرین‌های یک عمر، توی یک ثانیه جواب می‌ده.",
    ],
    "facts": [
        "چیزهایی که هر روز از کنارشون رد می‌شیم و اصلاً نمی‌دونیم.",
        "علم پر از چیزهای عجیبه و این یکی واقعاً غیرمنتظره‌ست.",
        "یه واقعیت کوچیک که بعد از شنیدنش، دنیا رو کمی متفاوت می‌بینی.",
    ],
    "": [
        "ما هر روز بهترین کلیپ‌های کوتاه یوتیوب رو برای تو انتخاب می‌کنیم.",
        "این یکی از اون‌هایی‌ست که ارزش داره دو بار ببینی.",
        "چند ثانیه وقت بذار؛ ارزشش رو داره.",
    ],
}

CTAS = [
    "کانال پادیز رو سابسکرایب کن.",
    "سابسکرایب کن تا هر روز یکی از این‌ها رو ببینی.",
    "برای بیشتر، سابسکرایب کن.",
]

_FA_NORM = str.maketrans({"\u0643": "ک", "\u064a": "ی", "\u0649": "ی", "\u06c0": "ه"})


def _seed(video_id: str) -> int:
    return int(hashlib.md5(str(video_id or "x").encode("utf-8")).hexdigest(), 16)


def _pick(pool: list[str], seed: int, salt: int = 0) -> str:
    if not pool:
        return ""
    return pool[(seed + salt * 7919) % len(pool)]


def narrate(item: dict, niche: str | None = None, duration: float = 30.0) -> dict:
    """متن روایت فارسی را می‌سازد.

    Returns: {"hook": متن روی کارت تیتر, "spoken": متن گفتاری, "chars": int}

    طول متن به مدت کلیپ وابسته است: کلیپ کوتاه روایت کوتاه می‌گیرد تا جمله
    نصفه نشود (TTS اگر از ویدیو بلندتر باشد بریده می‌شود).
    """
    niche = (niche or item.get("niche") or "").strip().lower()
    if niche not in HOOKS:
        niche = ""
    seed = _seed(item.get("id") or item.get("url") or "")

    hook = _pick(HOOKS[niche], seed)
    body = _pick(BODIES[niche], seed, salt=1)

    parts = [hook + "." if not hook.endswith(("!", "؟", ".")) else hook, body]
    # CTA فقط وقتی جا هست: کلیپ کوتاه‌تر از ۱۸ ثانیه CTA نمی‌گیرد.
    if duration >= 18:
        parts.append(_pick(CTAS, seed, salt=2))

    spoken = " ".join(p for p in parts if p)
    spoken = _EMOJI_RE.sub(" ", spoken)
    spoken = _HASHTAG_RE.sub(" ", spoken)
    spoken = re.sub(r"\s{2,}", " ", spoken).translate(_FA_NORM).strip()

    return {"hook": hook, "spoken": spoken, "chars": len(spoken)}


# --------------------------------------------------------------------------- #
# ffmpeg / probe
# --------------------------------------------------------------------------- #
def ffmpeg_path() -> str | None:
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def probe(path: str) -> dict:
    """عرض/ارتفاع/مدت/داشتن صدا/نرخ فریم را از خروجی ffmpeg می‌خواند.

    ffprobe در بسته‌ی imageio-ffmpeg نیست، پس همان ffmpeg با `-i` و بدون
    فایل خروجی صدا زده می‌شود؛ کد خطا می‌دهد ولی همه‌ی اطلاعات را چاپ می‌کند.
    """
    info = {"w": 0, "h": 0, "dur": 0.0, "audio": False, "fps": 30.0}
    ff = ffmpeg_path()
    if not ff:
        return info
    try:
        res = subprocess.run([ff, "-hide_banner", "-i", str(path)],
                             capture_output=True, text=True, errors="replace",
                             timeout=90)
        txt = (res.stderr or "") + (res.stdout or "")
    except Exception:
        return info

    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", txt)
    if m:
        info["w"], info["h"] = int(m.group(1)), int(m.group(2))
    d = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if d:
        info["dur"] = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
    info["audio"] = "Audio:" in txt
    f = re.search(r"(\d+(?:\.\d+)?)\s*fps", txt)
    if f:
        try:
            v = float(f.group(1))
            if 10.0 <= v <= 120.0:
                info["fps"] = v
        except ValueError:
            pass
    return info


def _even(n: float) -> int:
    n = int(round(n))
    return max(2, n - (n % 2))


# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #
def synthesize(text: str, out_path: str, voice: str = "fa-IR-FaridNeural",
               rate: str = "+0%", backends: list[str] | None = None) -> tuple[str | None, str]:
    """متن را به mp3 تبدیل می‌کند و (مسیر, نام بک‌اند) برمی‌گرداند.

    چرا چند بک‌اند: edge-tts (مایکروسافت) از بعضی IP ها با ۴۰۳ بسته می‌شود
    (ایران جزو همین‌هاست). اگر فقط یک مسیر باشد، کل زنجیره می‌خوابد. ترتیب
    پیش‌فرض: edge → gemini (اگر GEMINI_API_KEY ست شده باشد).
    """
    if not text.strip():
        return None, ""

    for backend in (backends or ["edge", "gemini"]):
        name = str(backend or "").lower().strip()
        if name == "edge":
            got = _tts_edge(text, out_path, voice, rate)
        elif name == "gemini":
            got = _tts_gemini(text, out_path)
        else:
            continue
        if got:
            return got, name
    return None, ""


def _tts_edge(text: str, out_path: str, voice: str, rate: str) -> str | None:
    try:
        import edge_tts
    except ImportError:
        LOG.warning("[transform] edge-tts نصب نیست")
        return None

    async def _go():
        com = edge_tts.Communicate(text, voice, rate=rate)
        await com.save(out_path)

    try:
        try:
            asyncio.run(_go())
        except RuntimeError:
            # داخل یک event loop فعال هستیم (اجرای async بیرونی)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_go())
            finally:
                loop.close()
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[transform] edge-tts شکست خورد (%s): %s", voice, str(exc)[:140])
        return None

    return out_path if _usable(out_path) else None


def _tts_gemini(text: str, out_path: str) -> str | None:
    """Gemini TTS از طریق pipeline؛ فقط اگر کلید موجود باشد."""
    if not (os.environ.get("GEMINI_API_KEY") or "").strip():
        return None
    try:
        import pipeline as P
        if P.generate_voice_gemini(text, out_path):
            return out_path if _usable(out_path) else None
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[transform] gemini-tts شکست خورد: %s", str(exc)[:140])
    return None


def _usable(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 1024


# --------------------------------------------------------------------------- #
# کارت‌های گرافیکی
# --------------------------------------------------------------------------- #
def _helpers():
    """(font_for, draw_persian, wrap) را از pipeline می‌گیرد، با fallback مستقل.

    pipeline سنگین است (edge_tts، googleapiclient) و در محیط تست ممکن است
    import نشود؛ در آن حالت خودمان با arabic_reshaper کار می‌کنیم.
    """
    try:
        import pipeline as P
        return P.font_for, P.draw_persian, P._wrap_to_width, P._measure
    except Exception:
        pass

    from PIL import ImageFont
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
    except ImportError:
        arabic_reshaper = None
        get_display = None

    fa_path = BASE_DIR / "Vazirmatn-Bold.ttf"

    def font_for(_text, size):
        try:
            return ImageFont.truetype(str(fa_path), size)
        except Exception:
            return ImageFont.load_default()

    def draw_persian(draw, xy, text, font, fill, anchor="mm"):
        t = text
        if arabic_reshaper and get_display:
            t = get_display(arabic_reshaper.reshape(text))
        draw.text(xy, t, font=font, fill=fill, anchor=anchor)

    def measure(draw, s, font):
        try:
            return draw.textlength(s, font=font)
        except Exception:
            return float(len(s) * getattr(font, "size", 40) * 0.6)

    def wrap(draw, text, font, max_width, max_lines=2):
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if measure(draw, trial, font) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
                if len(lines) == max_lines:
                    break
        if cur and len(lines) < max_lines:
            lines.append(cur)
        return lines[:max_lines]

    return font_for, draw_persian, wrap, measure


def _fit_font(font_for, draw, text: str, size: int, max_width: int):
    """بزرگ‌ترین اندازه‌ای که متن در عرض داده‌شده جا شود (حداقل ۴۰٪ اندازه‌ی اولیه)."""
    measure = None
    for _ in range(24):
        font = font_for(text, size)
        try:
            w = draw.textlength(text, font=font)
        except Exception:
            w = len(text) * size * 0.6
        if w <= max_width or size <= max(12, int(size * 0.4)):
            return font, size
        size = int(size * 0.92)
    return font_for(text, size), size


def make_hook_png(text: str, w: int, h: int, out_path: str,
                  brand: str = "PADIZ") -> str | None:
    """کارت تیتر: پنل نیمه‌شفاف با تیتر فارسی + نوار برند.

    همه‌چیز با ضریب SS بزرگ‌تر رندر و بعد با LANCZOS کوچک می‌شود تا لبه‌ی
    فارسی و منحنی پنل نرم باشد. اگر مختصات را با اندازه‌ی نهایی حساب کنیم و
    فونت را در SS ضرب کنیم (باگ قبلی) متن دو برابر می‌شود و سرریز می‌کند.
    """
    font_for, draw_persian, wrap, _measure = _helpers()
    try:
        W, H = w * SS, h * SS
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        panel_w = int(W * 0.86)
        inner_w = panel_w - int(W * 0.13)
        fs = int(H * 0.052)
        font = font_for(text, fs)
        lines = wrap(d, text, font, inner_w, max_lines=2) or [text]
        # اگر بلندترین خط جا نشد، فونت را کوچک کن
        widest = max(lines, key=len)
        font, fs = _fit_font(font_for, d, widest, fs, inner_w)

        line_h = int(fs * 1.38)
        pad_y = int(fs * 0.66)
        brand_fs = max(18, int(fs * 0.34))
        bfont = font_for(brand, brand_fs)
        bar = max(4, int(fs * 0.15))

        panel_h = pad_y * 2 + line_h * len(lines) + int(brand_fs * 2.4)
        cx, cy = W // 2, int(H * 0.40)

        box = [cx - panel_w // 2, cy - panel_h // 2,
               cx + panel_w // 2, cy + panel_h // 2]
        d.rounded_rectangle(box, radius=int(panel_h * 0.10),
                            fill=PANEL + (208,),
                            outline=ACCENT + (235,), width=max(2, bar // 2))
        # نوار صورتی سمت راست پنل (سمت شروع خواندن فارسی)
        bar_x = box[2] - bar - int(panel_w * 0.035)
        d.rounded_rectangle([bar_x, box[1] + pad_y,
                             bar_x + bar, box[3] - pad_y],
                            radius=bar // 2, fill=ACCENT + (255,))

        ty = box[1] + pad_y + line_h // 2
        for ln in lines:
            draw_persian(d, (cx, ty), ln, font, WHITE + (255,), anchor="mm")
            ty += line_h

        # خط برند
        by = box[3] - pad_y - brand_fs // 2
        dot = max(4, int(brand_fs * 0.26))
        tw = d.textlength(brand.upper(), font=bfont)
        total = dot * 2 + int(brand_fs * 0.45) + tw
        sx = cx - total // 2
        d.ellipse([sx, by - dot, sx + dot * 2, by + dot], fill=ACCENT + (255,))
        d.text((sx + dot * 2 + int(brand_fs * 0.45), by), brand.upper(),
               font=bfont, fill=(255, 255, 255, 215), anchor="lm")

        img.resize((w, h), Image.LANCZOS).save(out_path, "PNG")
        return out_path
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[transform] ساخت کارت تیتر شکست خورد: %s", str(exc)[:120])
        return None


def make_outro_png(w: int, h: int, out_path: str, cta: str = "سابسکرایب کن",
                   handle: str = "@padiz") -> str | None:
    """کارت پایانی: دعوت به سابسکرایب + آدرس کانال."""
    font_for, draw_persian, _wrap, _measure = _helpers()
    try:
        W, H = w * SS, h * SS
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        panel_w = int(W * 0.86)
        inner_w = panel_w - int(W * 0.14)
        fs = int(H * 0.058)
        hfs = max(20, int(fs * 0.58))

        font, fs = _fit_font(font_for, d, cta, fs, inner_w)
        hfont = font_for(handle, hfs)

        pad_y = int(fs * 0.72)
        panel_h = pad_y * 2 + fs + int(hfs * 1.9)
        cx, cy = W // 2, int(H * 0.78)

        box = [cx - panel_w // 2, cy - panel_h // 2,
               cx + panel_w // 2, cy + panel_h // 2]
        d.rounded_rectangle(box, radius=int(panel_h * 0.28),
                            fill=PANEL + (216,),
                            outline=ACCENT + (240,),
                            width=max(2, int(fs * 0.055)))

        draw_persian(d, (cx, box[1] + pad_y + fs // 2), cta, font,
                     WHITE + (255,), anchor="mm")

        hy = box[3] - pad_y - hfs // 2
        dot = max(4, int(hfs * 0.22))
        tw = d.textlength(handle, font=hfont)
        total = dot * 2 + int(hfs * 0.5) + tw
        sx = cx - total // 2
        d.ellipse([sx, hy - dot, sx + dot * 2, hy + dot], fill=ACCENT + (255,))
        d.text((sx + dot * 2 + int(hfs * 0.5), hy), handle, font=hfont,
               fill=(255, 255, 255, 225), anchor="lm")

        img.resize((w, h), Image.LANCZOS).save(out_path, "PNG")
        return out_path
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[transform] ساخت کارت پایانی شکست خورد: %s", str(exc)[:120])
        return None


# --------------------------------------------------------------------------- #
# تبدیل
# --------------------------------------------------------------------------- #
def _merge(cfg: dict | None) -> dict:
    c = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k].update(v)
        elif v is not None:
            c[k] = v
    return c


def build(src: str, item: dict | None = None, cfg: dict | None = None,
          out_path: str | None = None, niche: str | None = None,
          remove_source: bool = True) -> str | None:
    """کلیپ را به یک ویدیوی تازه تبدیل می‌کند. مسیر خروجی یا None.

    None یعنی تبدیل انجام نشد؛ تصمیم آپلود/عدم‌آپلود با `on_error` است.
    """
    item = item or {}
    c = _merge(cfg)
    on_error = str(c.get("on_error") or "next").lower()

    ff = ffmpeg_path()
    if not ff:
        LOG.error("[transform] ffmpeg پیدا نشد — تبدیل ممکن نیست")
        return src if on_error == "raw" else None

    info = probe(src)
    W, H, dur = info["w"], info["h"], info["dur"]
    if W < 2 or H < 2:
        LOG.error("[transform] ابعاد فایل خوانده نشد: %s", Path(src).name)
        return src if on_error == "raw" else None
    if dur <= 0:
        LOG.error("[transform] مدت فایل خوانده نشد: %s", Path(src).name)
        return src if on_error == "raw" else None

    vis = c["visual"]
    aud = c["audio"]
    ncfg = c["narration"]

    # ---- ۱) روایت ----
    narration = {"hook": "", "spoken": "", "chars": 0}
    voice_path = None
    voice_backend = ""
    tmpdir = tempfile.mkdtemp(prefix="tr_")
    try:
        if ncfg.get("enabled", True):
            narration = narrate(item, niche, duration=dur)
            if narration["spoken"]:
                voice_path, voice_backend = synthesize(
                    narration["spoken"],
                    os.path.join(tmpdir, "voice.mp3"),
                    voice=str(ncfg.get("voice") or "fa-IR-FaridNeural"),
                    rate=str(ncfg.get("rate") or "+0%"),
                    backends=list(ncfg.get("backends") or ["edge", "gemini"]),
                )
            if not voice_path:
                on_fail = str(ncfg.get("on_fail")
                              or ("skip" if ncfg.get("required") else "upload")).lower()
                if on_fail == "skip":
                    LOG.error(
                        "[transform] روایت ساخته نشد و narration.on_fail=skip است "
                        "— این ویدیو آپلود نمی‌شود (ریپاست بدون روایت = محتوای "
                        "بازاستفاده‌شده). تست TTS: python transform.py --tts-test"
                    )
                    return src if on_error == "raw" else None
                # ویدیو را از دست نمی‌دهیم: تدوین تصویری انجام می‌شود و صدای
                # اصلی حفظ می‌شود (بدون این، خروجی بی‌صدا می‌شد چون
                # audio.original_volume پیش‌فرض صفر است).
                LOG.warning(
                    "[transform] روایت ساخته نشد — با صدای اصلی و تدوین تصویری "
                    "منتشر می‌شود. برای روایت: GEMINI_API_KEY را ست کن یا "
                    "narration.on_fail را skip بگذار."
                )
                narration["no_voice"] = True

        # ---- ۲) کارت‌ها ----
        cw, ch = _even(W), _even(H)
        hook_png = outro_png = pill_png = None
        hook_sec = float(vis.get("hook_sec") or 0)
        outro_sec = float(vis.get("outro_sec") or 0)

        if hook_sec > 0:
            hook_png = make_hook_png(narration["hook"] or "اینو ببین", cw, ch,
                                     os.path.join(tmpdir, "hook.png"),
                                     brand=str(vis.get("brand") or "PADIZ"))
        if outro_sec > 0:
            outro_png = make_outro_png(cw, ch, os.path.join(tmpdir, "outro.png"),
                                       cta=str(vis.get("cta") or "سابسکرایب کن"),
                                       handle=str(vis.get("handle") or "@padiz"))

        # مهر کانال (همان پلاک watermark.py تا یکدست بماند)
        try:
            import watermark as _wm
            pill = _wm.build_pill(str(vis.get("handle") or "@padiz"), ch)
            pill_png = os.path.join(tmpdir, "pill.png")
            pill.save(pill_png, "PNG")
            pw, ph = pill.size
            px, py = _wm.position_xy("top", cw, ch, pw, ph, 5.0)
        except Exception:
            pill_png = None
            pw = ph = px = py = 0

        # ---- ۳) گراف فیلتر ----
        fps = int(vis.get("fps") or 30)
        p = max(1.0, float(vis.get("punch_in") or 1.0))
        sw, sh = _even(W * p), _even(H * p)

        # کارت پایانی باید وقت اضافه داشته باشد، وگرنه آخرین ثانیه‌های کلیپ
        # اصلی را می‌پوشاند. tpad آخرین فریم را کلون می‌کند تا end-card روی
        # تصویر جدید بنشیند و محتوای اصلی حذف نشود.
        pad_tail = outro_sec if outro_png else 0.0
        total_dur = dur + pad_tail
        pad_filter = (f",tpad=stop_mode=clone:stop_duration={pad_tail:.3f}"
                      if pad_tail > 0 else "")
        f = [f"[0:v]scale={sw}:{sh},crop={cw}:{ch},setsar=1,"
             f"fps={fps},format=yuv420p{pad_filter}[base]"]

        last = "base"
        idx = 1
        if hook_png:
            fo = max(0.0, hook_sec - 0.35)
            f.append(f"[{idx}:v]format=rgba,"
                     f"fade=t=in:st=0:d=0.28:alpha=1,"
                     f"fade=t=out:st={fo:.2f}:d=0.35:alpha=1[hk]")
            f.append(f"[{last}][hk]overlay=0:0:enable='lte(t,{hook_sec:.2f})'[v1]")
            last = "v1"
            idx += 1
        if outro_png:
            # کارت پایانی از لحظه‌ای ظاهر می‌شود که کلیپ اصلی تمام شده
            # (روی ناحیه‌ی tpad). ورودی تا انتهای تایم‌لاین کش می‌آید و
            # fade هم روی همان زمان کلیپ تنظیم می‌شود، وگرنه محو شدن قبل از
            # دیده‌شدن تمام می‌شد و کارت یک‌دفعه می‌پرید.
            f.append(f"[{idx}:v]format=rgba,"
                     f"fade=t=in:st={dur:.3f}:d=0.35:alpha=1[ot]")
            f.append(f"[{last}][ot]overlay=0:0:enable='gte(t,{dur:.3f})'[v2]")
            last = "v2"
            idx += 1
        if pill_png:
            f.append(f"[{last}][{idx}:v]overlay={px}:{py}[v3]")
            last = "v3"
            idx += 1
        f.append(f"[{last}]null[vout]")

        # ---- ۴) صدا ----
        a_idx = idx
        vol = float(aud.get("original_volume") or 0.0)
        if narration.get("no_voice"):
            # روایت نداریم؛ اگر صدای اصلی هم حذف شود ویدیو بی‌صدا منتشر
            # می‌شود که هم بد به نظر می‌رسد هم در Shorts بازدهی ندارد.
            vol = max(vol, float(aud.get("fallback_volume") or 0.9))
        delay = int(ncfg.get("delay_ms") or 0)
        audio_out = None

        if voice_path:
            # apad صدا را تا انتهای ویدیو کش می‌دهد. عمداً به‌جای `-shortest`
            # از `-t` روی خروجی استفاده می‌کنیم: ترکیب apad + -shortest در
            # ffmpeg 7.1 قفل می‌کند (تست‌شده — فایل ساخته می‌شد ولی پروسه
            # تمام نمی‌شد و با ۱.۵ گیگ رم آویزان می‌ماند).
            f.append(f"[{a_idx}:a]adelay={delay}|{delay},apad,"
                     f"atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS[voice]")
            a_idx += 1
            if vol > 0 and info["audio"]:
                f.append(f"[0:a]volume={vol},apad,atrim=0:{total_dur:.3f}[amb]")
                f.append("[voice][amb]amix=inputs=2:duration=longest:"
                         "dropout_transition=0[aout]")
            else:
                # anull و نه null: فیلتر null فقط پد ویدیویی دارد و اتصال
                # صدا به آن خطای «Media type mismatch» می‌دهد.
                f.append("[voice]anull[aout]")
            audio_out = "aout"
        elif vol > 0 and info["audio"]:
            f.append(f"[0:a]apad,atrim=0:{total_dur:.3f}[aout]")
            audio_out = "aout"

        # ---- ۵) ورودی‌ها و دستور ----
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
        if hook_png:
            cmd += ["-framerate", str(fps), "-loop", "1",
                    "-t", f"{hook_sec + 0.8:.2f}", "-i", hook_png]
        if outro_png:
            # ورودی باید تا انتهای تایم‌لاین زنده بماند تا fade روی t=dur
            # فریم داشته باشد.
            cmd += ["-framerate", str(fps), "-loop", "1",
                    "-t", f"{total_dur + 0.8:.2f}", "-i", outro_png]
        if pill_png:
            cmd += ["-framerate", str(fps), "-loop", "1",
                    "-t", f"{total_dur + 1.0:.2f}", "-i", pill_png]
        if voice_path:
            cmd += ["-i", voice_path]

        if not out_path:
            out_path = str(Path(src).with_name(Path(src).stem + "_tr.mp4"))

        cmd += ["-filter_complex", ";".join(f), "-map", "[vout]"]
        cmd += ["-map", f"[{audio_out}]"] if audio_out else ["-an"]
        cmd += [
            "-c:v", "libx264", "-preset", str(c.get("preset") or "veryfast"),
            "-crf", str(c.get("crf") or 22), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            # سقف زمانی صریح: طول خروجی = طول ورودی + کارت پایانی. بدون این،
            # overlay با ورودی‌های حلقه‌ای می‌تواند بی‌نهایت جلو برود.
            "-t", f"{total_dur + 0.05:.3f}",
            out_path,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 errors="replace", timeout=3600)
            ok = (res.returncode == 0 and os.path.exists(out_path)
                  and os.path.getsize(out_path) > 4096)
        except Exception as exc:  # noqa: BLE001
            LOG.error("[transform] ffmpeg اجرا نشد: %s", str(exc)[:160])
            ok = False
            res = None

        if not ok:
            tail = (getattr(res, "stderr", "") or "").strip().splitlines()
            LOG.error("[transform] تبدیل شکست خورد (%s)", tail[-1][:200] if tail else "بدون پیام")
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except OSError:
                pass
            return src if on_error == "raw" else None

        new_info = probe(out_path)
        LOG.info(
            "[transform] ✅ تبدیل شد: %dx%d %.1fs → %.1fs | punch-in %.2fx | "
            "روایت %d کاراکتر (%s) | صدا: %s | تیتر: %s | CTA: %s",
            cw, ch, dur, new_info["dur"] or total_dur, p,
            narration["chars"], voice_backend or "ندارد",
            "جایگزین شد" if voice_path else ("اصلی" if info["audio"] else "بی‌صدا"),
            "دارد" if hook_png else "ندارد",
            "دارد" if outro_png else "ندارد",
        )

        if remove_source and os.path.abspath(src) != os.path.abspath(out_path):
            try:
                os.remove(src)
            except OSError:
                pass
        return out_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def tts_selftest() -> int:
    """تست سریع TTS روی همین ماشین/سرور.

    روی سرور یک بار اجرا کن تا مطمئن شوی روایت ساخته می‌شود؛ اگر نشد،
    ریپاست‌ها عمداً آپلود نمی‌شوند.
    """
    tmp = tempfile.mkdtemp(prefix="tts_")
    sample = "سلام. این یک تست کوتاه برای بررسی صدای فارسی است."
    print("متن تست:", sample)
    print("بک‌اندها: edge → gemini\n")
    got, backend = synthesize(sample, os.path.join(tmp, "t.mp3"),
                              backends=["edge", "gemini"])
    if got:
        size = os.path.getsize(got)
        dur = probe(got)["dur"]
        print(f"✅ TTS کار می‌کند | بک‌اند: {backend} | {size} بایت | {dur:.1f} ثانیه")
        keep = os.path.join(BASE_DIR, "tts_selftest.mp3")
        try:
            shutil.copyfile(got, keep)
            print("نمونه ذخیره شد:", keep)
        except OSError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        return 0
    shutil.rmtree(tmp, ignore_errors=True)
    print("❌ هیچ بک‌اندی کار نکرد.")
    print("   edge-tts: اگر ۴۰۳ می‌دهد یعنی IP توسط مایکروسافت بسته شده")
    print("   (ایران معمولاً بسته است). راه‌حل: GEMINI_API_KEY ست کن،")
    print("   یا سرور را روی IP دیگری اجرا کن.")
    return 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="تبدیل کلیپ دانلودشده به ویدیوی تازه")
    ap.add_argument("video", nargs="?", default=None)
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--niche", default=None,
                    help="comedy | satisfying | sports | facts")
    ap.add_argument("--punch-in", type=float, default=None)
    ap.add_argument("--no-narration", action="store_true")
    ap.add_argument("--allow-no-narration", action="store_true",
                    help="اگر روایت ساخته نشد باز هم ادامه بده")
    ap.add_argument("--keep-audio", type=float, default=None,
                    help="صدای اصلی با این حجم بماند (۰ = حذف)")
    ap.add_argument("--keep", action="store_true", help="فایل اصلی را پاک نکن")
    ap.add_argument("--tts-test", action="store_true",
                    help="فقط TTS را تست کن و خارج شو")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(message)s")

    if a.tts_test:
        return tts_selftest()

    if not a.video:
        ap.error("مسیر ویدیو لازم است (یا از --tts-test استفاده کن)")

    cfg: dict = {"on_error": "raw"}
    if a.no_narration:
        cfg["narration"] = {"enabled": False}
    if a.allow_no_narration:
        cfg["narration"] = {"required": False}
    if a.punch_in is not None:
        cfg["visual"] = {"punch_in": a.punch_in}
    if a.keep_audio is not None:
        cfg["audio"] = {"original_volume": a.keep_audio}

    out = build(a.video, {"id": Path(a.video).stem}, cfg, out_path=a.out,
                niche=a.niche, remove_source=not a.keep)
    if not out:
        print("تبدیل انجام نشد.")
        return 1
    print("خروجی:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
