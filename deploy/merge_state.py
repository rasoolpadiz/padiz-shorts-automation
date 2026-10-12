"""Union the server's live publish state back on top of the freshly pulled repo.

Called by deploy/pull.sh with the snapshot directory as argv[1].

The publish-state files used to be tracked in git, so `git reset --hard
origin/main` replaced them with whatever the repo last saw - and the server's
copies are the authoritative record of what has already been published. They are
now UNTRACKED (see .gitignore), which is the real fix: no reset can touch them.

This module remains as the transition guard. On the first pull after they were
untracked, git still deletes them (it removes a file that was tracked in the old
commit), and this puts them back. Afterwards it is a no-op, because the files are
untracked and the reset never touches them.

This only ever ADDS. An entry present on the server but missing from the repo is
kept, and an entry present in the repo but missing from the server is kept too.
Nothing is ever removed, because dropping an id from the "already published" set
is exactly what would cause a duplicate upload. The worst case of a bug here is
a video being skipped, not published twice.

Deliberately not handled here (the repo owns them; GitHub Actions writes them):
    discovery_pool.json, analytics_history.json
"""

import json
import os
import shutil
import sys

# Lists of published entries, merged by id.
LIST_FILES = [
    "posted_shorts.json",
    "longform_out/posted_long.json",
]

# Directories of generated drafts, merged by filename.
DIRS = [
    "shorts_generated",
    "topics_generated",
]

# Files where the server's live copy replaces the repo's outright.
#
# discovery_quota.json is the shared YouTube unit ledger (yt_budget.py). It is
# tracked in git, so without this the reset in pull.sh wipes the day's spend -
# observed live: the trend refresh recorded 304 units, the next pull zeroed it,
# and the following upload reported spent=1600 instead of 1904. Under-counting
# the ledger is what lets discovery overspend the budget.
SERVER_WINS = [
    "discovery_quota.json",
]


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return None


def _key(item):
    """Identity of one PUBLISH EVENT.

    This must not be the topic id: `id` is the topic slug and repeats every time
    the same topic is published again, so keying on it makes the union keep the
    older record and silently drop the newer one - which is how today's uploads
    disappeared from posted_shorts.json. The upload URL (or video id) is unique
    per publish, so that is what identifies an event.
    """
    if isinstance(item, dict):
        for k in ("url", "video_id", "videoId"):
            if item.get(k):
                return str(item[k])
        # No URL recorded: fall back to topic + timestamp, so two publishes of
        # the same topic on different days stay distinct.
        if item.get("id"):
            return f"{item['id']}@{item.get('posted_at', '')}"
        for k in ("id", "title"):
            if item.get(k):
                return str(item[k])
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def merge_list(server_path, repo_path):
    """Union two JSON lists of published entries. Returns (kept, added).

    posted_shorts.json is a list but longform_out/posted_long.json is a DICT
    ({"posted": {...}, "counts": {...}}). Anything that is not a list on either
    side is left to the server, which is always the authoritative copy here -
    a shape mismatch must never end in the repo's version overwriting it.
    """
    server = _load(server_path)
    repo = _load(repo_path)

    if not isinstance(server, list):
        if server is not None and not isinstance(repo, list):
            shutil.copy2(server_path, repo_path)
        return 0, 0
    if not isinstance(repo, list):
        # The repo has no usable copy - keep the server's outright.
        shutil.copy2(server_path, repo_path)
        return len(server), 0

    seen = {}
    for item in repo:
        seen[_key(item)] = item
    added = 0
    for item in server:
        k = _key(item)
        if k not in seen:
            seen[k] = item
            added += 1

    merged = list(seen.values())
    try:
        merged.sort(key=lambda d: str(d.get("posted_at", "")) if isinstance(d, dict) else "")
    except Exception:
        pass

    if added:
        with open(repo_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return len(merged), added


def merge_dir(snapshot_dir, repo_dir):
    """Copy in any snapshot file the repo copy does not have."""
    if not os.path.isdir(snapshot_dir):
        return 0
    os.makedirs(repo_dir, exist_ok=True)
    added = 0
    for name in os.listdir(snapshot_dir):
        src = os.path.join(snapshot_dir, name)
        dst = os.path.join(repo_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            added += 1
    return added


def main():
    if len(sys.argv) < 2:
        print("usage: merge_state.py <snapshot_dir>")
        return 1
    snap = sys.argv[1]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for rel in LIST_FILES:
        s = os.path.join(snap, rel)
        r = os.path.join(repo, rel)
        if os.path.exists(s):
            if not os.path.exists(r):
                os.makedirs(os.path.dirname(r), exist_ok=True)
                shutil.copy2(s, r)
                print(f"[state] {rel}: restored (repo had no copy)")
                continue
            total, added = merge_list(s, r)
            print(f"[state] {rel}: {total} entries, +{added} recovered from the server")

    for rel in DIRS:
        added = merge_dir(os.path.join(snap, rel), os.path.join(repo, rel))
        print(f"[state] {rel}/: +{added} file(s) recovered from the server")

    for rel in SERVER_WINS:
        s = os.path.join(snap, rel)
        r = os.path.join(repo, rel)
        if os.path.exists(s):
            os.makedirs(os.path.dirname(r) or ".", exist_ok=True)
            shutil.copy2(s, r)
            print(f"[state] {rel}: kept the server's live copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
