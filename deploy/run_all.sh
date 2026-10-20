#!/usr/bin/env bash
# Merged daily run for the Padiz server: repost + self-made Shorts.
#
# ONE cron entry now covers the whole day (this is the point of the merge):
#   step 1  repost.py        -> shortsdl finds the top Shorts, downloads them,
#                               uploads them through the channel's OAuth token
#   step 2  run_daily.py     -> renders + publishes the self-made Persian Short
#
# Both steps share the 10,000-unit daily API budget (5 uploads max), which
# run_all_daily.py enforces before spending anything.
#
# Low CPU/IO priority so the VPN panel never feels it; flock serializes a late
# catch-up against the primary run. Artifacts are cleaned after a success.
set -e
REPO=/opt/padiz/repo
VENV=/opt/padiz/venv
LOG=/var/log/padiz_all.log
cd "$REPO"
set -a; . "$REPO/.env"; set +a
export PADIZ_MINE=1 PADIZ_PRUNE=1

# Refresh code + state before publishing. Never fatal: a stale publish beats a
# missed slot, and pull.sh always exits 0.
bash "$REPO/deploy/pull.sh" || true

PY="$VENV/bin/python"
[ -x "$PY" ] || PY="$REPO/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[all] FATAL: no usable python venv ($VENV, $REPO/.venv)" >> "$LOG"
  exit 1
fi

# The merge added the downloader to this venv. If a pull brought new
# requirements and nobody ran pip, the run would publish nothing at all - so
# install them here (once; afterwards the import succeeds and this is a no-op).
if ! "$PY" -c "import yt_dlp" >/dev/null 2>&1; then
  echo "[all] yt-dlp missing in the venv - installing requirements.txt" >> "$LOG"
  "$PY" -m pip install -q -r "$REPO/requirements.txt" >> "$LOG" 2>&1 || \
    echo "[all] pip install failed - repost step will fail loudly" >> "$LOG"
fi

LOCK=/opt/padiz/run_all.lock
exec 9>"$LOCK"
if ! flock -n 9; then echo "[all] lock held - skip"; exit 0; fi
TS=$(date -u +%Y%m%d_%H%M%S)
echo "==== all run $TS ====" >> "$LOG"
if nice -n 15 ionice -c2 -n7 "$PY" run_all_daily.py "$@" >> "$LOG" 2>&1; then
  nice -n 15 "$PY" cleanup_artifacts.py >> "$LOG" 2>&1 || true
  echo "[all] done+cleaned $TS" >> "$LOG"
else
  echo "[all] FAILED $TS (exit $?) - artifacts kept" >> "$LOG"
fi
