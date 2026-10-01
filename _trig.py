import json, sys, urllib.request
sys.path.insert(0, r"C:\youtube_pipeline")
import check_actions as C
tok = C.github_token()
url = f"https://api.github.com/repos/{C.REPO}/actions/workflows/scheduled_longform.yml/dispatches"
payload = {"ref": "main", "inputs": {"topic": "", "upload": "true"}}
req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
    headers={"Authorization": f"token {tok}", "Accept": "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "padiz"})
with urllib.request.urlopen(req, timeout=30) as r:
    print("dispatch status:", r.status, "(204 = accepted)")
