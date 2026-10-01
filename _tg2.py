# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r'C:\youtube_pipeline')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import gen_shorts as G
# REAL save (no gemini key locally -> template), no upload
item = G.build_short('fa')
print('saved:', item and item['id'], '| fallback:', item and item['fallback'])
print('generated now:', len(G.load_generated()))
for t in G.load_generated():
    print('  ', t['id'], '| valid:', G._valid(t, t['lang']))
