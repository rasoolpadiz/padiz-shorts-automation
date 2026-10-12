#!/usr/bin/env bash
# Daily disk janitor - the safety net that keeps the server from archiving.
#
# WHY THIS EXISTS
# cleanup_artifacts.py runs only after a SUCCESSFUL upload. That is deliberate:
# a failed run keeps its artifacts for debugging. But it means a pipeline that
# fails repeatedly accumulates forever, and there was no second line of defence.
# Measured on this server: 615MB of stale long-form MP4s, because the long-form
# job had been failing on a numpy that the CPU cannot run.
#
# So this runs once a day, regardless of what the publish jobs did, and prunes:
#   1. the normal cleanup (idempotent, safe by construction), and
#   2. anything in the transient dirs older than MAX_AGE_H - i.e. leftovers from
#      a run that never reached cleanup.
#
# It touches ONLY the paths cleanup_artifacts.py already owns, plus the run logs.
# Source, tokens, state json, fonts and the music assets are never touched.
set -uo pipefail

REPO=/opt/padiz/repo
PY=/opt/padiz/venv/bin/python
LOG=/var/log/padiz_janitor.log
MAX_AGE_H=24

echo "==== janitor $(date -u +%Y-%m-%dT%H:%M:%SZ) ====" >> "$LOG"
before=$(df -k / | awk 'NR==2{print $3}')

# 1. The normal cleanup.
if [ -x "$PY" ] && [ -f "$REPO/cleanup_artifacts.py" ]; then
  cd "$REPO" && nice -n 15 "$PY" cleanup_artifacts.py >> "$LOG" 2>&1
fi

# 2. Age-based sweep of the transient dirs only.
for d in temp_render short_out longform_out longform_images; do
  [ -d "$REPO/$d" ] || continue
  find "$REPO/$d" -type f -mmin +$((MAX_AGE_H * 60)) \
    \( -name '*.mp4' -o -name '*.mp3' -o -name '*.wav' \
       -o -name '*.png' -o -name '*.jpg' -o -name '*.srt' \) \
    -print -delete >> "$LOG" 2>&1
done

# 3. Keep the run logs bounded (this box has no logrotate config for them).
for f in /var/log/padiz_short.log /var/log/padiz_long.log \
         /var/log/padiz_pull.log /var/log/padiz_trend.log; do
  [ -f "$f" ] || continue
  sz=$(stat -c%s "$f")
  if [ "$sz" -gt 5242880 ]; then
    tail -c 2000000 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "[janitor] trimmed $f (was $((sz / 1024))KB)" >> "$LOG"
  fi
done

after=$(df -k / | awk 'NR==2{print $3}')
echo "[janitor] freed $(( (before - after) / 1024 ))MB | disk now: $(df -h / | awk 'NR==2{print $3" used of "$2", "$4" free"}')" >> "$LOG"
