# -*- coding: utf-8 -*-
import io, sys, zipfile
sys.path.insert(0, r'C:\youtube_pipeline')
import check_actions as C
tok = C.github_token()
blob = C.api(f"https://api.github.com/repos/{C.REPO}/actions/runs/36848791596/logs", tok, raw=True)
zf = zipfile.ZipFile(io.BytesIO(blob))
name = [n for n in zf.namelist() if n.endswith('.txt') and 'system' not in n and n.startswith('0_')][0]
text = zf.read(name).decode('utf-8','replace')
out = []
for l in text.splitlines():
    if '[img]' in l or '[long]' in l:
        # strip timestamp prefix
        out.append(l.split('Z ',1)[-1] if 'Z ' in l else l)
open(r'C:\youtube_pipeline\_imglog.txt','w',encoding='utf-8').write('\n'.join(out))
print('img/long lines:', len(out))
