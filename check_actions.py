# -*- coding: utf-8 -*-
"""Pull the REAL GitHub Actions logs for the publishing workflow and show the
lines that explain why the viral-hunter half failed.

Read-only: it only GETs data from api.github.com using the token that git
already has stored for this repo.

    python check_actions.py            # summary of the last runs
    python check_actions.py --logs 3   # + interesting lines of the last 3 runs
"""

import io
import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = "rasoolpadiz/padiz-shorts-automation"
WORKFLOW = "scheduled_shorts.yml"

INTERESTING = re.compile(
    r"(Traceback|Error|error:|ERROR|Exception|quotaExceeded|uploadLimitExceeded"
    r"|invalid_grant|Sign in to confirm|HTTP Error 4\d\d|Downloading video stream"
    r"|Applying Padiz branding|Uploading branded|Viral|viral|No eligible"
    r"|Skipping:|Selected topic|SUCCESSFULLY|exit code)",
)


def github_token():
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


def api(url, tok, raw=False):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "padiz-debug",
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {tok}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    return data if raw else json.loads(data)



def list_runs(tok, limit=15):
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page={limit}"
    runs = api(url, tok).get("workflow_runs", [])
    print(f"{'when (UTC)':20} {'event':17} {'conclusion':12} run id")
    print("-" * 72)
    for r in runs:
        when = r["created_at"][:19].replace("T", " ")
        print(f"{when:20} {r['event']:17} {str(r['conclusion']):12} {r['id']}")
    return runs


def run_log_text(tok, run_id):
    blob = api(f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/logs", tok, raw=True)
    out = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            try:
                out[name] = zf.read(name).decode("utf-8", errors="replace")
            except Exception:
                pass
    return out


def show_interesting(tok, run):
    print("\n" + "=" * 72)
    print(f"RUN {run['id']}  {run['created_at'][:19]}  {run['event']}  {run['conclusion']}")
    print(run["html_url"])
    print("=" * 72)
    try:
        logs = run_log_text(tok, run["id"])
    except Exception as exc:
        print("could not download logs:", exc)
        return
    for name, text in logs.items():
        if "Run automated" not in text and "run_daily" not in text:
            continue
        print(f"--- {name} ---")
        for line in text.splitlines():
            if INTERESTING.search(line):
                print("   ", line.strip()[:200])


def main():
    tok = github_token()
    if not tok:
        raise SystemExit("no github token found via 'git credential fill'")

    print("repo:", REPO)
    runs = list_runs(tok)

    only_logs = 0
    if "--logs" in sys.argv:
        idx = sys.argv.index("--logs")
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            only_logs = int(sys.argv[idx + 1])
    for run in runs[:only_logs]:
        if run["conclusion"] != "success":
            show_interesting(tok, run)

    if "--run" in sys.argv:
        idx = sys.argv.index("--run")
        for rid in sys.argv[idx + 1:]:
            if not rid.isdigit():
                continue
            detail = api(f"https://api.github.com/repos/{REPO}/actions/runs/{rid}", tok)
            show_interesting(tok, detail)


if __name__ == "__main__":
    main()
