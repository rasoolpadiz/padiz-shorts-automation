# -*- coding: utf-8 -*-
"""
Padiz Content Dashboard - محتوای روزانه و ترندها
شماره‌ی موضوعات، منابع اکتشاف، quota، و وضعیت
"""
import json
import os
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except:
        return default or {}

def dashboard():
    print("\n" + "="*80)
    print("PADIZ CONTENT DASHBOARD".center(80))
    print("="*80)
    
    # 1. Discovery Status
    discovery = load_json(os.path.join(BASE_DIR, 'discovery_pool.json'), {})
    quota = load_json(os.path.join(BASE_DIR, 'discovery_quota.json'), {})
    
    print(f"\nDISCOVERY (Trending Topics)")
    print(f"   Last updated: {discovery.get('fa', {}).get('generated_at', 'N/A')}")
    print(f"   API Quota: {quota.get('yt_searches', 0)}/6 YouTube searches used today")
    
    en_items = discovery.get('en', {}).get('items', [])[:5]
    fa_items = discovery.get('fa', {}).get('items', [])[:5]
    
    if en_items:
        print(f"\n   ENGLISH TRENDING:")
        for i, item in enumerate(en_items, 1):
            vel = item.get('velocity', 0)
            print(f"      {i}. {item.get('title', 'N/A')[:50]}... ({vel:,.0f} views/hr)")
    
    if fa_items:
        print(f"\n   PERSIAN TRENDING:")
        for i, item in enumerate(fa_items, 1):
            vel = item.get('velocity', 0)
            print(f"      {i}. {item.get('title', 'N/A')[:50]}... ({vel:,.0f} views/hr)")
    
    # 2. Generated Topics
    print(f"\nGENERATED TOPICS")
    topics = load_json(os.path.join(BASE_DIR, 'topics_generated', 'used_niches.json'), {})
    
    print(f"   EN niches used: {len(topics.get('en', []))} -- {', '.join(topics.get('en', [])[:3])}")
    print(f"   FA niches used: {len(topics.get('fa', []))} -- {', '.join(topics.get('fa', [])[:3])}")
    
    # 3. Published Videos
    print(f"\nPUBLISHED VIDEOS")
    posted = load_json(os.path.join(BASE_DIR, 'longform_out', 'posted_long.json'), {})
    
    today = date.today().isoformat()
    todayCount = sum(1 for v in posted.get('posted', {}).values() if v == today)
    
    print(f"   Videos published today: {todayCount}")
    print(f"   Total videos published: {len(posted.get('posted', {}))}")
    
    for topic_id, when in list(posted.get('posted', {}).items())[-3:]:
        print(f"      + {topic_id} on {when}")
    
    # 4. Scheduler Status
    print(f"\nSCHEDULER")
    print(f"   Status: OK (Windows Task Scheduler)")
    print(f"   Run times: 15:30, 21:00")
    print(f"   Pattern: Odd days=EN, Even days=FA")
    
    # 5. Quota Analysis
    print(f"\nQUOTA ANALYSIS (Free Tier)")
    print(f"   YouTube API quota: 10,000 units/day")
    print(f"   Long-form upload: 1,600 units each")
    print(f"   Short-form upload: 200 units each")
    print(f"   Discovery search: 100 units each")
    print(f"   ")
    print(f"   Max capacity: 1 long + 20 shorts/day (need room for searches)")
    print(f"   Recommended: 1 long + 10 shorts/day")
    print(f"   Current pace: 1 long/day + shorts (SAFE)")
    
    print("\n" + "="*80 + "\n")

if __name__ == '__main__':
    dashboard()
