# -*- coding: utf-8 -*-
"""Daily long-form (16:9) runner for Padiz.

Builds + uploads ONE long video per day (>= 8 min, mid-roll eligible),
alternating English / Persian pools so both channels stay warm.
State lives in longform_out/posted_long.json (auto-committed by CI).
"""
import json
import os
import sys
from datetime import date

import longform as L

STATE_PATH = os.path.join(L.LONGFORM_DIR, "posted_long.json")
PER_DAY = int(os.environ.get("LONG_PER_DAY", "1"))


def _safe(line):
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


def _load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"posted": {}, "counts": {}}


def _save_state(state):
    os.makedirs(L.LONGFORM_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pick_topics(topics, state):
    """Alternate EN/FA; prefer never-posted topics, then the least-used one."""
    today = date.today().isoformat()
    order = ["en", "fa"] if len(state.get("posted", {})) % 2 == 0 else ["fa", "en"]
    picked = []
    for lang in order:
        pool = [t for t in topics if t.get("lang") == lang and state["posted"].get(t["id"]) != today]
        if not pool:
            continue
        pool.sort(key=lambda t: state.get("counts", {}).get(t["id"], 0))
        picked.append(pool[0])
        if len(picked) >= PER_DAY:
            break
    return picked


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    topics = L.load_topics()
    if not topics:
        print("[long] no topics available")
        return 1

    state = _load_state()
    wanted = None
    if "--topic" in argv:
        wanted = argv[argv.index("--topic") + 1]

    if wanted:
        targets = [t for t in topics if t["id"] == wanted]
    elif "--list" in argv or not argv:
        for t in topics:
            _safe(f"{t['id']:24} {t['lang']:3} {len(t['scenes']):3} scenes  {t['title'][:60]}")
        return 0
    else:
        targets = pick_topics(topics, state)

    if not targets:
        print("[long] every topic already posted today")
        return 0

    for topic in targets:
        if state["posted"].get(topic["id"]) == date.today().isoformat() and "--force" not in argv:
            print(f"[long] {topic['id']} already posted today - skip")
            continue
        meta = L.build_long_video(topic)
        if "--upload" in argv:
            url = L.upload_long(meta, topic)
            print(f"[long] uploaded {url}")
            state["posted"][topic["id"]] = date.today().isoformat()
            state["counts"][topic["id"]] = state.get("counts", {}).get(topic["id"], 0) + 1
            _save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())