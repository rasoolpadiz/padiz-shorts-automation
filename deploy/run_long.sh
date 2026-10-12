#!/usr/bin/env bash
# Daily Persian long-form (16:9, 8-9 min). --upload is REQUIRED or nothing is
# published. Low priority + serialized + cleanup-after-upload (no server archives).
set -e
REPO=/opt/padiz/repo
VENV=/opt/padiz/venv
cd "$REPO"
set -a; . "$REPO/.env"; set +a
export PADIZ_MINE=1 PADIZ_PRUNE=1 PADIZ_KEEP_ARTIFACTS=0

# Refresh code + state first (see run_short.sh for why this is not `git pull`).
"$REPO/deploy/pull.sh" || true

# Explicit venv resolution - see run_short.sh.
PY="$VENV/bin/python"
[ -x "$PY" ] || PY="$REPO/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[long] FATAL: no usable python venv ($VENV, $REPO/.venv)" >> /var/log/padiz_long.log
  exit 1
fi

LOCK=/opt/padiz/run_long.lock
exec 9>"$LOCK"
if ! flock -n 9; then echo "[long] lock held - skip"; exit 0; fi
TS=$(date -u +%Y%m%d_%H%M%S)
LOG=/var/log/padiz_long.log
echo "==== long run $TS ====" >> "$LOG"
if nice -n 15 ionice -c2 -n7 "$PY" run_long_daily.py --upload >> "$LOG" 2>&1; then
  nice -n 15 "$PY" cleanup_artifacts.py >> "$LOG" 2>&1 || true
  echo "[long] done+cleaned $TS" >> "$LOG"
else
  echo "[long] FAILED $TS (exit $?) - artifacts kept" >> "$LOG"
fi
