# -*- coding: utf-8 -*-
"""دا��نلود کل لاگ یک اجرا و نمایش خطوط موردنظر (برای عیب‌یابی دقیق)."""
import io
import re
import sys
import zipfile

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import check_actions as ca

pattern = sys.argv[1] if len(sys.argv) > 1 else "POT|provider|bgutil|docker|Error|ERROR"
run_id = sys.argv[2] if len(sys.argv) > 2 else "36484557458"

tok = ca.github_token()
logs = ca.run_log_text(tok, run_id)
rx = re.compile(pattern)
for name, text in logs.items():
    print("=" * 70)
    print(name)
    print("=" * 70)
    for line in text.splitlines():
        if rx.search(line):
            print("  ", line.strip()[:220])
