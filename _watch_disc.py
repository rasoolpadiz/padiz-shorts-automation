# -*- coding: utf-8 -*-
"""Wait for the analytics+discovery workflow and dump its filtered log."""
import io
import re
import sys
import time
import zipfile

sys.path.insert(0, r"C:\youtube_pipeline")
import check_actions as C

tok = C.github_token()
runs = C.api(
    f"https://api.github.com/repos/{C.REPO}/actions/workflows/scheduled_analytics.yml/runs?per_page=1",
    tok,
)["workflow_runs"]
rid = runs[0]["id"]

status = "in_progress"
for _ in range(60):
    d = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/{rid}", tok)
    status = d["status"]
    if status == "completed":
        break
    time.sleep(10)

out = [f"run {rid}", f"status: {status}", f"conclusion: {d['conclusion']}"]
try:
    blob = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/{rid}/logs", tok, raw=True)
    zf = zipfile.ZipFile(io.BytesIO(blob))
    for name in zf.namelist():
        if name.endswith("/") or "system" in name:
            continue
        text = zf.read(name).decode("utf-8", "replace")
        if "Discover hot topics" not in name and "Collect channel" not in name:
            continue
        for line in text.splitlines():
            if re.search(r"(\[analytics\]|\[discover\]|heat=|Traceback|##\[error\]|"
                         r"::warning::|No change|snapshot|discovery pool)", line):
                out.append(line.split("Z ", 1)[-1][:220])
except Exception as exc:
    out.append(f"log fetch failed: {exc}")

with open(r"C:\youtube_pipeline\_disc_run.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
