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
    """Alternate EN/FA and always prefer a topic the channel has never published."""
    today = date.today().isoformat()
    order = ["en", "fa"] if len(state.get("posted", {})) % 2 == 0 else ["fa", "en"]
    posted = state.get("posted", {})
    picked = []
    for lang in order:
        pool = [t for t in topics if t.get("lang") == lang]
        # The owner asked for zero repeats, so anything already published is out -
        # if the pool runs dry the writer supplies a new topic instead.
        fresh = [t for t in pool
                 if t["id"] not in posted and posted.get(t["id"]) != today]
        if not fresh:
            continue
        fresh.sort(key=lambda t: state.get("counts", {}).get(t["id"], 0))
        picked.append(fresh[0])
        if len(picked) >= PER_DAY:
            break
    return picked


def _top_up(targets, state):
    """If no ready topic is left for a language, write a fresh one from a niche."""
    import gen_topics
    have = {t.get("lang") for t in targets}
    wanted = [l for l in ("en", "fa") if l not in have][:PER_DAY - len(targets)]
    for lang in wanted:
        try:
            targets.append(gen_topics.build_topic(lang))
        except Exception as e:
            print(f"[long] could not generate a {lang} topic ({e})")
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

    # Keep a buffer of unused topics so tomorrow never has to wait on the writer.
    if "--upload" in argv and not "--no-prep" in argv:
        try:
            import gen_topics
            for lang in ("en", "fa"):
                ready = [t for t in gen_topics.load_generated()
                         if t.get("lang") == lang and t["id"] not in state["posted"]]
                if len(ready) < 2:
                    gen_topics.build_topic(lang)
        except Exception as e:
            print(f"[long] topic pre-build skipped ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())