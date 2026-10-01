# -*- coding: utf-8 -*-
"""Background watcher: polls GitHub for `schedule`-event runs for ~10 minutes."""

import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = "rasoolpadiz/padiz-shorts-automation"
LOG = os.path.join(BASE, "schedule_watch.txt")


def token():
    proc = subprocess.run(
        ["git", "credential", "fill"],
        cwd=BASE,
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def fetch(url, tok):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "schedule-watch",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    tok = token()
    with open(LOG, "a", encoding="utf-8") as log:
        log.write(f"=== watch started {time.strftime('%H:%M:%SZ', time.gmtime())} ===\n")
        log.flush()
        for _ in range(30):  # 30 x 20s = 10 minutes
            stamp = time.strftime("%H:%M:%SZ", time.gmtime())
            try:
                data = fetch(
                    f"https://api.github.com/repos/{REPO}/actions/runs?event=schedule&per_page=5",
                    tok,
                )
                names = ", ".join(
                    f"{run['name']}={run['status']}/{run['conclusion']}"
                    for run in data.get("workflow_runs", [])
                )
                log.write(f"{stamp} schedule_runs={data['total_count']} {names}\n")
            except Exception as exc:  # noqa: BLE001 - diagnostic logger
                log.write(f"{stamp} error: {exc}\n")
            log.flush()
            time.sleep(20)
        log.write(f"=== watch finished {time.strftime('%H:%M:%SZ', time.gmtime())} ===\n")


if __name__ == "__main__":
    sys.exit(main())
