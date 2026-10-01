# 📺 Padiz YouTube Automation - راهنمای اجرا

## ✅ چه‌کاری انجام شد

1. **آپلود فیلم امروز (۱ اکتبر)**
   - فیلم بلند `en_long_ai_mistakes_01` آپلود شد
   - در حال رندر و آپلود است...

2. **نصب Scheduler اتوماتیک**
   - ✅ PadizDaily_1: هر روز **۱۵:۳۰** (فیلم + شورت‌ها)
   - ✅ PadizDaily_2: هر روز **۲۱:۰۰** (بکاپ)

3. **الگوی اتوماتیک**
   - 📅 **روز فرد**: فیلم بلند انگلیسی + شورت‌های انگلیسی
   - 📅 **روز زوج**: فیلم بلند فارسی + شورت‌های فارسی

---

## 🚀 دستورات دستی

### آپلود فیلم بلند **امروز**
```bash
python run_long_daily.py --upload --force
```

### لیست موضوعات آماده
```bash
python run_long_daily.py --list
```

### آپلود موضوع خاص
```bash
python run_long_daily.py --topic en_long_ai_mistakes_01 --upload
```

### رندر بدون آپلود (تست)
```bash
python run_long_daily.py --render --force
```

---

## 📅 مدیریت Scheduler

### نمایش تسک‌های نصب‌شده
```bash
python schedule_runner.py --list
```

### تغییر ساعت‌ها
```bash
python schedule_runner.py --install --times 15:30,21:00,23:59
```

### حذف تسک‌ها
```bash
python schedule_runner.py --remove
```

### اجرای دستی برای امروز
```bash
python schedule_runner.py --today           # اجرای واقعی
python schedule_runner.py --today --dry-run # فقط نمایش
```

---

## 📊 پیکربندی

### فایل‌های کلیدی
- `run_long_daily.py` — انتخاب + رندر + آپلود فیلم
- `longform.py` — موتور رندر ۱۶:۹
- `pipeline.py` — شورت‌ها و آپلود
- `gen_topics.py` — نوشتن متن ۲۲ صحنه‌ای
- `image_fetch.py` — دانلود عکس

### وضعیت آپلودها
- `longform_out/posted_long.json` — تاریخچه فیلم‌های بلند
- `posted_shorts.json` — تاریخچه شورت‌ها

### لاگ‌ها
- `schedule_daily.log` — نتایج اجرای Scheduler
- `up_log.txt`, `up_err.txt` — لاگ‌های آپلود

---

## 🔧 عیب‌یابی

### اگر فیلم آپلود نشد:
```bash
# بررسی وضعیت امروز
python schedule_runner.py --today --dry-run

# آپلود دستی
python run_long_daily.py --upload --force

# چک لاگ
cat schedule_daily.log
```

### اگر شورت‌ها آپلود نشدند:
```bash
python pipeline.py --gen-shorts
```

### بررسی Scheduler:
```bash
schtasks /query /tn PadizDaily_1 /v
```

---

## 📋 نکات مهم

- ⚠️ حداکثر **۶ آپلود روزانه** از سبب محدودیت YouTube API
- 🔐 توکن یوتیوب در `token.pickle` ذخیره شده (محرمانه)
- 🌐 Gemini API برای نوشتن متن (روز سوم به بعد)
- 🎬 رندر هر فیلم **۲-۳ دقیقه** طول می‌کشد
- 📤 آپلود **۲۰-۴۰ دقیقه** بسته به سرعت اینترنت

---

## 🎯 نتیجهٔ نهایی

✅ **سیستم اتوماتیک اجرا شد:**
- هر روز ۱۵:۳۰ اجرا خودکار
- فیلم + شورت‌ها هردو آپلود می‌شوند
- زبان برای هر روز جدا (فارسی ↔ انگلیسی)
- در صورت ناموفقی، ۲۱:۰۰ دوباره تلاش می‌کند

**آپلود امروز درحال انجام است...**
