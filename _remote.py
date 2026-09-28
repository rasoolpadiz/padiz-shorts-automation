# -*- coding: utf-8 -*-
"""اجرای یک دستور روی سرور از طریق SSH (برای عیب‌یابی).

    $env:PADIZ_SSH_PASSWORD='...'
    python _remote.py "<shell command>"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from deploy_viral_server import Remote  # noqa: E402

host = os.environ.get("PADIZ_HOST", "188.40.180.124")
user = os.environ.get("PADIZ_USER", "root")
password = os.environ["PADIZ_SSH_PASSWORD"]

argv = sys.argv[1:]
use_script = False
if argv and argv[0] == "--script":
    use_script = True
    argv = argv[1:]

remote = Remote(host, user, password)
try:
    if use_script:
        local_path, command = argv[0], (argv[1] if len(argv) > 1 else "bash /tmp/_padiz_task.sh")
        # خط‌های ویندوز (CRLF) نباید به bash برسند
        with open(local_path, "r", encoding="utf-8") as src:
            body = src.read().replace("\r\n", "\n").replace("\r", "\n")
        with remote.sftp.open("/tmp/_padiz_task.sh", "w") as dst:
            dst.write(body)
        remote.run(f"chmod +x /tmp/_padiz_task.sh && {command}", timeout=900)
        remote.run("rm -f /tmp/_padiz_task.sh")
    else:
        remote.run(" ".join(argv), timeout=600)
finally:
    remote.close()
