#!/usr/bin/env bash
# Safe auto-pull for the Padiz publishing server.
#
# WHY THIS IS NOT JUST `git pull`
# The publish-state files are TRACKED in git (posted_shorts.json,
# longform_out/posted_long.json, shorts_generated/, topics_generated/). They are
# written on the server as videos go out, so the server's copies are the
# authoritative record of what has already been published. A plain
# `git reset --hard origin/main` rewinds that record to whatever the repo last
# saw, and the automation would then re-upload videos that are already live.
#
# So the order is: snapshot the live state -> hard-sync code -> union the live
# state back on top (deploy/merge_state.py). The union only ever ADDS an id to
# the "already published" set, never removes one, so the worst case is a skipped
# video rather than a duplicate upload.
#
# discovery_quota.json (the shared unit ledger) is restored wholesale, since the
# repo's copy can only ever be a stale snapshot from a local run.
#
# Never fatal: if the fetch fails the caller keeps publishing with the code that
# is already on disk. A stale publish beats no publish.
set -uo pipefail

REPO=/opt/padiz/repo
PY=/opt/padiz/venv/bin/python
LOG=/var/log/padiz_pull.log
SNAP=/opt/padiz/state_snapshot

cd "$REPO" || exit 1
echo "==== pull $(date -u +%Y-%m-%dT%H:%M:%SZ) ====" >> "$LOG"

BEFORE=$(git rev-parse --short HEAD 2>/dev/null || echo '?')

# 1. Snapshot the live publish state BEFORE anything can rewind it.
#    If the snapshot cannot be taken, do NOT proceed: a reset without a usable
#    snapshot is exactly how the publish record gets destroyed.
rm -rf "$SNAP"
mkdir -p "$SNAP/longform_out"
snap_fail=0
for f in posted_shorts.json longform_out/posted_long.json discovery_quota.json; do
  [ -f "$f" ] && { cp -a "$f" "$SNAP/$f" || snap_fail=1; }
done
for d in shorts_generated topics_generated; do
  [ -d "$d" ] && { cp -a "$d" "$SNAP/" || snap_fail=1; }
done
if [ "$snap_fail" != "0" ]; then
  echo "[pull] snapshot FAILED - leaving the tree untouched" >> "$LOG"
  exit 0
fi

# 2. Sync code + the repo's copy of the state.
if ! git fetch origin -q >>"$LOG" 2>&1; then
  echo "[pull] fetch failed - keeping the code already on disk" >> "$LOG"
  exit 0
fi
git reset --hard origin/main -q >>"$LOG" 2>&1
AFTER=$(git rev-parse --short HEAD 2>/dev/null || echo '?')

# 3. Put the live state back on top.
if [ -x "$PY" ] && [ -f "$REPO/deploy/merge_state.py" ]; then
  "$PY" "$REPO/deploy/merge_state.py" "$SNAP" >>"$LOG" 2>&1 \
    || echo "[pull] merge_state failed - falling back to a raw restore" >> "$LOG"
fi

# 4. Verify. The state files are untracked, so the FIRST pull after that change
#    still deletes them (git removes a file that was tracked in the old commit).
#    Anything the snapshot had that is now missing is copied straight back.
restored=0
for f in posted_shorts.json longform_out/posted_long.json discovery_quota.json; do
  if [ -f "$SNAP/$f" ] && [ ! -f "$REPO/$f" ]; then
    mkdir -p "$(dirname "$REPO/$f")"
    cp -a "$SNAP/$f" "$REPO/$f" && restored=$((restored + 1))
  fi
done
for d in shorts_generated topics_generated; do
  if [ -d "$SNAP/$d" ] && [ ! -d "$REPO/$d" ]; then
    cp -a "$SNAP/$d" "$REPO/$d" && restored=$((restored + 1))
  fi
done
[ "$restored" != "0" ] && echo "[pull] restored $restored state path(s) from the snapshot" >> "$LOG"

echo "[pull] $BEFORE -> $AFTER" >> "$LOG"
exit 0
