#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import json

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except:
    pass

os.environ['GEMINI_API_KEY'] = 'AQ.Ab8RN6IV6tTvBOHJOvC8tgmigDM6cWQ0JnpbOokBMM6RbNBRWg'

import gen_topics

print("[test] تولید موضوع جدید با Gemini...")
topic = gen_topics.build_topic('fa', niche='تصمیم‌گیری', dry_run=False)

print(f"\n[test] موضوع تولید شد:")
print(f"  ID: {topic.get('id')}")
print(f"  عنوان: {topic.get('title')}")
print(f"  Hook: {topic.get('hook')[:100]}...")
print(f"  صحنه‌ها: {len(topic.get('scenes', []))}")
print(f"  Fallback: {topic.get('fallback')}")
