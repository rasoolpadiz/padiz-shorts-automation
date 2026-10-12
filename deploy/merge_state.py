"""Union the server's live publish state back on top of the freshly pulled repo.

Called by deploy/pull.sh with the snapshot directory as argv[1].

The publish-state files are tracked in git, so `git reset --hard origin/main`
replaces them with whatever the repo last saw. The server's copies are the
authoritative record of what has already been published, so they are snapshotted
before the sync and re-applied here.

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


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return None


def _key(item):
    """Identity of one published entry. Prefer id, fall back to url, then title."""
    if isinstance(item, dict):
        for k in ("id", "video_id", "url", "title"):
            if item.get(k):
                return str(item[k])
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def merge_list(server_path, repo_path):
    """Union two JSON lists of published entries. Returns (kept, added)."""
    server = _load(server_path)
    repo = _load(repo_path)

    if not isinstance(server, list):
        return 0, 0                      # nothing usable to restore
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
