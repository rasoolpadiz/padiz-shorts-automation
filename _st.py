import sys; sys.path.insert(0, r'C:\youtube_pipeline')
import check_actions as C
tok = C.github_token()
d = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/36848791596", tok)
print('status:', d['status'], '| conclusion:', d['conclusion'])
