# -*- coding: utf-8 -*-
"""Daily long-form (16:9) runner for Padiz.

Builds + uploads ONE long video per day (8-10 min, mid-roll eligible),
alternating English / Persian pools so both channels stay warm.
Primary slot: 12:00 UTC = 15:30 Tehran (best for both monetization + discovery).
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


def _posted_today(state):
    """The id of any long video already published today, or None.

    This is the real once-per-day brake. The workflow runs several catch-up
    crons because GitHub's scheduler is unreliable (it fired 5h49m late on
    2026-09-30 and was skipped entirely on 2026-10-01), so without this guard a
    late second run would happily publish a second video the same day.
    """
    today = date.today().isoformat()
    for topic_id, when in (state.get("posted") or {}).items():
        if when == today:
            return topic_id
    return None


def _last_posted_lang(state):
    """Language of the most recently published long video ('en'/'fa'/None)."""
    posted = state.get("posted") or {}
    if not posted:
        return None
    latest = max(posted.items(), key=lambda kv: kv[1])
    return "en" if str(latest[0]).startswith("en") else "fa"


def pick_topics(topics, state):
    """FA-ONLY (owner directive 2026-10-09): pick an unposted Persian topic.

    Alternation is gone - the last-published language no longer matters.
    Failed or retried runs can never resurrect an English pick.
    """
    today = date.today().isoformat()
    posted = state.get("posted", {})
    pool = [t for t in topics if t.get("lang") == "fa"]
    # The owner asked for zero repeats, so anything already published is out -
    # if the pool runs dry the writer supplies a new topic instead.
    fresh = [t for t in pool
             if t["id"] not in posted and posted.get(t["id"]) != today]
    if not fresh:
        return []
    fresh.sort(key=lambda t: state.get("counts", {}).get(t["id"], 0))
    return fresh[:PER_DAY]


def _top_up(targets, state):
    """If no ready FA topic is left, write a fresh one from a niche (FA only)."""
    import gen_topics
    if len(targets) >= PER_DAY:
        return targets
    try:
        targets.append(gen_topics.build_topic("fa", kind="long"))
    except Exception as e:
        print(f"[long] could not generate a fa topic ({e})")
    return targets



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

    # Strict once-per-day brake. Several catch-up crons exist because GitHub's
    # scheduler is unreliable, so without this the 2nd cron of the day would
    # publish a 2nd video. --force overrides it for a deliberate manual re-run.
    already = _posted_today(state)
    if already and "--force" not in argv and "--render" not in argv:
        print(f"[long] already published today ({already}) - nothing to do")
        return 0

    if wanted:
        targets = [t for t in topics if t["id"] == wanted]
    elif "--render" in argv:
        # Render-only smoke test: build without uploading, never touch state.
        targets = pick_topics(topics, state)
    elif "--list" in argv or not argv:
        for t in topics:
            _safe(f"{t['id']:24} {t['lang']:3} {len(t['scenes']):3} scenes  {t['title'][:60]}")
        return 0
    else:
        targets = _top_up(pick_topics(topics, state), state)

    if not targets:
        print("[long] every topic already posted today")
        return 0

    for topic in targets:
        if state["posted"].get(topic["id"]) == date.today().isoformat() and "--force" not in argv:
            print(f"[long] {topic['id']} already posted today - skip")
            continue
        if topic.get("fallback") and "--allow-fallback" not in argv:
            # A template topic is placeholder text, not a video worth publishing.
            print(f"[long] {topic['id']} is a placeholder (writer unavailable) - not publishing")
            continue
        meta = L.build_long_video(topic)
        if "--upload" in argv:
            url = L.upload_long(meta, topic)
            print(f"[long] uploaded {url}")
            state["posted"][topic["id"]] = date.today().isoformat()
            state["counts"][topic["id"]] = state.get("counts", {}).get(topic["id"], 0) + 1
            _save_state(state)

    # Keep a buffer of unused FA topics so tomorrow never has to wait on the writer.
    if "--upload" in argv and not "--no-prep" in argv:
        try:
            import gen_topics
            ready = [t for t in gen_topics.load_generated()
                     if t.get("lang") == "fa" and t["id"] not in state["posted"]]
            if len(ready) < 2:
                gen_topics.build_topic("fa", kind="long")
        except Exception as e:
            print(f"[long] topic pre-build skipped ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())