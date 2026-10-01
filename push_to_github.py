# Auto-push script to GitHub repo
# Usage: python push_to_github.py <YOUR_GITHUB_PAT>
import sys, os, subprocess, base64

if len(sys.argv) < 2:
    print('Usage: python push_to_github.py <YOUR_GITHUB_PAT>')
    sys.exit(1)

pat = sys.argv[1].strip()
repo_url = f'https://rasoolpadiz:{pat}@github.com/rasoolpadiz/padiz-shorts-automation.git'
git_exe = r'C:\Program Files\Git\cmd\git.exe'

subprocess.run([git_exe, 'init'], cwd=r'C:\youtube_pipeline', check=True)
subprocess.run([git_exe, 'config', 'user.name', 'Rasool Padiz'], cwd=r'C:\youtube_pipeline', check=True)
subprocess.run([git_exe, 'config', 'user.email', 'rasoolpadiz@gmail.com'], cwd=r'C:\youtube_pipeline', check=True)
subprocess.run([git_exe, 'remote', 'remove', 'origin'], cwd=r'C:\youtube_pipeline')
subprocess.run([git_exe, 'remote', 'add', 'origin', repo_url], cwd=r'C:\youtube_pipeline', check=True)
subprocess.run([git_exe, 'add', 'pipeline.py', 'topics_pool.py', 'requirements.txt', 'run_daily.py', 'insta_reels_pipeline.py', 'Vazirmatn-Bold.ttf', '.github/workflows/scheduled_shorts.yml'], cwd=r'C:\youtube_pipeline', check=True)
subprocess.run([git_exe, 'commit', '-m', 'Fix Persian rendering and expand topics pool across all categories'], cwd=r'C:\youtube_pipeline')
subprocess.run([git_exe, 'branch', '-M', 'main'], cwd=r'C:\youtube_pipeline', check=True)
res = subprocess.run([git_exe, 'push', '-u', 'origin', 'main', '--force'], cwd=r'C:\youtube_pipeline')
if res.returncode == 0:
    print('SUCCESSFULLY PUSHED TO GITHUB!')
else:
    print('Push failed.')
