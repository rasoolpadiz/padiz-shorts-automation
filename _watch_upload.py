# -*- coding: utf-8 -*-
"""Wait for the long-form upload run and dump the lines that matter."""
import io
import re
import sys
import time
import zipfile

sys.path.insert(0, r"C:\youtube_pipeline")
import check_actions as C

RID = 36899272116
tok = C.github_token()

status = "in_progress"
d = {}
for _ in range(90):
    try:
        d = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/{RID}", tok)
        status = d["status"]
        if status == "completed":
            break
    except Exception as exc:
        status = f"poll error: {exc}"
    time.sleep(10)

out = [f"run {RID}", f"status: {status}", f"conclusion: {d.get('conclusion')}"]
try:
    blob = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/{RID}/logs", tok, raw=True)
    zf = zipfile.ZipFile(io.BytesIO(blob))
    for name in zf.namelist():
        if name.endswith("/") or "system" in name:
            continue
        text = zf.read(name).decode("utf-8", "replace")
        if "Build + upload" not in name:
            continue
        out.append("===== " + name)
        for line in text.splitlines():
            if re.search(r"(\[long\]|\[gen\]|\[analytics\]|uploaded|Traceback|##\[error\]|"
                         r"thumbnail|done:|scenes|already published|nothing to do)", line):
                out.append(line.split("Z ", 1)[-1][:230])
except Exception as exc:
    out.append(f"log fetch failed: {exc}")

with open(r"C:\youtube_pipeline\_upload_run.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
