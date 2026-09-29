# راهنمای اتوماسیون شبانه‌روزی کانال پادیز

## چطور کار می‌کند (بدون نیاز به روشن بودن کامپیوتر شما)

```
GitHub Actions (cron: 5 بار در روز)
   └─ .github/workflows/scheduled_shorts.yml
        ├─ نصب ffmpeg + requirements.txt
        ├─ python run_daily.py
        │    ├─ انتخاب موضوع چرخشی از topics_pool.py (بر اساس posted_shorts.json)
        │    ├─ رندر اسلایدها با Pillow + فونت وزیرمتن  (pipeline.create_slide_image)
        │    ├─ صدای طبیعی گوینده فارسی با Google AI Studio (Gemini)
        │    │    └─ فالبک خودکار: Edge-TTS  (اگر کلید/مدل در دسترس نباشد)
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

## صدای طبیعی فارسی (Google AI Studio / Gemini)

گویندگی ویدیوها اول با مدل‌های صوتی Gemini (Google AI Studio) ساخته می‌شود و اگر
در دسترس نباشد، به‌صورت خودکار روی Edge-TTS برمی‌گردد؛ یعنی انتشار ویدیو هرگز
به دلیل مشکل صداسازی متوقف نمی‌شود.

```python
# pipeline.py
generate_voice(text, edge_voice, out_mp3)          # نقطهٔ ورود اصلی (استفاده شده در build_full_short)
  ├─ generate_voice_gemini(...)                     # اول: صدای طبیعی Gemini
  │    └─ خروجی WAV/PCM → تبدیل با ffmpeg به MP3 استاندارد (192k)
  └─ generate_voice_edge(...)                       # فالبک: Edge-TTS
