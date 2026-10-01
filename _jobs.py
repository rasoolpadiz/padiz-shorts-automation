import sys, json; sys.path.insert(0, r'C:\youtube_pipeline')
import check_actions as C
tok = C.github_token()
d = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/36848791596/jobs", tok)
for j in d.get('jobs', []):
    print(j['name'], '|', j['status'], '|', j['conclusion'])
    for s in j.get('steps', []):
        print('   ', s['number'], s['name'], '->', s['status'], s['conclusion'])
