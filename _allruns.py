import sys
sys.path.insert(0, r"C:\youtube_pipeline")
import check_actions as C
tok = C.github_token()
# every run in the repo today (any workflow)
runs = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs?per_page=20", tok)
print("workflow           event             status       conclusion   created")
print("-" * 84)
for r in runs.get("workflow_runs", []):
    print(f"{r['name'][:18]:18} {r['event']:17} {r['status']:12} {str(r['conclusion']):12} {r['created_at']}")
