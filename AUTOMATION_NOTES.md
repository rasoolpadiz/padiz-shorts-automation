# راهنمای اتوماسیون شبانه‌روزی کانال پادیز

## چطور کار می‌کند (بدون نیاز به روشن بودن کامپیوتر شما)

```
GitHub Actions (cron: 5 بار در روز)
   └─ .github/workflows/scheduled_shorts.yml
        ├─ نصب ffmpeg + requirements.txt
        ├─ python run_daily.py
        │    ├─ انتخاب موضوع چرخشی از topics_pool.py (بر اساس posted_shorts.json)
        │    ├─ رندر اسلایدها با Pillow + فونت وزیرمتن  (pipeline.create_slide_image)
        │    ├─ صدای گوینده فارسی با Edge-TTS
        │    ├─ ترکیب با ffmpeg (1080x1920)
        │    └─ آپلود در یوتیوب با YouTube Data API v3  (سکرت YOUTUBE_TOKEN_B64)
        └─ کامیت و پوش posted_shorts.json  →  چرخش موضوع‌ها بین اجراها حفظ می‌شود
```

زمان‌های اجرا (UTC → ساعت تهران، UTC+3:30):

| cron (UTC) | ساعت تهران |
|---|---|
| 06:00 | 09:30 |
| 10:00 | 13:30 |
| 14:00 | 17:30 |
| 17:00 | 20:30 |
| 20:00 | 23:30 |

## نکته کلیدی رندر فارسی (باگی که رفع شد)

Pillow در دو محیط متفاوت رفتار می‌کند:

* **روی رانر گیت‌هاب (لینوکس)**: چرخ‌های آماده Pillow شامل `libraqm` هستند
  (`PIL.features.check("raqm") == True`) و خودشان HarfBuzz (چسباندن حروف) و
  FriBidi (چیدمان راست‌به‌چپ) را اجرا می‌کنند.
* **روی ویندوز/نصب محلی**: معمولاً `libraqm` وجود ندارد و بدون پیش‌پردازش،
  متن فارسی جدا و برعکس درمی‌آید.

اگر متن را در هر دو حالت با `arabic_reshaper + python-bidi` آماده کنید، روی رانر
**دو بار** اعمال می‌شود و متن **آینه‌ای** می‌شود (همان باگ ویدیوهای قبلی).

راه‌حل اعمال‌شده در `pipeline.py`:

```python
HAS_RAQM = bool(pil_features.check("raqm"))   # در زمان اجرا تشخیص داده می‌شود

def prepare_bidi_text(text): ...   # فقط وقتی HAS_RAQM == False پیش‌پردازش می‌کند
def draw_persian(draw, xy, text, font, fill, anchor="mm"):  # direction="rtl" روی Raqm
```

## تأیید رندر (بدون مصرف سهمیه یوتیوب)

```powershell
python render_check.py            # اسلایدهای نمونه در ./render_check/
```

یا در ابر: Actions → **Persian Render Check** → Run workflow؛ خروجی هم به‌صورت
آرتیفکت و هم در برنچ `cloud-render-check` منتشر می‌شود (لاگ محیط در
`render_check/cloud_log.txt`).

## مدیریت ویدیوهای کانال

```powershell
python channel_admin.py list 10                # لیست آپلودهای اخیر + وضعیت عمومی/خصوصی
python channel_admin.py unlist <VIDEO_ID>      # خصوصی کردن (برگشت‌پذیر)
python channel_admin.py publish <VIDEO_ID>     # عمومی کردن مجدد
python channel_admin.py delete <VIDEO_ID>      # حذف کامل
```

## تنظیمات و محدودیت‌های مهم

| مورد | مقدار / نکته |
|---|---|
| سهمیه YouTube Data API | ۱۰٬۰۰۰ واحد در روز؛ هر آپلود ۱٬۶۰۰ واحد → ۵ آپلود ≈ ۸٬۰۰۰ واحد |
| فاصله حداقلی بین آپلودها | `MIN_GAP_MINUTES = 90` در `run_daily.py` (ضد تکرار در اجراهای تأخیری/دستی) |
| تعداد موضوع‌های استخر | ۹ موضوع × ۳ اسلاید؛ با ۵ آپلود در روز هر ~۲ روز تکرار می‌شود |
| دقایق Actions | مخزن خصوصی: هر اجرا ~۴ دقیقه؛ ۵ اجرا در روز ≈ ۲۰ دقیقه (سقف رایگان ۲۰۰۰ دقیقه در ماه) |
| کرون گیت‌هاب | همیشه دقیق نیست؛ تأخیر ۲۰ دقیقه تا چند ساعت و در موارد نادر اجرا نشدن گزارش شده است |

## اگر انتشار خودکار متوقف شد

1. **چک وضعیت اجراها**: `Actions → Padiz 24/7 Shorts Automation`
2. **خطای `invalid_grant` یا `Token has been expired or revoked`** →
   توکن گوگل منقضی شده. اگر اپ OAuth در حالت **Testing** باشد، refresh token
   بعد از **۷ روز** باطل می‌شود. راه‌حل دائمی: در Google Cloud Console →
   OAuth consent screen وضعیت را به **In production** تغییر دهید؛ سپس یک‌بار
   توکن را محلی بسازید و سکرت `YOUTUBE_TOKEN_B64` را به‌روز کنید:
   ```powershell
   python auth_test.py            # ساخت مجدد token.pickle
   # سپس مقدار جدید را در GitHub → Settings → Secrets → YOUTUBE_TOKEN_B64 ثبت کنید
   ```
3. **خطای سهمیه (`quotaExceeded`)** → سهمیه ۱۰٬۰۰۰ واحدی روز تمام شده؛ فردا خودکار درست می‌شود.
4. **اجرا نشدن کرون** → تأخیر طبیعی است. برای زمان‌بندی دقیق می‌توانید از یک
   سرویس cron خارجی (مثل cron-job.org) استفاده کنید که این endpoint را با یک
   Personal Access Token با دسترسی `actions: write` صدا بزند:
   `POST https://api.github.com/repos/rasoolpadiz/padiz-shorts-automation/actions/workflows/scheduled_shorts.yml/dispatches`
   با بدنه `{"ref":"main"}`. (توکن را در سرویس ثالث ذخیره کنید، نه در مخزن.)
5. **اطلاع از خطاها**: Settings آکانت گیت‌هاب → Notifications → Actions را فعال کنید
   تا ایمیل خطای اجرای زمان‌بندی‌شده دریافت کنید.

## افزودن موضوع جدید

در `topics_pool.py` یک آبجکت با این ساختار اضافه کنید (فقط `id` نباید تکراری باشد):

```python
{
    "id": "unique_id_01",
    "category": "دسته‌بندی",
    "title": "عنوان ویدیو #shorts",
    "description": "متن توضیحات ...",
    "tags": ["shorts", "..."],
    "slides": [
        {"title": "عنوان اسلاید", "text": "متن روی اسلاید", "speech": "متنی که گوینده می‌خواند"},
        # ۳ اسلاید برای هر موضوع
    ],
}
```
