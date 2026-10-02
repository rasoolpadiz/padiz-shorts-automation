# 🔴 فیکس فوری: توکن یوتیوب منقضی شده

## چی شد؟
امروز (۲۰۲۶-۱۰-۰۲) هیچ ویدیویی آپلود نشد. علت دقیق از لاگ گیت‌هاب:

```
google.auth.exceptions.RefreshError:
('invalid_grant: Token has been expired or revoked.')
```

یعنی **توکن یوتیوب باطل شده**، نه اینکه کد خراب باشه. کرون سر وقت اجرا شد، ویدیو هم رندر شد،
فقط لحظهٔ آپلود یوتیوب اجازه نداد.

## چرا این اتفاق افتاد؟
اپ OAuth تو در Google Cloud روی حالت **Testing** بوده.
گوگل refresh token اپ‌های Testing را **بعد از ۷ روز** باطل می‌کند.
تو credentials را حدود ۲۵ سپتامبر ساختی → ۲ اکتبر = دقیقاً ۷ روز. منطبق است.

---

# ✅ راه‌حل: ۳ مرحله، حدود ۲ دقیقه

## مرحله ۱ (فقط یک‌بار برای همیشه) — اپ را Publish کن
این کار جلوی ۷ روز بعد دوباره باطل شدن را می‌گیرد:

**همین لینک را باز کن:**
```
https://console.cloud.google.com/apis/credentials/consent?project=padiz-446920
```
- اگر گفت وارد شو → با همون اکانت کانال پادیز وارد شو
- بالای صفحه `Publishing status: Testing` را می‌بینی
- دکمهٔ **PUBLISH APP** را بزن → Confirm
- (اگر گفت verification لازم است، رد کن / Skip — برای استفادهٔ خودت لازم نیست،
  فقط موقع ورود یک صفحهٔ «unverified» نشان می‌دهد که با Advanced → Go ادامه می‌دهی)

## مرحله ۲ — توکن جدید بساز
در PowerShell:
```powershell
cd C:\youtube_pipeline
python refresh_youtube_token.py
```
- مرورگر باز می‌شود
- با **همون اکانت کانال پادیز** وارد شو
- اگر صفحهٔ «Google hasn't verified this app» آمد: **Advanced → Go to ... (unsafe)**
- **Allow** را بزن
- آخرش باید ببینی:
  ```
  ✅ توکن ساخته شد و تست شد | کانال: <اسم کانال>
  ```

## مرحله ۳ — سکرت گیت‌هاب را آپدیت کن
**راه الف (خودکار، اگر PAT داری):**
```powershell
python refresh_youtube_token.py --pat <GITHUB_PAT>
```

**راه ب (دستی، همیشه کار می‌کند):**
1. فایل `C:\youtube_pipeline\YOUTUBE_TOKEN_B64.txt` را باز کن و **کل محتوا** را کپی کن
2. برو به:
   ```
   https://github.com/rasoolpadiz/padiz-shorts-automation/settings/secrets/actions
   ```
3. روی `YOUTUBE_TOKEN_B64` → **Update**
4. محتوای کپی‌شده را paste کن → **Update secret**

---

## مرحله ۴ — تست
```powershell
cd C:\youtube_pipeline
python run_daily.py
```
اگر ویدیو آپلود شد → تمام. اگر نه، خروجی را برای من بفرست.

---

## چک سریع سلامت توکن (هر وقت خواستی)
```powershell
cd C:\youtube_pipeline
python verify_setup.py
```
خط `توکن یوتیوب سالم و refresh می‌شود` باید **PASS** باشد.