# -*- coding: utf-8 -*-
"""Background watcher for the CI test run. Writes the final status + filtered
log lines to _testrun_result.txt so the terminal does not have to poll."""
import io
import re
import sys
import time
import zipfile

sys.path.insert(0, r"C:\youtube_pipeline")
import check_actions as C

OUT = r"C:\youtube_pipeline\_testrun_result.txt"
RID = 36848791596

tok = C.github_token()
status = "in_progress"
for _ in range(120):  # up to ~60 min
    try:
        d = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/{RID}", tok)
        status = d["status"]
        if status == "completed":
            break
    except Exception as e:
        status = f"poll error: {e}"
    time.sleep(30)

lines = [f"final status: {status}"]
try:
    d = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/{RID}", tok)
    lines.append(f"conclusion: {d['conclusion']}")
    blob = C.api(
        f"https://api.github.com/repos/{C.REPO}/actions/runs/{RID}/logs", tok, raw=True
    )
    zf = zipfile.ZipFile(io.BytesIO(blob))
    pat = re.compile(
        r"(deps OK|\[long\]|Traceback|ERROR|Error|uploaded|duration|scenes"
        r"|placeholder|exit code|##\[error\])"
    )
    for name in zf.namelist():
        if name.endswith("/") or "system" in name:
            continue
        text = zf.read(name).decode("utf-8", "replace")
        lines.append("===== " + name)
        for line in text.splitlines():
            if pat.search(line):
                lines.append(line[:260])
except Exception as e:
    lines.append(f"log fetch failed: {e}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
