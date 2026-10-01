# 📘 راهنمای کامل Padiz YouTube Automation

**نسخه:** ۱.۰ | **تاریخ:** ۱ اکتبر ۲۰۲۶

---

## 🎯 خلاصهٔ سیستم

**سیستم شما یک ربات YouTube است که:**
- ✅ هر روز خودکار بهترین موضوعات را پیدا می‌کند
- ✅ فیلم‌های بلند (16 دقیقه) و شورت‌ها می‌سازد
- ✅ مستقیم YouTube آپلود می‌کند
- ✅ موفق‌تر‌ها را تکرار می‌کند
- ✅ بدون نیاز به تأیید کاربر

---

## ⏰ زمان‌بندی خودکار

### Windows Task Scheduler
```
روزانه:
  15:30 → PadizDaily_1 (اجرای اصلی)
  21:00 → PadizDaily_2 (بکاپ اگر 15:30 fail شد)
```

### الگوی انتشار
```
روز 1، 3، 5، ... (فرد):  English long-form + shorts
روز 2، 4، 6، ... (زوج):  Persian long-form + shorts
```

---

## 🔍 چگونه بهترین موضوعات یافت می‌شوند

### منابع Discovery
```
1. YouTube API search (بهترین ویدیوهای viral)
2. Google News (اخبار جدید)
3. Analytics (موضوع‌های قبلی که نتیجه دادند)
```

### فرآیند انتخاب
```
discover.py → discovery_pool.json
   ↓
سیستم بهترین‌ها را نمره می‌دهد:
  • heat (نمره‌ی رتبه‌بندی)
  • velocity (بازدید/ساعت)
   ↓
gen_topics.py → نیچ‌های تأیید‌شده filter می‌کند
   ↓
موضوع تولید می‌شود (Gemini یا fallback)
```

---

## 📊 Quota Management

### محدودیت‌های free tier YouTube:
```
10,000 واحد API در روز
```

### مصرف روزانه:
```
Upload فیلم بلند:    1,600 units
Upload 10 shorts:     2,000 units
Search discovery:       600 units
─────────────────────────────
کل:                   4,200 units (SAFE!)
```

**نتیجه:** شما می‌توانید ۲ فیلم بلند در روز بسازید!

---

## 🎬 فایل‌های کلیدی

| فایل | نقش |
|------|------|
| `discover.py` | ترند‌یاب روزانه |
| `discovery_pool.json` | موضوعات ترند‌شده |
| `gen_topics.py` | نویسنده‌ی محتوا |
| `run_long_daily.py` | Orchestrator |
| `longform.py` | موتور رندر |
| `pipeline.py` | آپلود YouTube |
| `schedule_runner.py` | Windows Scheduler |
| `topics_niches.py` | نیچ‌های تأیید‌شده |
| `posted_long.json` | تاریخچهٔ منتشرشده |

---

## 📈 مدیریت و نظارت

### دستورات مفید

#### ببینید چه چیزهایی ترند است
```bash
python discover.py
python dashboard.py
```

#### لیست موضوعات آماده
```bash
python run_long_daily.py --list
```

#### اجرای دستی (اگر Scheduler fail شد)
```bash
python schedule_runner.py --today
python schedule_runner.py --today --dry-run  # فقط نمایش
```

#### بررسی Scheduler
```bash
python schedule_runner.py --list
schtasks /query /tn PadizDaily_1 /v
```

#### لاگ‌ها
```bash
cat schedule_daily.log
tail -100 schedule_daily.log  # آخر 100 خط
```

---

## 🎯 بهبودی که قابل انجام است

### اختیاری:
1. **نیچ‌های جدید اضافه کنید**
   - فایل: `topics_niches.py`
   - موارد موجود: 85 انگلیسی + 19 فارسی
   - سیستم خودکار آنها را استفاده می‌کند

2. **الگوریتم scoring تغییر دهید**
   - فایل: `discover.py` (تابع `_score`)
   - تغییر وزن‌های velocity, age, engagement

3. **Templates بهبود دهید**
   - فایل: `gen_topics.py` (تابع `_fallback_scene`)
   - ۲۲ صحنه‌ی محتوا را customise کنید

---

## ⚠️ مشکل‌یابی

### اگر فیلم آپلود نشد:
```bash
# بررسی لاگ
tail -50 schedule_daily.log

# تست دستی
python run_long_daily.py --render --force

# اجرای فوری
python run_long_daily.py --upload --force
```

### اگر عکس‌ها دانلود نشدند:
```
مشکل: Openverse overloaded است
حل: صبر کنید یا نیچ را تغییر دهید
```

### اگر صدا خراب بود:
```
مشکل: Gemini TTS unavailable
حل: Fallback to Edge-TTS خودکار
```

### اگر موضوع تکرار شد:
```
مشکل: posted_long.json فسادی دارد
حل: دستی edit کنید یا --force استفاده کنید
```

---

## 🔐 امنیت و توکن‌ها

### GitHub Secrets (تنظیم‌شده):
```
YOUTUBE_TOKEN_B64    ✅ OAuth token
GEMINI_API_KEY       ✅ Gemini access
```

### Local Files (محرمانه):
```
token.pickle         ← YouTube OAuth
client_secret.json   ← OAuth credentials
```

**نکته:** این فایل‌ها بدون .gitignore آپلود نشوند!

---

## 📞 پشتیبانی و سوالات

### سوالات معمول:

**سوال:** چرا فیلمی امروز آپلود نشد؟
**جواب:** `tail -50 schedule_daily.log` را ببینید

**سوال:** آیا می‌تواند بیش از یک فیلم در روز بسازد؟
**جواب:** بله، `LONG_PER_DAY=2` تنظیم کنید

**سوال:** چگونه الگو را تغییر دهم؟
**جواب:** `gen_topics.py` میں `_fallback_scene` تابع عوض کنید

**سوال:** یا quota تمام شد؟
**جواب:** فقط شورت‌ها بسازید (200 units) یا منتظر ساعت 00:00 UTC شوید

---

## ✨ خلاصهٔ نهایی

### آنچه سیستم بدون شما انجام می‌دهد:

- ✅ روزانه ترند‌ها را بررسی می‌کند
- ✅ بهترین موضوعات را انتخاب می‌کند
- ✅ فیلم بلند می‌سازد
- ✅ شورت‌ها می‌سازد  
- ✅ YouTube آپلود می‌کند
- ✅ state update می‌کند
- ✅ یادادگار موفق‌ها می‌شود
- ✅ تکرار را جلوگیری می‌کند

### آنچه شما باید بکنید:

- ⭕ هیچی! سیستم خودکار است
- ⭕ یا گاهی analytics را بررسی کنید
- ⭕ یا هفتگی نیچ‌های جدید اضافه کنید

---

**سیستم شما ۲۴/۷ فعال است!** 🚀

اگر سوالی دارید، `schedule_daily.log` را ببینید یا `schedule_runner.py --today --dry-run` را اجرا کنید.
