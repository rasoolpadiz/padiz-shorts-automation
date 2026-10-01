import sys, json
sys.path.insert(0, r"C:\youtube_pipeline")
import check_actions as C
tok = C.github_token()
wf = "scheduled_longform.yml"
info = C.api(f"https://api.github.com/repos/{C.REPO}/actions/workflows/{wf}", tok)
print("state:", info.get("state"))
print("created:", info.get("created_at"))
print("updated:", info.get("updated_at"))
runs = C.api(f"https://api.github.com/repos/{C.REPO}/actions/workflows/{wf}/runs?per_page=8", tok)
print("--- runs ---")
for r in runs.get("workflow_runs", []):
    print(r["id"], r["event"], r["status"], r["conclusion"], r["created_at"])
