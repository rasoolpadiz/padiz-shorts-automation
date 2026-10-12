#!/usr/bin/env bash
# Refresh the trending pool the topic pickers read.
#
# WHY THIS EXISTS
# trend_finder.discover() is the only thing that writes trend_pool.json, and
# nothing was calling it on a schedule - so the "live trending" signal that
# gen_shorts._trend_pick and gen_topics._research_brief read was only ever as
# fresh as the last time someone ran the module by hand.
#
# COST
# 3 searches x 100 units = 300 of the day's 10,000. yt_budget reserves the four
# uploads (1,600 units each) first, so this can never starve publishing - if the
# budget is short, discover() refuses to start and this exits harmlessly.
set -uo pipefail

REPO=/opt/padiz/repo
PY=/opt/padiz/venv/bin/python
LOG=/var/log/padiz_trend.log

cd "$REPO" || exit 1
set -a; . "$REPO/.env"; set +a

echo "==== trend refresh $(date -u +%Y-%m-%dT%H:%M:%SZ) ====" >> "$LOG"
nice -n 15 "$PY" trend_finder.py --searches 3 >> "$LOG" 2>&1 \
  || echo "[trend] refresh failed (pool left as it was)" >> "$LOG"
