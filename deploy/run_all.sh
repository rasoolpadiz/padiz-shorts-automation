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
#
# imageio_ffmpeg is checked alongside yt_dlp on purpose: transform.py needs a
# bundled ffmpeg for the punch-in / card / audio-replace pass. Without it the
# transform step returns None and EVERY repost is skipped - a silent "nothing
# published today" that looks like a YouTube problem. Checking both here turns
# that into a loud, self-healing log line.
if ! "$PY" -c "import yt_dlp, imageio_ffmpeg" >/dev/null 2>&1; then
  echo "[all] yt-dlp or imageio-ffmpeg missing - installing requirements.txt" >> "$LOG"
  "$PY" -m pip install -q -r "$REPO/requirements.txt" >> "$LOG" 2>&1 || \
    echo "[all] pip install failed - repost step will fail loudly" >> "$LOG"
fi

# Narration is what makes a repost count as a new work instead of a re-upload,
# and edge-tts is blocked from some IP ranges (403 from Microsoft). Test it
# once a day so the log shows the truth before the first repost is attempted.
#
# NOTE (2026-10-21): a failed TTS no longer blocks publishing. transform.py
# falls back to the original audio + visual editing (narration.on_fail=upload),
# because a hard block silently produced "zero uploads today" which looked
# exactly like a YouTube problem. Set narration.on_fail=skip to restore the
# old strict behaviour.
TTS_MARK="/opt/padiz/.tts_checked_$(date -u +%Y%m%d)"
if [ ! -f "$TTS_MARK" ]; then
  if nice -n 15 "$PY" transform.py --tts-test >> "$LOG" 2>&1; then
    echo "[all] TTS OK - reposts will be narrated" >> "$LOG"
  else
    echo "[all] WARNING: TTS FAILED - reposts will publish with ORIGINAL AUDIO" >> "$LOG"
    echo "[all]          fix for Persian narration: set GEMINI_API_KEY in .env" >> "$LOG"
  fi
  : > "$TTS_MARK" 2>/dev/null || true
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

# Heartbeat: one small file that answers "is everything fine?" without SSH.
# Written on success AND failure, so a stale health.json is itself a signal
# that cron stopped running.
nice -n 15 "$PY" health.py --write >> "$LOG" 2>&1 || true
