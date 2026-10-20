# راهنمای پروژه‌ی ادغام‌شده (Padiz + shortsdl)

تاریخ ادغام: ۲۰۲۶-۱۰-۲۰

## چه شد؟

دو پروژه‌ی جدا بود:

| پروژه | کار | مسیر قبلی |
|---|---|---|
| `youtube_pipeline` | ساخت شورت فارسی + آپلود روی کانال با توکن OAuth | `C:\youtube_pipeline` (و `/opt/padiz/repo` روی سرور) |
| `yyy` (shortsdl) | کشف و دانلود Shorts پربازدید از یوتیوب | `C:\Users\Allah\Desktop\yyy` |

حالا **پروژه‌ی دوم داخل پروژه‌ی اول ادغام شده** و همه‌چیز از یک ریپو و یک کرون
اجرا می‌شود. پروژه‌ی دوم حذف نشده؛ کدش دست‌نخورده داخل `shortsdl/` است.

```
C:\youtube_pipeline\
├── shortsdl/                 ← کد پروژه‌ی دوم (کشف + دانلود)
├── shortsdl_config.json      ← تنظیمات بازارها و سقف روزانه‌ی ریپاست
├── repost.py                 ← 🆕 کشف → دانلود → آپلود روی کانال
├── run_all_daily.py          ← 🆕 تنها نقطه‌ی ورود روزانه
├── run_daily.py              ← شورت فارسی ساخته‌شده (بدون تغییر)
├── schedule_runner.py        ← زمان‌بند ویندوز (حالا ریپاست را هم اجرا می‌کند)
├── yt_budget.py              ← بودجه‌ی API (حالا ریپاست را هم می‌شمارد)
├── repost_posted.json        ← 🆕 ثبت ویدیوهای منتشرشده (ضد تکرار)
├── repost_out/               ← 🆕 فایل‌های دانلودشده + لاگ (بعد از آپلود پاک می‌شوند)
└── deploy/run_all.sh         ← 🆕 کرون سرور: ریپاست + شورت با هم
```

## چطور کار می‌کند؟

هر اجرا:

1. **ریپاست** — `shortsdl` پربازدیدترین Shorts را از بازارهای تنظیم‌شده پیدا می‌کند،
   آن‌هایی که قبلاً منتشر شده‌اند را رد می‌کند، ۲ ویدیوی بعدی را دانلود می‌کند و با
   همان توکن کانال آپلود می‌کند. بعد از آپلود موفق فایل پاک می‌شود.
2. **شورت فارسی** — همان مسیر قبلی `run_daily.py` (رندر + TTS + آپلود).

### سقف‌ها (مهم)

| محدودیت | مقدار | دلیل |
|---|---|---|
| آپلود ریپاست در روز | ۲ | خواسته‌ی شما |
| شورت ساخته‌شده در روز | ۳ | `MAX_SHORTS_PER_DAY` |
| سقف کل آپلود روز | ۵ | ۵ × ۱۶۰۰ = ۸۰۰۰ از ۱۰۰۰۰ واحد API |

هر آپلود ۱۶۰۰ واحد از سهمیه‌ی روزانه‌ی YouTube API می‌خورد. با ۵ آپلود، ۲۰۰۰ واحد
برای جست‌وجو و retry باقی می‌ماند. اگر ۶ آپلود کنیم، یک retry کل روز را می‌سوزاند.

## اجرای دستی (تست)

```powershell
cd C:\youtube_pipeline

python repost.py --dry-run              # فقط ببین چه ویدیوهایی پیدا می‌شود
python repost.py --count 1 --no-upload  # دانلود کن، آپلود نکن
python repost.py                        # ۲ ویدیو: دانلود + آپلود
python run_all_daily.py                 # کل روز: ریپاست + شورت
python run_all_daily.py --only repost   # فقط ریپاست
python schedule_runner.py --today       # همان چیزی که کرون اجرا می‌کند
```

## نصب روی سرور (یک‌بار)

```bash
cd /opt/padiz/repo
/opt/padiz/venv/bin/pip install -r requirements.txt   # imageio-ffmpeg اضافه شده
/opt/padiz/venv/bin/python repost.py --dry-run         # تست کشف
```

### کرون

ورودی قدیمی (`deploy/run_short.sh`) را با `deploy/run_all.sh` عوض کنید تا شورت
دو بار آپلود نشود:

```cron
# قبل (فقط شورت ساخته‌شده)
30 12 * * *  bash /opt/padiz/repo/deploy/run_short.sh

# بعد (ریپاست + شورت، با هم)
30 12 * * *  bash /opt/padiz/repo/deploy/run_all.sh
0  17 * * *  bash /opt/padiz/repo/deploy/run_all.sh
```

`run_all.sh` خودش `deploy/pull.sh` را صدا می‌زند، پس کد از گیت‌هاب به‌روز می‌شود؛
`flock` هم جلوی اجرای هم‌زمان را می‌گیرد.

### وضعیت

```bash
bash /opt/padiz/repo/deploy/status.sh
```

حالا تعداد ریپاست‌های امروز و حجم `repost_out` را هم نشان می‌دهد.

## تنظیمات

`shortsdl_config.json` → بخش `repost`:

```json
"repost": {
  "per_day": 2,                          // تعداد ویدیو در روز
  "markets": ["trending", "global"],     // یا "persian"
  "privacy_status": "public",            // public / unlisted / private
  "category_id": "24",                   // 24 = Entertainment
  "keep_files": false                    // true = فایل‌ها را نگه دار (دیسک پر می‌شود)
}
```

بازارها: `trending` (ترند این هفته)، `global` (پربازدید جهانی)، `persian` (فارسی).

## ⚠️ دو نکته‌ی مهم

**۱) توکن یوتیوب الان مرده است.** آخرین بررسی (`token_health.json`):

```
invalid_grant: Token has been expired or revoked
```

تا وقتی این درست نشود، هیچ آپلودی — نه ریپاست نه شورت — انجام نمی‌شود. ریپاست
عمداً قبل از دانلود توکن را چک می‌کند تا پهنای باند هدر نرود.

```powershell
cd C:\youtube_pipeline
python refresh_youtube_token.py
```

راهنمای کامل: `FIX_TOKEN_FA.md`

**۲) کپی‌رایت.** ویدیوهایی که این ماژول پیدا می‌کند مال کانال‌های دیگرند. آپلود
مجدد آن‌ها می‌تواند Claim یا Strike کپی‌رایت بگیرد و کانال را از کار بیندازد.
برای همین در توضیحات هر ویدیو، نام کانال اصلی و لینک منبع به‌صورت خودکار درج
می‌شود (اعتباردهی) — ولی این جایگزین اجازه‌ی ناشر نیست. اگر کانال برایت مهم است،
پیشنهاد می‌کنم `privacy_status` را روی `unlisted` بگذاری یا فقط از بازار
`persian` با کانال‌های کوچک‌تر استفاده کنی.
