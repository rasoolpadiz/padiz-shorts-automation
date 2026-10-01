# -*- coding: utf-8 -*-
"""ثبت سکرت GEMINI_API_KEY در GitHub Actions (بدون نیاز به تنظیم دستی در سایت).

Usage:
    python set_github_secret.py <GITHUB_PAT> <GEMINI_API_KEY>

توکن گیت‌هاب باید دسترسی «Secrets: read and write» (یا scope کافی repo) داشته باشد.
روش دستی (اگر توکن ندارید): GitHub -> repo -> Settings -> Secrets and variables ->
Actions -> New repository secret  ->  Name: GEMINI_API_KEY
"""
import sys
import json
import base64
import urllib.request
import urllib.error

# Windows consoles default to cp1252 and would crash on Persian output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

OWNER = "rasoolpadiz"
REPO = "padiz-shorts-automation"
SECRET_NAME = "GEMINI_API_KEY"


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Encrypt with libsodium sealed box, the format GitHub Actions expects."""
    from nacl import encoding, public

    public_key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def github_request(url: str, token: str, method: str = "GET", payload: dict = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
        return response.status, (json.loads(body) if body.strip() else {})


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2

    pat = sys.argv[1].strip()
    api_key = sys.argv[2].strip()

    if not api_key or len(api_key) < 20:
        print("کلید API معتبر به نظر نمی‌رسد (خیلی کوتاه است).")
        return 2

    try:
        status, key_info = github_request(
            f"https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/public-key", pat
        )
    except urllib.error.HTTPError as e:
        print(f"دریافت کلید عمومی مخزن ناموفق بود (HTTP {e.code}): {e.read().decode('utf-8', 'ignore')[:300]}")
        print("دسترسی توکن باید شامل Secrets: read and write باشد.")
        return 1

    print(f"کلید عمومی مخزن دریافت شد (key_id={key_info.get('key_id')}).")

    payload = {
        "encrypted_value": encrypt_secret(key_info["key"], api_key),
        "key_id": key_info["key_id"],
    }

    try:
        status, _ = github_request(
            f"https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/{SECRET_NAME}",
            pat,
            method="PUT",
            payload=payload,
        )
    except urllib.error.HTTPError as e:
        print(f"ثبت سکرت ناموفق بود (HTTP {e.code}): {e.read().decode('utf-8', 'ignore')[:300]}")
        return 1

    if status in (201, 204):
        print(f"سکرت {SECRET_NAME} با موفقیت در {OWNER}/{REPO} ثبت شد.")
        print("اجرای بعدی (یا اجرای دستی ورکفلو) از صدای Gemini استفاده می‌کند.")
        return 0

    print(f"پاسخ غیرمنتظره از GitHub: HTTP {status}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