```

**تنظیمات لازم در GitHub**: Settings → Secrets and variables → Actions →
`GEMINI_API_KEY` (کلید رایگان از [aistudio.google.com](https://aistudio.google.com/apikey)).
این سکرت در `scheduled_shorts.yml` به‌عنوان متغیر محیطی به اجرا پاس داده می‌شود.
بدون این سکرت، همه‌چیز مثل قبل با Edge-TTS کار می‌کند.

| متغیر محیطی | کاربرد |
|---|---|
| `GEMINI_API_KEY` | کلید Google AI Studio (بدون آن، فقط Edge-TTS) |
| `GEMINI_TTS_MODEL` | اجبار به یک مدل خاص (مثلاً `gemini-2.5-flash-preview-tts`) |
| `GEMINI_TTS_VOICE` | اجبار به یک صدای خاص (مثلاً `Puck` یا `Kore`) |
| `DISABLE_GEMINI_VOICE=1` | خاموش کردن کامل Gemini و استفادهٔ همیشگی از Edge-TTS |

ابزارها:

```powershell
python gemini_key_check.py AIzaSy...              # تست کلید: کدام مدل کار می‌کند و کیفیت صدا
python set_github_secret.py <GITHUB_PAT> AIzaSy...  # ثبت خودکار سکرت GEMINI_API_KEY
python voice_check.py                             # تست آفلاین کل مسیر صدا (بدون کلید)
```

نکات پیاده‌سازی:

* مدل‌ها به این ترتیب امتحان می‌شوند (اولین پاسخ برنده است):
  `gemini-3.8-flash-tts` → `gemini-3.8-flash-lite-tts` →
  `gemini-2.5-flash-preview-tts` → `gemini-2.0-flash` → `gemini-2.5-flash` →
  `gemini-2.5-pro-preview-tts`. سه مدل اول TTS اختصاصی و در پلن رایگان رایگان‌اند؛
  مدل Pro فقط با Billing فعال کار می‌کند و آخر صف است.
* متن دقیقاً همان‌طور که هست فرستاده می‌شود (بدون جمله‌ای مثل «این را بخوان»)
  چون مدل TTS هر متنی که بگیرد را می‌خواند؛ لحن با `speech_metadata.style`
  کنترل می‌شود. اگر مدل/نسخهٔ SDK این فیلد را نپذیرد، همان متن به‌شکل ساده دوباره
  فرستاده می‌شود.
* نگاشت صدا: `fa-IR-FaridNeural → Puck` (مرد) و `fa-IR-DilaraNeural → Kore` (زن).
* اگر همهٔ مدل‌ها شکست بخورند یا کلید نامعتبر باشد، Gemini برای بقیهٔ همان اجرا
  خاموش می‌شود تا وقت و درخواست تلف نشود (هر اجرا حداکثر یک دور تلاش).
* توجه: اگر Gemini اسلاید اول را بسازد ولی برای اسلایدهای بعدی خطا بدهد،
  اسلایدهای باقی‌مانده با Edge-TTS خوانده می‌شوند (صدای ویدیو یکدست نمی‌ماند).
  برای ویدیوی یکدست، یا سکرت `GEMINI_API_KEY` را معتبر نگه دارید یا با
  `DISABLE_GEMINI_VOICE=1` کاملاً روی Edge-TTS بمانید.

## گرفتن کلید رایگان Google AI Studio (گام‌به‌گام)

۱. با همان اکانت گوگل خودتان (همان که کانال یوتیوب با آن ساخته شده) وارد
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey) شوید.
۲. شرایط استفاده (Terms) را بپذیرید. اگر قبلاً نپذیرفته‌اید، صفحه یک دکمهٔ
   Accept نشان می‌دهد.
۳. روی **Create API key** بزنید. اگر گزینهٔ انتخاب پروژه آمد،
   **Create API key in new project** را بزنید (ساده‌ترین حالت).
۴. کلیدی مثل `AIzaSy...` ساخته می‌شود؛ روی **Copy** بزنید و آن را در جای امن
   نگه دارید (بعداً کامل نمایش داده نمی‌شود، ولی می‌توانید کلید جدید بسازید).
۵. کلید را همین‌جا روی کامپیوتر تست کنید:
   ```powershell
   cd C:\youtube_pipeline
   python gemini_key_check.py AIzaSy...        # نام مدل‌ها و خطاها را نشان می‌دهد
   ```
   اگر یکی از مدل‌ها ✓ گرفت، فایل `gemini_key_check.mp3` ساخته می‌شود؛ آن را
   گوش کنید تا کیفیت صدای فارسی را بشنوید.
۶. کلید را در گیت‌هاب به‌عنوان سکرت ثبت کنید — یا از طریق سایت:
   `repo → Settings → Secrets and variables → Actions → New repository secret`
   با نام دقیق **`GEMINI_API_KEY`** و مقدار کلید؛ یا با اسکریپت آماده:
   ```powershell
   python set_github_secret.py <GITHUB_PAT> AIzaSy...
   ```
   (توکن گیت‌هاب باید دسترسی `Secrets: read and write` داشته باشد.)
۷. تمام. اجرای بعدی ورکفلو خودکار با صدای Gemini منتشر می‌کند. برای تست فوری:
   `Actions → Padiz 24/7 Shorts Automation → Run workflow`.

### پلن رایگان چه چیزی را پوشش می‌دهد؟

بر اساس صفحهٔ قیمت‌گذاری گوگل (ai.google.dev/gemini-api/docs/pricing):

| مدل | پلن رایگان | پلن پولی (هر ۱ میلیون توکن صوتی) |
|---|---|---|
| `gemini-3.8-flash-tts` | ✅ Free of charge | حدود $9 (معادل ~$0.00225 برای هر ۱۰ ثانیه صدا) |
| `gemini-3.8-flash-lite-tts` | ✅ Free of charge | حدود $6 |
| `gemini-2.5-flash-preview-tts` | ✅ Free of charge | $10 |
| `gemini-2.5-pro-preview-tts` | ❌ فقط پولی | $20 |

* برای همین کار ما (روزی ۵ ویدیو، هر کدام ~۱۵ ثانیه گفتار) پلن رایگان کاملاً کافی
  است؛ فقط سهمیهٔ روزانه محدود است (مقدار دقیقش را در AI Studio →
  «View your active rate limits» ببینید). هر صدا معادل ۲۵ توکن در هر ثانیه است.
* در پلن رایگان، محتوای شما «برای بهبود محصولات گوگل» استفاده می‌شود (مثل
  Edge-TTS که رایگان است). اگر این برایتان مهم است، یا Billing را فعال کنید
  (هزینهٔ ماهانه در این حجم ناچیز است) یا با `DISABLE_GEMINI_VOICE=1` روی
  Edge-TTS بمانید.
* اگر کلید اشتباه/بدون دسترسی باشد، خطا در لاگ چاپ می‌شود و ویدیو با Edge-TTS
  ساخته می‌شود؛ پس انتشار هرگز متوقف نمی‌شود.

## تأیید رندر (بدون مصرف سهمیه یوتیوب)

```powershell
python render_check.py            # اسلایدهای نمونه در ./render_check/
python voice_check.py             # تست آفلاین صدا (Gemini + فالبک Edge-TTS) در ./voice_check/
```

`voice_check.py` بدون نیاز به کلید و بدون مصرف سهمیه، کل مسیر صدا را چک می‌کند:
نگاشت صداها، تبدیل WAV/PCM مدل به MP3، فرستادن لحن (`speech_metadata`)،
کار کردن فالبک Edge-TTS، و خاموش شدن خودکار Gemini بعد از خطای کلید.

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
4. **اجرا نشدن کرون گیت‌هاب** → این یک مشکل شناخته‌شده در مخزن‌های خصوصی است
   (تأخیر ۳۰ دقیقه تا چند ساعت، و در مواردی هیچ‌وقت اجرا نشدن). فایل آماده
   `apps_script/trigger.gs` را در
   [script.google.com](https://script.google.com) باز کنید: زمان‌بند گوگل (رایگان و دقیق)
   هر روز ساعت‌های ۰۹:۳۰/۱۳:۳۰/۱۷:۳۰/۲۰:۳۰/۲۳:۳۰ تهران این workflow را دیسپچ می‌کند.
   برای این کار فقط یک Personal Access Token با دسترسی `Actions: read and write`
   لازم است که در Script properties با نام `GH_TOKEN` ذخیره می‌شود
   (جزئیات در بالای همان فایل نوشته شده است).
   جایگزین ساده‌تر: در [cron-job.org](https://cron-job.org) با منطقهٔ زمانی تهران، این
   درخواست را با هدر `Authorization: Bearer <توکن>` زمان‌بندی کنید:
   `POST https://api.github.com/repos/rasoolpadiz/padiz-shorts-automation/actions/workflows/scheduled_shorts.yml/dispatches`
   با بدنهٔ JSON: `{"ref":"main"}`
   چون `MIN_GAP_MINUTES = 90` فعال است، اگر کرون گیت‌هاب و زمان‌بند خارجی هر دو
   در یک بازه اجرا شوند، فقط یکی آپلود می‌کند.
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
