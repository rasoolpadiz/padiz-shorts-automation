#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""توکن یوتیوب را بازسازی کن و (اختیاری) سکرت گیت‌هاب را آپدیت کن.

چرا لازم شد؟ 2026-10-02 آپلودها با این خطا متوقف شدند:
    google.auth.exceptions.RefreshError: invalid_grant: Token has been expired or revoked.
علت: اپ OAuth در Google Cloud روی حالت «Testing» بوده و گوگل refresh token را
بعد از ۷ روز باطل می‌کند. راه‌حل دائمی: اپ را Publish کن (مرحلهٔ ۱ پایین).

Usage (فقط همین یک خط):
    python refresh_youtube_token.py

اختیاری، برای آپدیت خودکار سکرت گیت‌هاب:
    python refresh_youtube_token.py --pat <GITHUB_PAT>
    (PAT باید دسترسی repo + Secrets: read and write داشته باشد)

مرحلهٔ ۱ (یک‌بار برای همیشه، در مرورگر):
    https://console.cloud.google.com/apis/credentials/consent?project=padiz-446920
    → Publishing status: Testing  → دکمهٔ "PUBLISH APP" را بزن (In production)
    اگر این کار را نکنی، ۷ روز بعد دوباره همین اتفاق می‌افتد.
"""
import argparse
import base64
import os
import pickle
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.path.join(BASE_DIR, "client_secret.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")
B64_PATH = os.path.join(BASE_DIR, "YOUTUBE_TOKEN_B64.txt")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def new_token():
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(CLIENT_SECRET):
        raise SystemExit(f"client_secret.json پیدا نشد: {CLIENT_SECRET}")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    print("\nمرورگر باز می‌شود → با همان اکانت کانال پادیز وارد شو → Allow\n")
    return flow.run_local_server(port=0, access_type="offline", prompt="consent")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Padiz YouTube token refresh")
    ap.add_argument("--pat", default="", help="GitHub PAT برای آپدیت خودکار سکرت (اختیاری)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    print("=" * 68)
    print("  بازسازی توکن یوتیوب - پادیز")
    print("=" * 68)
    print("  قبل از این اسکریپت، این لینک را باز کن و PUBLISH APP را بزن:")
    print("    https://console.cloud.google.com/apis/credentials/consent?project=padiz-446920")
    print("  (اگر Testing بماند، ۷ روز بعد دوباره توکن می‌میرد)")
    print("-" * 68)
    print("  الان مرورگر باز می‌شود. با همان اکانت کانال پادیز لاگین کن.")
    print("  اگر صفحهٔ «Google hasn't verified this app» آمد:")
    print("     Advanced  ->  Go to ... (unsafe)  ->  Allow")
    print("=" * 68)
    input("  برای شروع Enter بزن (یا Ctrl+C برای انصراف)... ")

    creds = new_token()

    with open(TOKEN_PATH, "wb") as fh:
        pickle.dump(creds, fh)

    if not creds.refresh_token:
        print("⚠️  refresh_token برنگشت! دوباره با یک اکانت دیگر امتحان کن "
              "(یا دسترسی قبلی را در myaccount.google.com/permissions حذف کن).")

    token_b64 = base64.b64encode(open(TOKEN_PATH, "rb").read()).decode("ascii")
    with open(B64_PATH, "w", encoding="utf-8") as fh:
        fh.write(token_b64)

    # verify the token really works before telling the user it is fixed.
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", credentials=creds)
    who = yt.channels().list(mine=True, part="snippet").execute()
    name = who["items"][0]["snippet"]["title"] if who.get("items") else "?"
    print(f"\n✅ توکن ساخته شد و تست شد | کانال: {name}")
    print(f"   token.pickle            → {TOKEN_PATH}")
    print(f"   YOUTUBE_TOKEN_B64.txt   → {B64_PATH}")

    pat = args.pat.strip() or os.environ.get("GITHUB_PAT", "").strip()
    if not pat:
        print("\nمرحلهٔ بعد (یکی را انجام بده):")
        print("  الف) python refresh_youtube_token.py --pat <GITHUB_PAT>   (خودکار)")
        print("  ب)  دستی: GitHub → Settings → Secrets and variables → Actions")
        print("      → YOUTUBE_TOKEN_B64 → Update → محتوای فایل YOUTUBE_TOKEN_B64.txt را paste کن")
        return 0

    try:
        _push_secret(pat, "YOUTUBE_TOKEN_B64", token_b64)
        print("\n✅ سکرت YOUTUBE_TOKEN_B64 در گیت‌هاب آپدیت شد.")
    except Exception as e:  # noqa: BLE001
        print(f"\n⚠️  آپدیت خودکار سکرت نشد ({e})")
        print("   دستی آپدیت کن: GitHub → Settings → Secrets → YOUTUBE_TOKEN_B64")
        print(f"   مقدار = محتوای {B64_PATH}")
        return 1
    return 0


def _push_secret(pat, name, value, owner="rasoolpadiz", repo="padiz-shorts-automation"):
    """Encrypt with libsodium sealed box (the format GitHub Actions expects) and PUT."""
    import json
    import urllib.request

    from nacl import encoding, public

    api = f"https://api.github.com/repos/{owner}/{repo}/actions/secrets"
    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "padiz-token-refresh",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    req = urllib.request.Request(f"{api}/public-key", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        key_info = json.loads(resp.read())

    pkey = public.PublicKey(key_info["key"].encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pkey).encrypt(value.encode())
    payload = {
        "encrypted_value": base64.b64encode(sealed).decode(),
        "key_id": key_info["key_id"],
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{api}/{name}", data=body, headers=headers, method="PUT")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


if __name__ == "__main__":
    sys.exit(main())
