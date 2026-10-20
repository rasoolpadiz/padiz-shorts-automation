"""ساخت ایندکس (CSV/JSON) و گزارش HTML از نتیجه‌ی دانلود."""

from __future__ import annotations

import csv
import html
import json
import logging
from pathlib import Path

from .utils import human_duration, human_size, human_views, now_iso

LOG = logging.getLogger("shortsdl.index")

FIELDS = [
    "market", "rank", "id", "title", "channel", "views", "views_human",
    "duration", "duration_human", "url", "file", "size_bytes", "size_human",
    "status", "error", "collected_at",
]


def build_rows(market: str, items: list[dict], results: list[dict]) -> list[dict]:
    by_id = {r["id"]: r for r in results}
    rows = []
    for idx, item in enumerate(items, 1):
        res = by_id.get(item["id"], {})
        path = res.get("file")
        rows.append({
            "market": market,
            "rank": idx,
            "id": item["id"],
            "title": item.get("title", ""),
            "channel": item.get("channel", ""),
            "views": item.get("views") or 0,
            "views_human": human_views(item.get("views")),
            "duration": item.get("duration") or 0,
            "duration_human": human_duration(item.get("duration")),
            "url": item.get("url", ""),
            "file": path or "",
            "size_bytes": res.get("size") or 0,
            "size_human": human_size(res.get("size")) if path else "-",
            "status": "ok" if path else "failed",
            "error": res.get("error") or "",
            "collected_at": now_iso(),
        })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig تا اکسل فارسی را درست نشان دهد
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    LOG.info("ایندکس CSV نوشته شد: %s", path)


def write_json(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    LOG.info("ایندکس JSON نوشته شد: %s", path)


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--muted:#6b7280;--line:#e5e7eb;--accent:#d90429}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font-family:Vazirmatn,"Segoe UI",Tahoma,system-ui,sans-serif;direction:rtl}
header{padding:28px 24px 18px;background:linear-gradient(180deg,#fff,#f6f7f9);border-bottom:1px solid var(--line)}
h1{margin:0 0 6px;font-size:24px}
.sub{color:var(--muted);font-size:13px}
.wrap{padding:24px;max-width:1240px;margin:0 auto}
section{margin-bottom:36px}
h2{font-size:18px;margin:0 0 4px;display:flex;align-items:center;gap:8px}
h2 .badge{font-size:12px;font-weight:400;color:var(--muted);background:#eef0f3;padding:2px 8px;border-radius:99px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px;margin-top:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
 display:flex;flex-direction:column;transition:box-shadow .15s,transform .15s}
.card:hover{box-shadow:0 6px 20px rgba(0,0,0,.08);transform:translateY(-2px)}
.thumb{position:relative;aspect-ratio:9/16;background:#0f1115 center/cover no-repeat;max-height:320px}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.rank{position:absolute;top:8px;right:8px;background:rgba(0,0,0,.72);color:#fff;font-size:12px;
 padding:2px 8px;border-radius:99px}
.dur{position:absolute;bottom:8px;left:8px;background:rgba(0,0,0,.72);color:#fff;font-size:11px;
 padding:1px 6px;border-radius:4px}
.body{padding:10px 12px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
.title{font-size:13px;line-height:1.6;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
 overflow:hidden;min-height:2.9em}
.meta{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--muted)}
.views{color:var(--accent);font-weight:600}
.ch{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.actions{display:flex;gap:8px;margin-top:auto;padding-top:8px}
a.btn{flex:1;text-align:center;text-decoration:none;font-size:12px;padding:6px 8px;border-radius:8px;
 border:1px solid var(--line);color:var(--ink)}
a.btn.primary{background:var(--ink);color:#fff;border-color:var(--ink)}
a.btn.disabled{opacity:.45;pointer-events:none}
footer{padding:20px 24px 40px;color:var(--muted);font-size:12px;text-align:center}
"""


def _card(row: dict, folder_rel: str) -> str:
    vid = row["id"]
    thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    local = row["file"]
    if local:
        try:
            local_rel = f"{folder_rel}/{Path(local).name}"
        except Exception:
            local_rel = ""
    else:
        local_rel = ""
    return f"""
    <article class="card">
      <div class="thumb">
        <img loading="lazy" src="{thumb}" alt="">
        <span class="rank">#{row['rank']:02d}</span>
        <span class="dur">{html.escape(row['duration_human'])}</span>
      </div>
      <div class="body">
        <div class="title" title="{html.escape(row['title'])}">{html.escape(row['title'])}</div>
        <div class="ch">{html.escape(row['channel'])}</div>
        <div class="meta">
          <span class="views">{html.escape(row['views_human'])} بازدید</span>
          <span>{html.escape(row['size_human'])}</span>
        </div>
        <div class="actions">
          <a class="btn primary" href="{html.escape(row['url'])}" target="_blank" rel="noopener">یوتیوب</a>
          <a class="btn {'disabled' if not local_rel else ''}" href="{html.escape(local_rel)}" target="_blank">فایل</a>
        </div>
      </div>
    </article>"""


def write_report(path: Path, sections: list[tuple[str, str, list[dict]]], folder_prefix: str = "") -> None:
    """گزارش HTML. sections: [(market_key, label, rows), ...]"""
    total_ok = sum(1 for _, _, rows in sections for r in rows if r["status"] == "ok")
    total = sum(len(rows) for _, _, rows in sections)
    blocks = []
    for key, label, rows in sections:
        cards = "".join(_card(r, f"{folder_prefix}{key}") for r in rows)
        ok = sum(1 for r in rows if r["status"] == "ok")
        blocks.append(f"""
    <section>
      <h2>{html.escape(label)} <span class="badge">{ok} از {len(rows)} فایل</span></h2>
      <div class="grid">{cards}</div>
    </section>""")

    doc = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>پربازدیدترین YouTube Shorts</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>پربازدیدترین YouTube Shorts</h1>
  <div class="sub">جمع‌آوری‌شده در {html.escape(now_iso())} — {total_ok} فایل دانلودشده از {total} مورد</div>
</header>
<div class="wrap">{''.join(blocks)}</div>
<footer>ساخته‌شده با yt-dlp — رتبه‌بندی بر اساس تعداد بازدید کاندیداهای کشف‌شده است.</footer>
</body>
</html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    LOG.info("گزارش HTML نوشته شد: %s", path)
