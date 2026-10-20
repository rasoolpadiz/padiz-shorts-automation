# -*- coding: utf-8 -*-
"""Delete every transient render/upload artifact AFTER a successful upload,
keeping ONLY the state files that must survive (posted_shorts.json,
longform_out/posted_long.json). Owner directive 2026-10-09: no video archives
on the server - free the disk immediately.

Safe by construction:
  - runs from a known repo path
  - only touches video/image/cache dirs, never source .py, token, or state json
  - is idempotent (missing dirs are fine)
  - logs what it freed

Usage:  python cleanup_artifacts.py [--dry-run]
"""
import os
import sys
import shutil

REPO = os.path.dirname(os.path.abspath(__file__))
DRY = "--dry-run" in sys.argv

# Never delete these (source of truth / credentials).
KEEP_FILES = {
    "posted_shorts.json",
    "longform_out/posted_long.json",
}

# Transient directories to wipe entirely.
WIPE_DIRS = [
    "temp_render",       # short clips/png/mp3/srt
    "short_out",         # manual short artifacts (legacy)
    "longform_images",   # cached scene photos for long videos
]

# Merged repost pipeline (2026-10-20): downloaded Shorts are the biggest files
# this repo ever holds, and repost.py already deletes each one right after a
# successful upload. This sweeps whatever a crash/failed upload left behind,
# while keeping the state + index + logs that make the run auditable.
REPOST_DIR = "repost_out"
REPOST_KEEP_SUFFIX = {".csv", ".json", ".txt", ".log"}
REPOST_KEEP_NAMES = {".download_archive.txt", "candidates.json", "index.json",
                     "index.csv", "report.html"}


def clean_repost_out():
    d = os.path.join(REPO, REPOST_DIR)
    if not os.path.isdir(d):
        return
    for root, dirs, files in os.walk(d):
        if os.path.basename(root) == "logs":
            dirs[:] = []
            continue
        for name in files:
            if name in REPOST_KEEP_NAMES:
                continue
            if os.path.splitext(name)[1].lower() in REPOST_KEEP_SUFFIX:
                continue
            try:
                _rm(os.path.join(root, name))
            except Exception as e:
                print(f"  [skip] {name}: {e}")

# Files inside longform_out to delete (all *.mp4, *.jpg thumbnails, per-topic
# folders), EXCEPT posted_long.json which is the state file.
def clean_longform_out():
    d = os.path.join(REPO, "longform_out")
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if name == "posted_long.json":
            continue
        try:
            if os.path.isdir(p):
                _rmtree(p)
            elif name.endswith((".mp4", ".jpg", ".png", ".json")):
                _rm(p)
        except Exception as e:
            print(f"  [skip] {name}: {e}")

def _rm(p):
    size = _size(p)
    if DRY:
        print(f"  [dry] would delete file {p} ({size/1e6:.1f}MB)")
    else:
        os.remove(p)
        print(f"  deleted file {p} ({size/1e6:.1f}MB)")

def _rmtree(p):
    size = _size(p)
    if DRY:
        print(f"  [dry] would delete dir  {p} ({size/1e6:.1f}MB)")
    else:
        shutil.rmtree(p, ignore_errors=True)
        print(f"  deleted dir  {p} ({size/1e6:.1f}MB)")

def _size(p):
    if os.path.isfile(p):
        return os.path.getsize(p)
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total

def main():
    print(f"cleanup_artifacts ({'DRY-RUN' if DRY else 'LIVE'}) in {REPO}")
    for d in WIPE_DIRS:
        p = os.path.join(REPO, d)
        if os.path.exists(p):
            _rmtree(p)
        else:
            print(f"  (absent) {d}")
    clean_longform_out()
    clean_repost_out()
    # leftover short_*.mp4 / short_*_music.mp4 at repo root
    for name in os.listdir(REPO):
        if name.endswith(".mp4"):
            _rm(os.path.join(REPO, name))
    print("cleanup done.")

if __name__ == "__main__":
    main()
