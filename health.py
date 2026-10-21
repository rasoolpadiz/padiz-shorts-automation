#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""گزارش سلامت یک‌صفحه‌ای — «آیا همه‌چیز خودش کار می‌کند؟»

    python health.py            # متن خوانا (exit 0 سالم، 1 هشدار، 2 خراب)
    python health.py --json     # برای مانیتورینگ
    python health.py --no-net   # بدون تماس با یوتیوب (سریع، فقط فایل‌ها)

چرا هست: بعد از حادثه‌ی ۲۰۲۶-۱۰-۲۱ (دو آپلود مرده که سهمیه را خوردند و
هیچ ریپاستی منتشر نشد) مالک باید بتواند بدون خواندن چهار لاگ و بدون
SSH زدن بفهمد اوضاع سالم است یا نه.
"""
import argparse
import json
import os
import pickle
import shutil
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, "token.pickle")
STATE = os.path.join(BASE_DIR, "repost_posted.json")
SHORTS_STATE = os.path.join(BASE_DIR, "posted_shorts.json")
HEALTH_PATH = os.path.join(BASE_DIR, "health.json")

DELETE_SCOPES = {
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube",
}


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _rows(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def check_token(net=True):
    """توکن سالم است؟ (و مجوز حذف دارد؟)"""
    out = {"ok": False, "channel": "", "can_delete": False, "detail": ""}
    if not os.path.exists(TOKEN_PATH):
        out["detail"] = "token.pickle نیست"
        return out
    try:
        with open(TOKEN_PATH, "rb") as fh:
            creds = pickle.load(fh)
        out["can_delete"] = bool(set(creds.scopes or []) & DELETE_SCOPES)
    except Exception as exc:  # noqa: BLE001
        out["detail"] = "token.pickle خوانده نشد: %s" % str(exc)[:80]
        return out

    if not net:
        out["ok"] = True
        out["detail"] = "چک نشد (--no-net)"
        return out

    try:
        from googleapiclient.discovery import build
        from google.auth.transport.requests import Request

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "wb") as fh:
                pickle.dump(creds, fh)
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        r = yt.channels().list(part="snippet,statistics", mine=True).execute()
        item = (r.get("items") or [{}])[0]
        out["channel"] = (item.get("snippet") or {}).get("title", "")
        st = item.get("statistics") or {}
        out["subs"] = st.get("subscriberCount")
        out["videos"] = st.get("videoCount")
        out["ok"] = bool(out["channel"])
        out["detail"] = "سالم" if out["ok"] else "کانال برنگشت"
    except Exception as exc:  # noqa: BLE001
        out["detail"] = str(exc)[:140]
    return out


def check_quota():
    try:
        import yt_budget as B
        return {
            "spent": B.spent_today(),
            "uploads_today": B.uploads_done_today(),
            "affordable": B.uploads_affordable(),
            "detail": B.report(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"spent": 0, "uploads_today": 0, "affordable": 0,
                "detail": "خوانده نشد: %s" % str(exc)[:80]}


def check_state():
    repost = _rows(STATE)
    shorts = _rows(SHORTS_STATE)
    today = _today()
    dead = [r for r in repost if r.get("health") == "dead"]
    return {
        "repost_today": sum(1 for r in repost
                            if str(r.get("posted_at", ""))[:10] == today
                            and r.get("health") != "dead"),
        "repost_total": len(repost),
        "dead": len(dead),
        "dead_ids": [(r.get("url") or "").rsplit("/", 1)[-1] for r in dead],
        "shorts_today": sum(1 for r in shorts
                            if str(r.get("posted_at", ""))[:10] == today),
    }


def check_disk():
    try:
        u = shutil.disk_usage(BASE_DIR)
        free_gb = u.free / (1024 ** 3)
        return {"free_gb": round(free_gb, 1), "ok": free_gb > 2.0}
    except Exception:  # noqa: BLE001
        return {"free_gb": -1, "ok": True}


def check_last_run():
    """آخرین بار کی اجرا شد؟ (از mtime آخرین لاگ ریپاست)"""
    logs = os.path.join(BASE_DIR, "repost_out", "logs")
    if not os.path.isdir(logs):
        return {"age_hours": -1, "ok": True}
    files = [os.path.join(logs, f) for f in os.listdir(logs) if f.endswith(".log")]
    if not files:
        return {"age_hours": -1, "ok": True}
    newest = max(files, key=os.path.getmtime)
    age = (datetime.now().timestamp() - os.path.getmtime(newest)) / 3600.0
    return {"age_hours": round(age, 1), "ok": age < 48}


def build(net=True):
    tok = check_token(net)
    q = check_quota()
    s = check_state()
    d = check_disk()
    lr = check_last_run()

    problems, warnings = [], []
    if not tok["ok"]:
        problems.append("توکن یوتیوب کار نمی‌کند: %s" % tok["detail"])
    if q["affordable"] <= 0:
        warnings.append("بودجه‌ی API امروز تمام شده — آپلودی انجام نمی‌شود")
    if s["dead"]:
        warnings.append("%d آپلود مرده در تاریخچه (%s)" % (
            s["dead"], ", ".join(s["dead_ids"][:3])))
    if not d["ok"]:
        problems.append("فضای دیسک کم است: %.1f GB" % d["free_gb"])
    if not lr["ok"]:
        warnings.append("آخرین اجرا %.0f ساعت پیش بود — کرون را چک کن" % lr["age_hours"])
    if tok["ok"] and not tok["can_delete"]:
        warnings.append("توکن مجوز حذف ندارد (ویدیوی خراب خودکار پاک نمی‌شود)")

    status = "OK"
    if problems:
        status = "FAIL"
    elif warnings:
        status = "WARN"

    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "token": tok, "quota": q, "state": s, "disk": d, "last_run": lr,
        "problems": problems, "warnings": warnings,
    }


def render(rep):
    icon = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[rep["status"]]
    t, q, s = rep["token"], rep["quota"], rep["state"]
    lines = [
        "%s  وضعیت کلی: %s" % (icon, rep["status"]),
        "-" * 58,
        "توکن     : %s%s" % (
            "سالم" if t["ok"] else "خراب",
            " | %s" % t["channel"] if t.get("channel") else ""),
        "کانال    : %s سابسکرایبر | %s ویدیو" % (
            t.get("subs", "?"), t.get("videos", "?")),
        "مجوز حذف : %s" % ("دارد" if t["can_delete"] else "ندارد"),
        "سهمیه    : %s واحد مصرف‌شده | %d آپلود ممکن" % (
            q["spent"], q["affordable"]),
        "امروز    : %d ریپاست + %d شورت" % (s["repost_today"], s["shorts_today"]),
        "تاریخچه  : %d ریپاست (%d مرده)" % (s["repost_total"], s["dead"]),
        "دیسک     : %.1f GB آزاد" % rep["disk"]["free_gb"],
        "آخرین اجرا: %s" % (
            "—" if rep["last_run"]["age_hours"] < 0
            else "%.1f ساعت پیش" % rep["last_run"]["age_hours"]),
    ]
    if rep["problems"]:
        lines.append("-" * 58)
        for p in rep["problems"]:
            lines.append("  ❌ " + p)
    if rep["warnings"]:
        lines.append("-" * 58)
        for w in rep["warnings"]:
            lines.append("  ⚠️  " + w)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="گزارش سلامت پایپ‌لاین پادیز")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-net", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="health.json را هم بنویس")
    a = ap.parse_args(argv)

    rep = build(net=not a.no_net)
    if a.write or a.json:
        try:
            with open(HEALTH_PATH, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    print(json.dumps(rep, ensure_ascii=False, indent=2) if a.json else render(rep))
    return {"OK": 0, "WARN": 1, "FAIL": 2}[rep["status"]]


if __name__ == "__main__":
    sys.exit(main())
