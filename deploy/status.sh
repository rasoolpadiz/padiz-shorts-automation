#!/usr/bin/env bash
# One-screen health report for the Padiz publishing server.
#
# Usage:  bash /opt/padiz/repo/deploy/status.sh
#
# Answers "did the cron actually publish today, and is anything wrong?" without
# having to read four log files by hand.
set -uo pipefail

REPO=/opt/padiz/repo
PY=/opt/padiz/venv/bin/python
cd "$REPO" 2>/dev/null || { echo "repo missing: $REPO"; exit 1; }

line() { printf '%s\n' "------------------------------------------------------------"; }

echo "PADIZ SERVER STATUS   $(date '+%Y-%m-%d %H:%M %Z')   (Tehran $(TZ=Asia/Tehran date '+%H:%M'))"
line

echo "PUBLISHED TODAY (UTC date)"
"$PY" - <<'EOF' 2>/dev/null || echo "  (state files unreadable)"
import json, os
from datetime import datetime, timezone
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
try:
    s = json.load(open("posted_shorts.json"))
    n = [x for x in s if str(x.get("posted_at", ""))[:10] == today]
    print(f"  shorts : {len(n)} today  (last: {max((x.get('posted_at','') for x in s), default='-')})")
except Exception as e:
    print(f"  shorts : unreadable ({e})")
try:
    l = json.load(open("longform_out/posted_long.json"))
    posted = l.get("posted", {}) if isinstance(l, dict) else {}
    n = [k for k, v in posted.items() if str(v)[:10] == today]
    print(f"  long   : {len(n)} today  ({len(posted)} topics tracked)")
except Exception as e:
    print(f"  long   : unreadable ({e})")
try:
    r = json.load(open("repost_posted.json"))
    n = [x for x in r if str(x.get("posted_at", ""))[:10] == today]
    print(f"  repost : {len(n)} today  (total {len(r)} downloaded Shorts published)")
except FileNotFoundError:
    print("  repost : no uploads yet")
except Exception as e:
    print(f"  repost : unreadable ({e})")
EOF

line
echo "LAST RUNS"
for f in all short long pull trend janitor; do
  L="/var/log/padiz_$f.log"
  if [ -f "$L" ]; then
    printf '  %-8s %s\n' "$f" "$(grep -E '^(====|\[.*\] (done|FAILED|fetch))' "$L" 2>/dev/null | tail -1)"
  else
    printf '  %-8s (no log yet)\n' "$f"
  fi
done

line
echo "REPOST QUEUE / DISK"
if [ -d "$REPO/repost_out" ]; then
  echo "  downloaded files waiting: $(find "$REPO/repost_out" -maxdepth 2 -name '*.mp4' -o -maxdepth 2 -name '*.webm' 2>/dev/null | wc -l)"
  echo "  repost_out size: $(du -sh "$REPO/repost_out" 2>/dev/null | cut -f1)"
else
  echo "  repost_out: (absent - no repost run yet)"
fi

line
echo "FAILURES IN THE LAST 24H"
if grep -h "FAILED" /var/log/padiz_short.log /var/log/padiz_long.log 2>/dev/null | tail -5 | grep .; then :; else echo "  none"; fi
if grep -h "\[caption\]\|\[music\]" /var/log/padiz_short.log 2>/dev/null | tail -1 | grep . >/dev/null; then
  echo "  captions: $(grep -c '\[caption\] word-by-word captions ON' /var/log/padiz_short.log) run(s) used them"
fi

line
echo "QUOTA"
"$PY" -c 'import yt_budget as B; print(" ", B.report())' 2>/dev/null || echo "  unavailable"

line
echo "DISK / ARCHIVE"
df -h / | tail -1 | sed 's/^/  /'
echo "  repo: $(du -sh "$REPO" 2>/dev/null | cut -f1)   .git: $(du -sh "$REPO/.git" 2>/dev/null | cut -f1)"
echo "  leftover media >1M: $(find "$REPO" -name '*.mp4' -size +1M -not -path '*/.git/*' 2>/dev/null | wc -l)"
echo "  git tracked state/media that should NOT be: $(git ls-files posted_shorts.json discovery_quota.json longform_out longform_images 2>/dev/null | grep -vc '^longform_out/posted_long\.json$')"

line
echo "NEXT CRON FIRES (server time -> Tehran)"
echo "  $(crontab -l 2>/dev/null | grep -vE '^#|^$' | wc -l) entries installed"
crontab -l 2>/dev/null | grep -vE '^#|^$' | sed 's/^/  /'
line
