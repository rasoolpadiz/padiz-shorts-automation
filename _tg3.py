import sys
sys.path.insert(0, r'C:\youtube_pipeline')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import gen_shorts as G
import pipeline as P
t = G.load_generated()[0]
print('slides are pool-shaped:', all(set(s) >= {'title','text','speech'} for s in t['slides']))
print('has lang/music/voice_index:', t.get('lang'), '|', t.get('music'), '|', t.get('voice_index'))
print('bg track ->', P.bg_track_for(dict(t, id=t['id'])) or '(empty, but render continues)')
print('voices_for len:', len(P.voices_for(dict(t, id=t['id']))))
