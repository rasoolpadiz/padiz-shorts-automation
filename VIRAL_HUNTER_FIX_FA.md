# رفع باگ «پیدا کردن ویدیو و آپلودش» (Viral Hunter) — ۲۸ سپتامبر ۲۰۲۶

## خلاصهٔ مشکل

بخش تولید ویدیو (استخر فکت‌ها) درست کار می‌کرد و ویدیوها روی کانال می‌رفتند،
اما بخش **Global Viral Hunter** (پیدا کردن ویدیوی ترند جهانی و آپلودش) هرگز
یک بار هم موفق نشد. هیچ ویدیوی ویرالی روی کانال نیست و فایل `processed_reels.json`
در مخزن ساخته نشده است (این فایل فقط بعد از یک آپلود موفق نوشته می‌شود).

## ریشهٔ مشکل (با شاهد از لاگ)

لاگ واقعی GitHub Actions (اجراهای `36199343930` و `36259567887`):

```
Scheduled turn for Global Viral Hunter! Scanning viral trends...
Found viral video [psychology_facts]: https://www.youtube.com/watch?v=c1niHqhonFo with 179,252 views!
Downloading video stream...
ERROR: [youtube] c1niHqhonFo: Sign in to confirm you're not a bot.
       Use --cookies-from-browser or --cookies for the authentication.
Viral hunter encountered an issue: ... Falling back to fact pool...
Selected topic: ... (ID: ocean_creatures_01)
SUCCESSFULLY PUBLISHED TO YOUTUBE SHORTS!
```

یعنی به ترتیب:

1. جست‌وجو و انتخاب ویدیو **سالم** است (YouTube Data API آیدی را برمی‌گرداند).
2. **دانلود با yt-dlp شکست می‌خورد**، چون یوتیوب دانلود از IP دیتاسنتر
   (رانرهای GitHub / اکثر VPSها) را با پیام «Sign in to confirm you're not a bot»
   رد می‌کند.
3. کد خطا را بی‌صدا می‌گرفت و به استخر فکت‌ها برمی‌گشت، پس اجرا **سبز** می‌شد و
   تنها چیزی که کاربر می‌دید «رسیدن به مرحلهٔ آپلود» و بعد نبودن هیچ ویدیویی
   روی کانال بود.

نکتهٔ مهم: از IP خانگی (همین ویندوز) همان دانلود **موفق** است؛ مشکل مخصوص
IP سرور است.

## اصلاحات انجام‌شده در کد

| فایل | تغییر |
|---|---|
| `viral_hunter.py` | `download_video` حالا کوکی را پشتیبانی می‌کند و ۵ بار با کلاینت‌های مختلف yt-dlp (`default`, `android+web_safari`, `tv`, `ios`, `mweb`) تلاش می‌کند؛ اگر همه رد شوند `ViralDownloadBlocked` با پیام راهنما بالا می‌رود. |
| `viral_hunter.py` | `apply_padiz_branding` به‌جای `scale2ref` (که ویدیوی ۱۶:۹ را افقی می‌گذاشت و یوتیوب آن را Short نمی‌دانست) حالا هر ورودی را به **۱۰۸۰×۱۹۲۰ عمودی** با `scale + crop + setsar` و صدای AAC استاندارد تبدیل می‌کند و طول را زیر ۱۷۸ ثانیه نگه می‌دارد. |
| `viral_hunter.py` | آپلود درصد پیشرفت را چاپ می‌کند و بعد از آپلود با `videos().list` وضعیت واقعی (`privacyStatus`, `uploadStatus`, `rejectionReason`, `regionRestriction`) را گزارش می‌دهد. |
| `viral_hunter.py` | خطاها حالا **پرسروصدا** هستند (`!!! VIRAL HUNTER FAILED !!!`) و در `viral_last_error.log` هم ذخیره می‌شوند. |
| `viral_hunter.py` | CLI تازه: `--once`, `--dry-run`, `--url`, `--list-niches`؛ متغیرهای محیطی `VIRAL_MIN_VIEWS`, `VIRAL_LICENSE`, `KEEP_VIRAL_FILES`. |
| `run_daily.py` | وقتی دانلود بلاک شود، پیام روشن با راه‌حل چاپ می‌شود (قبلاً یک خط لاگ ساده بود). |
| `.github/workflows/scheduled_shorts.yml` | انتقال سکرت `YT_COOKIES_B64` به محیط اجرا. |
| `make_cookies.py` | ابزار ساخت `yt_cookies.txt` از مرورگر یا فایل افزونه + چاپ مقدار base64 + ثبت خودکار سکرت با `--pat`. |
| `viral_debug.py` | عیب‌یابی فقط-خواندنی: سلامت توکن، وضعیت واقعی آخرین آپلودها، تست جست‌وجو و دانلود. |
| `check_actions.py` | خواندن لاگ واقعی اجراهای Actions و نشان دادن خطاهای مهم. |



## راه‌اندازی (یکی از دو مسیر)

### مسیر A — اجرا روی سرور خودتان (توصیه‌شده، بدون بلاک IP)

