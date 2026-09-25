# -*- coding: utf-8 -*-
"""
Health check for the Padiz Shorts automation.

Run it any time:
    python verify_setup.py

Prints PASS/FAIL for everything that can be verified from this machine:
repository sync, workflow schedule, GitHub scheduler firing, secrets, the
YouTube token, the last successful publish and the topic pool.

Exit code 0 = everything green, 1 = at least one item needs attention.
"""

import json
import os
import pickle
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
REPO = "rasoolpadiz/padiz-shorts-automation"
SLOT_HOURS = [6, 10, 14, 17, 20]  # UTC -> Tehran 09:30, 13:30, 17:30, 20:30, 23:30

results = []


def record(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + ("  |  " + detail if detail else ""))


def github_token():
    proc = subprocess.run(
        ["git", "credential", "fill"],
        cwd=BASE,
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def api(url, tok=None, method="GET", payload=None):
    headers = {"User-Agent": "verify-setup", "Accept": "application/vnd.github+json"}
    if tok:
        headers["Authorization"] = f"token {tok}"
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def check_repository():
    subprocess.run(["git", "fetch", "origin", "--quiet"], cwd=BASE, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BASE, capture_output=True, text=True).stdout.strip()
    remote = subprocess.run(["git", "rev-parse", "origin/main"], cwd=BASE, capture_output=True, text=True).stdout.strip()
    record("مخزن محلی با origin/main همگام است", head == remote, f"{head[:8]} / {remote[:8]}")


def check_workflow_file():
    text = open(os.path.join(BASE, ".github", "workflows", "scheduled_shorts.yml"), encoding="utf-8").read()
    cron = re.search(r"cron:\s*'([^']+)'", text)
    expected = f"0 {','.join(str(h) for h in SLOT_HOURS)} * * *"
    record("۵ بازه زمانی در cron ورک‌فلو ثبت است", bool(cron) and cron.group(1).strip() == expected,
           cron.group(1) if cron else "cron not found")
    run_daily = open(os.path.join(BASE, "run_daily.py"), encoding="utf-8").read()
    record("ضد تکرار آپلود (MIN_GAP_MINUTES) فعال است", "MIN_GAP_MINUTES" in run_daily)
    tracked = subprocess.run(["git", "ls-files", "posted_shorts.json"], cwd=BASE,
                             capture_output=True, text=True).stdout.strip()
    record("posted_shorts.json در مخزن ذخیره شده (چرخش موضوع‌ها)", bool(tracked))


def check_github(tok):
    try:
        workflows = api(f"https://api.github.com/repos/{REPO}/actions/workflows", tok)
        states = {w["path"]: w["state"] for w in workflows.get("workflows", [])}
        state = states.get(".github/workflows/scheduled_shorts.yml")
        record("ورک‌فلوی انتشار نزد گیتهاب active است", state == "active", str(state))
    except Exception as exc:  # noqa: BLE001
        record("ورک‌فلوی انتشار نزد گیتهاب active است", False, str(exc))

    try:
        secrets = api(f"https://api.github.com/repos/{REPO}/actions/secrets", tok)
        names = [s["name"] for s in secrets.get("secrets", [])]
        record("سکرت YOUTUBE_TOKEN_B64 موجود است", "YOUTUBE_TOKEN_B64" in names, ", ".join(names))
    except Exception as exc:  # noqa: BLE001
        record("سکرت YOUTUBE_TOKEN_B64 موجود است", False, str(exc))

    try:
        sched = api(f"https://api.github.com/repos/{REPO}/actions/runs?event=schedule&per_page=1", tok)
        fired = sched.get("total_count", 0)
        record("کرون گیتهاب (رویداد schedule) شلیک شده است", fired > 0, f"total_count={fired}")
    except Exception as exc:  # noqa: BLE001
        record("کرون گیتهاب (رویداد schedule) شلیک شده است", False, str(exc))

    try:
        runs = api(f"https://api.github.com/repos/{REPO}/actions/workflows/scheduled_shorts.yml/runs?per_page=10", tok)
        done = [r for r in runs.get("workflow_runs", []) if r["conclusion"] == "success"]
        if done:
            last = max(done, key=lambda r: r["updated_at"])
            when = datetime.fromisoformat(last["updated_at"].replace("Z", "+00:00"))
            hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600.0
            record("آخرین اجرای موفق ورک‌فلو کمتر از ۲۴ ساعت پیش است", hours < 24,
                   f"{hours:.1f} ساعت پیش ({last['event']})")
        else:
            record("آخرین اجرای موفق ورک‌فلو کمتر از ۲۴ ساعت پیش است", False, "اجرای موفقی نیست")
    except Exception as exc:  # noqa: BLE001
        record("آخرین اجرای موفق ورک‌فلو کمتر از ۲۴ ساعت پیش است", False, str(exc))


def check_local():
    try:
        from google.auth.transport.requests import Request

        with open(os.path.join(BASE, "token.pickle"), "rb") as handle:
            creds = pickle.load(handle)
        creds.refresh(Request())
        record("توکن یوتیوب سالم و refresh می‌شود", creds.valid, f"expiry {creds.expiry}")
    except Exception as exc:  # noqa: BLE001
        record("توکن یوتیوب سالم و refresh می‌شود", False, str(exc))

    try:
        from topics_pool import FACTS_POOL

        record("استخر موضوعات بیش از ۱۲ موضوع است (مناسب ۵ آپلود در روز)", len(FACTS_POOL) > 12,
               f"{len(FACTS_POOL)} موضوع")
    except Exception as exc:  # noqa: BLE001
        record("خواندن topics_pool", False, str(exc))


def main():
    print("=" * 66)
    print("Padiz automation health check -", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    print("=" * 66)

    token = github_token()
    check_repository()
    check_workflow_file()
    check_github(token)
    check_local()

    print("=" * 66)
    failed = [item for item in results if not item[1]]
    if not failed:
        print("همه موارد PASS شد - اتوماسیون کامل و آماده است.")
    else:
        print(f"{len(failed)} مورد نیاز به بررسی دارد:")
        for name, _, detail in failed:
            print("  - " + name + (f"  ({detail})" if detail else ""))
    print("=" * 66)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
