# -*- coding: utf-8 -*-
"""آزمایش کلید Google AI Studio (Gemini) برای گویندگی فارسی.

Usage:
    python gemini_key_check.py                 # کلید از متغیر محیطی GEMINI_API_KEY
    python gemini_key_check.py <API_KEY>       # یا کلید را مستقیم بدهید

برای هر مدل در pipeline.GEMINI_TTS_MODELS یک درخواست کوتاه می‌فرستد و می‌گوید
کدام مدل با کلید شما کار می‌کند، طول فایل صوتی چقدر شد، یا خطای دقیق چیست.
اگر همهٔ مدل‌ها خطا دادند، متن خطا معمولاً می‌گوید مشکل «صورتحساب/صورت‌حساب
فعال‌نشده» است یا «کلید نامعتبر».

نکته: مدل‌های *Flash* TTS در پلن رایگان رایگان هستند؛ مدل Pro TTS فقط با
صورت‌حساب فعال کار می‌کند و در انتهای فهرست امتحان می‌شود.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Windows consoles default to cp1252 and would crash on Persian output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import pipeline

SAMPLE_TEXT = "سلام! این یک آزمایش کوتاه برای بررسی کیفیت صدای فارسی است."
VOICE = os.environ.get("GEMINI_TTS_VOICE", "").strip() or "Puck"


def main():
    api_key = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GEMINI_API_KEY", "")).strip()
    if not api_key:
        print("کلید پیدا نشد. استفاده: python gemini_key_check.py <API_KEY>")
        print("یا اول متغیر محیطی را ست کنید:  $env:GEMINI_API_KEY=\"...\"")
        return 2

    if not pipeline.HAS_GENAI:
        print("کتابخانهٔ google-genai نصب نیست:  pip install google-genai")
        return 2

    print(f"مدل‌ها به ترتیب اولویت: {[m for m in pipeline.GEMINI_TTS_MODELS if m]}")
    print(f"صدا: {VOICE}   متن آزمایش: {SAMPLE_TEXT[:30]}...")
    print("-" * 70)

    client = pipeline.genai.Client(api_key=api_key)
    working = []
    out_path = os.path.join(BASE_DIR, "gemini_key_check.mp3")

    for model_name in [m for m in pipeline.GEMINI_TTS_MODELS if m]:
        speech_config = pipeline.gemini_speech_config(model_name, VOICE)
        config = pipeline.genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
        )
        try:
            response = client.models.generate_content(
                model=model_name, contents=SAMPLE_TEXT, config=config,
            )
        except Exception as e:
            print(f"  ✗ {model_name}: {str(e)[:200]}")
            continue

        raw = None
        for candidate in (response.candidates or []):
            if not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    raw = inline.data
                    break
            if raw:
                break

        if not raw:
            print(f"  ~ {model_name}: پاسخ آمد ولی صدایی نداشت")
            continue

        if pipeline._gemini_audio_to_mp3(raw, out_path):
            print(f"  ✓ {model_name}: {os.path.getsize(out_path)} بایت، "
                  f"{pipeline.get_audio_duration(out_path):.2f} ثانیه -> {out_path}")
            working.append(model_name)
        else:
            print(f"  ~ {model_name}: صدا آمد ولی ffmpeg تبدیل نکرد")

    print("-" * 70)
    if working:
        print(f"نتیجه: کلید شما کار می‌کند. بهترین مدل پاسخ‌دهنده: {working[0]}")
        print(f"می‌توانید صدای این نمونه را گوش دهید: {out_path}")
        print("حالا این کلید را در GitHub به‌عنوان سکرت GEMINI_API_KEY ثبت کنید "
              "(python set_github_secret.py <PAT> <API_KEY>).")
        return 0

    print("نتیجه: هیچ مدلی صدا برنگرداند. راه‌های رفع:")
    print("  1) مطمئن شوید کلید از https://aistudio.google.com/apikey گرفته شده است.")
    print("  2) اگر خطا از جنس billing/quota بود، در AI Studio برای پروژه Billing فعال کنید")
    print("     (مدل‌های Flash TTS رایگان‌اند، ولی سهمیهٔ روزانه محدود است).")
    print("  3) علت را از متن خطاهای بالا بخوانید؛ خطای 401/403 = کلید نامعتبر،")
    print("     429 = سهمیه تمام شده (فردا ریست می‌شود)، 400 با نام مدل = مدل روی حساب شما نیست.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
