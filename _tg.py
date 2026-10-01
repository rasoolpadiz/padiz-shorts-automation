import sys
sys.path.insert(0, r'C:\youtube_pipeline')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import gen_shorts as G
# dry run: needs NO gemini, NO disk write. discovery comes from today cache.
item = G.build_short('fa', dry_run=True)
if item:
    print('FA generated:', item['id'])
    print('title:', item['title'][:70])
    print('niche:', item['niche'])
    print('fallback:', item['fallback'])
    for s in item['slides']:
        print(f"  - [{s['title'][:26]:26}] speech words: {len(s['speech'].split())}")
else:
    print('FA: nothing (no discovery or all covered)')
item2 = G.build_short('en', dry_run=True)
if item2:
    print('EN generated:', item2['id'])
    print('title:', item2['title'][:70])
    print('fallback:', item2['fallback'])
else:
    print('EN: nothing (no discovery or all covered)')