روی سرور/PC (با پایتون ۳.۱۱+ و ffmpeg نصب‌شده):

```bash
pip install -r requirements.txt
python viral_hunter.py --dry-run      # فقط پیدا کردن + دانلود + برندینگ (بدون آپلود)
python viral_hunter.py --once         # پیدا کردن + دانلود + برندینگ + آپلود
python viral_hunter.py --url "https://www.youtube.com/watch?v=XXXX"   # تست یک ویدیوی مشخص
```

اگر سرور شما IP دیتاسنتر دارد و همان خطای «not a bot» را داد، بخش B را هم انجام
دهید (کوکی). نکته‌های مهم اجرای سرور:

* توکن یوتیوب و `client_secret.json` باید روی سرور باشند (`python auth_test.py`
  برای ساخت توکن تازه).
* سهمیهٔ API: هر روز حداکثر ۱۰٬۰۰۰ واحد؛ هر آپلود ۱٬۶۰۰ و هر جست‌وجوی نیچ ~۱۰۰
  واحد. یعنی روزی ۵ آپلود امن است؛ بیشتر از آن خطای `quotaExceeded` می‌دهد.
* زمان‌بندی با cron (مثال: ۳ بار در روز):
  ```bash
  30 6,13,18 * * * cd /path/to/youtube_pipeline && /usr/bin/python3 viral_hunter.py --once >> viral_cron.log 2>&1
  ```

### مسیر B — اضافه کردن کوکی (برای GitHub Actions یا VPS دیتاسنتر)

۱. یک اکانت یوتیوب فرعی بسازید (اکانت اصلی را برای این کار استفاده نکنید).
۲. با افزونهٔ «Get cookies.txt LOCALLY» در حالت Incognito وارد `youtube.com`
   شوید و `cookies.txt` بگیرید — یا خودکار:

```powershell
python make_cookies.py --from-file cookies.txt      # از فایل افزونه
python make_cookies.py --browser chrome             # خواندن مستقیم از مرورگر (مرورگر بسته باشد)
python make_cookies.py --from-file cookies.txt --pat <GITHUB_PAT>   # ثبت خودکار سکرت
```

۳. مقدار base64 چاپ‌شده را در GitHub → Settings → Secrets and variables → Actions
   با نام **`YT_COOKIES_B64`** ثبت کنید (یا با `--pat` خودکار ثبت می‌شود).
۴. اجرای بعدی workflow کوکی را رمزگشایی می‌کند و دانلود از IP رانر هم کار می‌کند.
   کوکی‌ها معمولاً بعد از چند هفته منقضی می‌شوند؛ در صورت بلاک شدن دوباره همین
   مراحل را تکرار کنید (لاگ خطا خودش یادآوری می‌کند).

## تست و عیب‌یابی

```powershell
python viral_debug.py                # توکن + کانال + وضعیت واقعی آخرین آپلودها
python viral_debug.py --download     # جست‌وجوی نیچ + تست دانلود
python check_actions.py              # لیست اجراهای Actions
python check_actions.py --run <ID>   # خطاهای مهم همان اجرا
python viral_hunter.py --list-niches # فهرست نیچ‌ها
```

## هشدار مهم (قانونی/سیاست یوتیوب)

آپلود عین-به-عین ویدیوی دیگران در یوتیوب «Reused content» حساب می‌شود و دیر یا
زود یکی از این‌ها رخ می‌دهد: ادعای کپی‌رایت (`Content ID`)، مسدود شدن ویدیو یا
حتی ضربه/strike و بسته شدن کانال. سه راه امن‌تر:

1. **تغییر معنادار (Transformative)**: ویدیو فقط پس‌زمینه باشد و روی آن گویندگی
   فارسی، متن/زیرنویس و موسیقی خودتان اضافه شود (مثل `build_aesthetic_narrated.py`).
2. **اجازهٔ بازاستفاده**: با `VIRAL_LICENSE=creativeCommon` فقط ویدیوهای دارای
   لایسنس کریتیو کامنز انتخاب می‌شوند (در توضیحات به منبع اشاره کنید).
3. استفاده از ویدیوی خودتان (تولید با AI) به‌عنوان تصویر پس‌زمینه و صدای خودتان.

## اگر دوباره متوقف شد

| نشانه | معنا | راه‌حل |
|---|---|---|
| `Sign in to confirm you're not a bot` | بلاک IP | کوکی (مسیر B) یا اجرا روی IP خانگی/سرور (مسیر A) |
| `quotaExceeded` | سهمیهٔ روز تمام شده | فردا خودکار درست می‌شود؛ تعداد آپلود روز را کم کنید |
| آپلود موفق ولی ویدیو دیده نمی‌شود | ادعای کپی‌رایت / مسدودسازی | `uploadStatus`/`regionRestriction` در لاگ را ببینید و محتوا را تغییر دهید |
| `No eligible viral candidate` | هیچ ویدیوی تازه‌ای بالای ۱۰۰ هزار بازدید نبود | `VIRAL_MIN_VIEWS` را کم کنید |
