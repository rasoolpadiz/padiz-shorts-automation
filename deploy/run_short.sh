#!/usr/bin/env bash
# Daily Persian Short (one full-screen slide, ~40-50s). Low CPU/IO priority so the
# VPN panel never feels it. flock serializes a late catch-up vs the primary run.
# Cleans render artifacts after a successful upload (no server archives).
set -e
REPO=/opt/padiz/repo
VENV=/opt/padiz/venv
cd "$REPO"
set -a; . "$REPO/.env"; set +a
export PADIZ_MINE=1 PADIZ_PRUNE=1

# Refresh code + state before publishing. Never fatal: a stale publish beats a
# missed slot, and pull.sh always exits 0.
"$REPO/deploy/pull.sh" || true

# The venv used to be resolved as ./.venv/bin/python. That directory lost its
# bin/ and pyvenv.cfg, so every cron run died with "No such file or directory"
# and nothing was published for a day. Resolve it explicitly instead, and fail
# loudly rather than silently skipping.
PY="$VENV/bin/python"
[ -x "$PY" ] || PY="$REPO/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[short] FATAL: no usable python venv ($VENV, $REPO/.venv)" >> /var/log/padiz_short.log
  exit 1
fi

LOCK=/opt/padiz/run_short.lock
exec 9>"$LOCK"
if ! flock -n 9; then echo "[short] lock held - skip"; exit 0; fi
TS=$(date -u +%Y%m%d_%H%M%S)
LOG=/var/log/padiz_short.log
echo "==== short run $TS ====" >> "$LOG"
if nice -n 15 ionice -c2 -n7 "$PY" run_daily.py >> "$LOG" 2>&1; then
  nice -n 15 "$PY" cleanup_artifacts.py >> "$LOG" 2>&1 || true
  echo "[short] done+cleaned $TS" >> "$LOG"
else
  echo "[short] FAILED $TS (exit $?) - artifacts kept" >> "$LOG"
fi
