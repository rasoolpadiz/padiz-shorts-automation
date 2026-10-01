#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except:
    pass

os.environ['GEMINI_API_KEY'] = 'AQ.Ab8RN6IV6tTvBOHJOvC8tgmigDM6cWQ0JnpbOokBMM6RbNBRWg'

import gen_topics

print("\n" + "="*60)
print("🔥 GENERATING TRENDING TOPIC: Deep Sea Mysteries")
print("="*60)

# Generate a trending topic based on discovery
topic = gen_topics.build_topic('en', niche='History', dry_run=False)

print(f"\n✅ موضوع تولید شد:")
print(f"  📌 ID: {topic.get('id')}")
print(f"  📝 عنوان: {topic.get('title')}")
print(f"  🎬 صحنه‌ها: {len(topic.get('scenes', []))}")
print(f"  🎤 Hook: {topic.get('hook')[:80]}...")
print(f"  ⚠️  Fallback: {topic.get('fallback')} (Template: {topic.get('fallback')})")

print("\n" + "="*60)
print("اکنون فیلم را می‌سازیم و آپلود می‌کنیم...")
print("="*60)
