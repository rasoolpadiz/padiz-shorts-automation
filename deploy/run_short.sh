#!/usr/bin/env bash
# DEPRECATED SHIM - kept so an existing crontab line keeps working.
#
# Until 2026-10-20 this ran `run_daily.py` (self-made Short only). The downloader
# project is now merged in, so one run has to do BOTH: publish the 2 downloaded
# Shorts and render the self-made one. Rather than asking the owner to edit the
# crontab on the server, this entry point now delegates to run_all.sh - the
# schedule that is already installed picks up the merged behaviour on the next
# pull.
#
# New installs should point cron at deploy/run_all.sh directly.
exec bash "$(dirname "$0")/run_all.sh" "$@"
