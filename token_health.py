#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""سلامت توکن یوتیوب را چک کن (لوکال یا CI) و اگر خراب بود علت را دقیق بگو.

چرا؟ 2026-10-02 توکن باطل شد و ۶ ساعت بعد فهمیدیم. این اسکریپت روزی یک‌بار
قبل از اسلات اول آپلود اجرا می‌شود و اگر refresh کردی خطا داد، در گیت‌هاب
یک Issue خودکار می‌سازد تا همان لحظه خبردار شوی، نه نصف روز بعد.

Usage:
    python token_health.py            # چک فقط (exit 1 = خراب)
    python token_health.py --json     # خروجی JSON برای CI
"""
import base64
import json
import os
import pickle
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")
RESULT_PATH = os.path.join(BASE_DIR, "token_health.json")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def load_credentials():
    """از env (base64) یا token.pickle لوکال - اولی در CI برنده است."""
    env_token = (os.environ.get("YOUTUBE_TOKEN_B64") or "").strip()
    raw = None
    if env_token:
        try:
            raw = base64.b64decode(env_token)
        except Exception:
            raw = None
    if raw is None and os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as fh:
            raw = fh.read()
    if not raw:
        raise RuntimeError("no credentials: YOUTUBE_TOKEN_B64 empty and token.pickle missing")
    return pickle.loads(raw)


def check(creds=None):
    """(ok, channel_name, error) - refresh می‌زند و یک فراخوانی واقعی API می‌کند."""
    try:
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = creds if creds is not None else load_credentials()
        if not creds.refresh_token:
            return False, "", "refresh_token ندارد (دوباره allow کن)"
        creds.refresh(Request())
        yt = build("youtube", "v3", credentials=creds)
        who = yt.channels().list(mine=True, part="snippet").execute()
        items = who.get("items") or []
        name = items[0]["snippet"]["title"] if items else "(بدون کانال)"
        return True, name, ""
    except Exception as e:  # noqa: BLE001 - پیام خطا خودِ خروجی است
        return False, "", f"{type(e).__name__}: {e}"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ok, name, err = check()
    result = {"ok": ok, "channel": name, "error": err}

    try:
        with open(RESULT_PATH, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass

    if "--json" in argv:
        print(json.dumps(result, ensure_ascii=False))
    elif ok:
        print(f"PASS  توکن سالم است | کانال: {name}")
    else:
        print(f"FAIL  توکن خراب است | {err}")
        print("")
        print("راه‌حل (۲ دقیقه):")
        print("  1) اپ را Publish کن:")
        print("     https://console.cloud.google.com/apis/credentials/consent?project=padiz-446920")
        print("  2) cd C:\\youtube_pipeline && python refresh_youtube_token.py")
        print("  3) python refresh_youtube_token.py --pat <GITHUB_PAT>")
        print("     (یا مقدار YOUTUBE_TOKEN_B64.txt را در GitHub Secrets آپدیت کن)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())