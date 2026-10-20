# -*- coding: utf-8 -*-
"""watermark.py — مهر زدن لوگوی آدرس کانال روی ویدیوهای دانلودشده.

چرا ماژول جدا؟
    ویدیوهای ریپاست مال کانال‌های دیگرند. بدون مهر، ویدیو روی کانال ما شبیه
    یک کپی خام دیده می‌شود. این ماژول یک پلاک کوچک با آدرس کانال می‌سازد و با
    ffmpeg روی فریم‌ها می‌نشاند.

نکات مهم پیاده‌سازی:
  * پلاک با PIL ساخته می‌شود (۳ برابر بزرگ‌تر، بعد کوچک می‌شود) تا لبه‌هایش
    نرم باشد؛ اندازه‌اش بر اساس ارتفاع خودِ ویدیو حساب می‌شود، پس روی ۷۲۰p و
    ۱۰۸۰p و ۴K یک‌شکل دیده می‌شود.
  * ویدیو باید دوباره کدگذاری شود (overlay با -c:v copy ممکن نیست). برای اینکه
    روی CPU ضعیف سرور طول نکشد، preset پیش‌فرض veryfast و crf 23 است.
  * صدا به aac تبدیل می‌شود، چون بعضی دانلودها opus/dolby دارند و کپی خام آن
    داخل mp4 یوتیوب را رد می‌کند.
  * فایل اصلی بلافاصله بعد از مهر زدن پاک می‌شود: خواسته‌ی مالک این است که
    هیچ ویدیویی روی سرور نماند (حجم سرویس).

Usage:
    python watermark.py in.mp4 -o out.mp4
    python watermark.py in.mp4 --text "@padiz" --position bottom
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent

# فونت‌های لاتین (آدرس کانال لاتین است). Vazirmatn هم هست اگر @ و حروف لاتین
# داشته باشد، ولی برای وزن بصری بیشتر اول فونت‌های بولد سیستم امتحان می‌شوند.
FONT_CANDIDATES = [
    BASE_DIR / "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    BASE_DIR / "Vazirmatn-Bold.ttf",
]

ACCENT = (255, 45, 85)          # همان صورتی برند در pipeline.draw_cta_pill
PILL_FILL = (16, 16, 22)        # مشکی دودی برند
SS = 3                          # ضریب supersampling برای لبه‌های نرم

DEFAULT_CFG = {
    "enabled": True,
    "text": "@padiz",
    "position": "top",          # top | bottom | top-left | top-right | bottom-left | bottom-right
    "margin_pct": 5.0,          # فاصله از لبه، درصد ارتفاع
    "font_pct": 2.2,            # اندازه فونت، درصد ارتفاع ویدیو
    "opacity": 0.88,
    "preset": "veryfast",
    "crf": 23,
    "on_error": "skip",         # skip = بدون مهر آپلود کن | fail = آپلود نکن
}


# --------------------------------------------------------------------------- #
# ابزارها
# --------------------------------------------------------------------------- #
def ffmpeg_path() -> str | None:
    """ffmpeg را از imageio-ffmpeg یا نصب سیستمی پیدا می‌کند."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def probe_size(video_path: str) -> tuple[int, int]:
    """(عرض، ارتفاع) ویدیو را از خروجی ffmpeg می‌خواند.

    ffprobe در imageio-ffmpeg نیست، پس همان ffmpeg را با -i صدا می‌زنیم؛
    بدون فایل خروجی با کد خطا برمی‌گردد ولی اطلاعات را چاپ می‌کند.
    """
    ff = ffmpeg_path()
    if not ff:
        return 1080, 1920
    try:
        res = subprocess.run(
            [ff, "-hide_banner", "-i", str(video_path)],
            capture_output=True, text=True, errors="replace", timeout=60,
        )
        text = (res.stderr or "") + (res.stdout or "")
        m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return 1080, 1920


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        try:
            if os.path.exists(p):
                return ImageFont.truetype(str(p), size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default(size)


def _text_w(draw, text: str, font) -> int:
    try:
        box = draw.textbbox((0, 0), text, font=font)
        return box[2] - box[0]
    except Exception:
        return int(len(text) * font.size * 0.55)


# --------------------------------------------------------------------------- #
# ساخت پلاک
# --------------------------------------------------------------------------- #
def build_pill(text: str, video_h: int, opacity: float = 0.88,
               font_pct: float = 2.2) -> Image.Image:
    """پلاک RGBA با آدرس کانال می‌سازد (اندازه بر اساس ارتفاع ویدیو)."""
    font_px = max(20, int(video_h * max(0.6, float(font_pct)) / 100.0))
    fs = font_px * SS
    font = _font(fs)
    pad_x = int(fs * 0.62)
    pad_y = int(fs * 0.42)
    dot = int(fs * 0.26)
    gap = int(fs * 0.34)

    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = _text_w(probe, text, font)

    w = pad_x * 2 + dot * 2 + gap + tw
    h = fs + pad_y * 2

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    alpha = int(255 * max(0.0, min(1.0, opacity)))
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2,
                        fill=PILL_FILL + (alpha,),
                        outline=(255, 255, 255, int(alpha * 0.28)),
                        width=max(1, SS))
    cy = h // 2
    cx = pad_x + dot
    d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=ACCENT + (255,))
    d.text((cx + dot + gap, cy), text, font=font,
           fill=(255, 255, 255, 255), anchor="lm")

    # کوچک‌کردن با LANCZOS تا لبه‌ها نرم شوند
    return img.resize((max(1, w // SS), max(1, h // SS)), Image.LANCZOS)


def position_xy(position: str, vw: int, vh: int, pw: int, ph: int,
                margin_pct: float) -> tuple[int, int]:
    mx = int(vw * margin_pct / 100.0)
    my = int(vh * margin_pct / 100.0)
    pos = (position or "top").lower()
    if pos == "top":
        return (vw - pw) // 2, my
    if pos == "bottom":
        return (vw - pw) // 2, vh - ph - my
    if pos == "top-left":
        return mx, my
    if pos == "top-right":
        return vw - pw - mx, my
    if pos == "bottom-left":
        return mx, vh - ph - my
    if pos == "bottom-right":
        return vw - pw - mx, vh - ph - my
    return (vw - pw) // 2, my


# --------------------------------------------------------------------------- #
# اجرا
# --------------------------------------------------------------------------- #
def apply(src: str, cfg: dict | None = None, out_path: str | None = None,
          remove_source: bool = True) -> str | None:
    """مهر را روی ویدیو می‌نشاند. مسیر فایل خروجی را برمی‌گرداند.

    اگر همه‌چیز شکست بخورد:
      * on_error="skip" -> مسیر اصلی برگردانده می‌شود (آپلود بدون مهر)
      * on_error="fail" -> None (آپلود نشود)
    """
    c = dict(DEFAULT_CFG)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    text = str(c.get("text") or "").strip()

    ff = ffmpeg_path()
    if not ff or not text:
        print(f"[wm] رد شد (ffmpeg={'دارد' if ff else 'ندارد'}, text={'دارد' if text else 'خالی'})")
        return None if c.get("on_error") == "fail" else src

    vw, vh = probe_size(src)
    pill = build_pill(text, vh, float(c.get("opacity", 0.88)),
                      float(c.get("font_pct", 2.2)))
    pw, ph = pill.size
    x, y = position_xy(str(c.get("position", "top")), vw, vh, pw, ph,
                       float(c.get("margin_pct", 5.0)))

    tmpdir = tempfile.mkdtemp(prefix="wm_")
    pill_path = os.path.join(tmpdir, "pill.png")
    pill.save(pill_path, "PNG")

    if not out_path:
        out_path = str(Path(src).with_name(Path(src).stem + "_wm.mp4"))

    # عرض/ارتفاع باید زوج باشد وگرنه yuv420p خطا می‌دهد.
    # fps=30 عمدی است: بیشتر Shortsهای دانلودشده VFR (نرخ فریم متغیر) هستند
    # چون با موبایل ضبط شده‌اند. خروجی VFR گاهی در صف ترنسکد یوتیوب گیر
    # می‌کند و ویدیو ساعت‌ها روی «We're processing this video» می‌ماند.
    # نرمال‌کردن به CFR این ریسک را حذف می‌کند.
    vf = (f"[0:v]fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2[v0];"
          f"[v0][1:v]overlay={x}:{y}:format=auto[vout]")
    cmd = [
        ff, "-y", "-hide_banner", "-loglevel", "error",
        "-i", src, "-i", pill_path,
        "-filter_complex", vf,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", str(c.get("preset", "veryfast")),
        "-crf", str(c.get("crf", 23)), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             errors="replace", timeout=1800)
        ok = res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1024
    except Exception as exc:  # noqa: BLE001
        print(f"[wm] ffmpeg اجرا نشد: {exc}")
        ok = False
        res = None

    if not ok:
        err = (getattr(res, "stderr", "") or "").strip().splitlines()
        print(f"[wm] شکست خورد ({err[-1][:160] if err else 'بدون پیام'})")
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except OSError:
            pass
        return None if c.get("on_error") == "fail" else src

    # فایل اصلی دیگر لازم نیست — خواسته‌ی مالک: چیزی روی سرور نماند.
    if remove_source and os.path.abspath(src) != os.path.abspath(out_path):
        try:
            os.remove(src)
        except OSError:
            pass

    print(f"[wm] مهر زده شد: {Path(out_path).name} ({vw}x{vh}, {pw}x{ph}px)")
    return out_path


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="مهر زدن آدرس کانال روی ویدیو")
    p.add_argument("video")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--text", default=DEFAULT_CFG["text"])
    p.add_argument("--position", default=DEFAULT_CFG["position"])
    p.add_argument("--margin-pct", type=float, default=DEFAULT_CFG["margin_pct"])
    p.add_argument("--font-pct", type=float, default=DEFAULT_CFG["font_pct"])
    p.add_argument("--keep", action="store_true", help="فایل اصلی را پاک نکن")
    a = p.parse_args(argv)
    out = apply(a.video, {
        "text": a.text, "position": a.position,
        "margin_pct": a.margin_pct, "font_pct": a.font_pct,
    }, out_path=a.out, remove_source=not a.keep)
    return 0 if out else 1


if __name__ == "__main__":
    raise SystemExit(main())
