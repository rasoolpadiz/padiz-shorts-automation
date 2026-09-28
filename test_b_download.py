# -*- coding: utf-8 -*-
"""
TEST B - Download (fully standalone).

  YouTube URL/Video ID -> yt-dlp -> MP4 on disk.
  Prints sha256 + size on success; logs the exact client and failure
  reason per attempt on failure.

Proves the PO-token chain layer by layer:

  Layer 1: provider really mints a token (direct POST /get_pot)
  Layer 2: yt-dlp really fetches a token ([pot] lines in verbose log)
  Layer 3: token accepted - format URL answers ([download] progress)
  Layer 4: a real MP4 lands on disk (size + sha256)

Stops at the first client that works (no infinite retries) and writes
test_b_result.json for CI summaries.

Usage:
  python test_b_download.py
  python test_b_download.py --video-id dQw4w9WgXcQ
  python test_b_download.py --url "https://..."
"""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_PATH = os.path.join(BASE_DIR, "test_b_result.json")
LOG_DIR = os.path.join(BASE_DIR, "test_b_logs")

# "Me at the zoo" - the oldest, most stable YouTube video; ideal canary.
DEFAULT_VIDEO_ID = "jNQXAC9IVRw"

# Same order the pipeline uses: mweb first per the official PO-Token guide.
ATTEMPTS = [
    ("mweb", ["mweb"]),
    ("web", ["web"]),
    ("tv", ["tv"]),
    ("default", None),
    ("android", ["android"]),
    ("tv_embedded", ["tv_embedded"]),
    ("web_embedded", ["web_embedded"]),
]

BGUTIL_BASE_URL = os.environ.get("BGUTIL_URL", "http://127.0.0.1:4416").rstrip("/")

# Evidence markers: verbose-log lines showing a PO token was registered,
# fetched, or used.
POT_MARKERS = re.compile(r"\[pot\]|PO [Tt]oken|bgutil|getpot|wpc", re.I)

# Failure classification so the log says WHERE it broke.
FAILURE_KINDS = [
    ("BOT_CHECK", r"Sign in to confirm you're not a bot"),
    ("BOT_CHECK", r"Sign in to confirm you\u2019re not a bot"),
    ("FORMAT", r"Requested format is not available"),
    ("GVS_403", r"HTTP Error 403"),
    ("GVS_403", r"returned HTTP 403"),
    ("NO_VIDEO", r"Video unavailable"),
    ("AGE", r"age-restricted"),
    ("TIMEOUT", r"timed? ?out|socket.timeout"),
]


def classify_failure(log_text):
    for kind, pattern in FAILURE_KINDS:
        if re.search(pattern, log_text):
            return kind
    return "OTHER"


def cookies_file():
    """Same cookie precedence as viral_hunter: env file > env b64 > local file."""
    env_file = os.environ.get("YT_COOKIES_FILE")
    if env_file and os.path.exists(env_file):
        return env_file
    path = os.path.join(BASE_DIR, "yt_cookies.txt")
    b64 = os.environ.get("YT_COOKIES_B64")
    if b64 and not os.path.exists(path):
        try:
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(b64))
        except Exception as exc:  # noqa: BLE001
            print(f"[test-b] could not decode YT_COOKIES_B64: {exc}")
    return path if os.path.exists(path) else None


def probe_provider_direct():
    """Layer 1: ask the bgutil server itself for a token (no yt-dlp involved).

    GET  /ping    -> server is alive
    POST /get_pot -> actually mints a proof-of-origin token
    """
    info = {
        "url": BGUTIL_BASE_URL,
        "reachable": False,
        "token_minted": False,
        "version": None,
        "error": None,
        "response_keys": [],
        "token_length": 0,
    }
    try:
        import urllib.request

        with urllib.request.urlopen(f"{BGUTIL_BASE_URL}/ping", timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        info["reachable"] = True
        info["version"] = body.get("version")

        payload = json.dumps(
            {
                "content_binding": f"test-b-{uuid.uuid4().hex[:12]}",
                "bypass_cache": True,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{BGUTIL_BASE_URL}/get_pot",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        info["response_keys"] = sorted(body.keys())
        token = body.get("po_token") or body.get("pot") or ""
        if isinstance(token, str) and token:
            token = token.split("=", 1)[-1]
        info["token_length"] = len(token)
        info["token_minted"] = info["token_length"] > 0
        if not info["token_minted"]:
            info["error"] = f"server answered but no token field: {body}"
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def run_attempt(label, clients, url, output_path, log_path):
    """Run one yt-dlp attempt as a subprocess; capture the verbose log."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-v",
        "--no-warnings",
        "--no-part",
        "--newline",
        "--format",
        "best[ext=mp4][height<=1920]/bestvideo[height<=1920]+bestaudio/best",
        "--merge-output-format", "mp4",
        "--output", output_path,
        "--no-playlist",
        "--retries", "2",
        "--socket-timeout", "30",
    ]
    if clients:
        cmd += ["--extractor-args", f"youtube:player_client={','.join(clients)}"]

    browser_path = os.environ.get("WPC_BROWSER_PATH", "").strip()
    if browser_path:
        cmd += ["--extractor-args", f"youtubepot-wpc:browser_path={browser_path}"]

    proxy = os.environ.get("YT_PROXY", "").strip()
    if proxy:
        cmd += ["--proxy", proxy]

    cookie = cookies_file()
    if cookie:
        cmd += ["--cookies", cookie]

    cmd.append(url)

    started = time.time()
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    elapsed = round(time.time() - started, 1)
    log_text = proc.stdout or ""

    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(log_text)

    pot_lines = [ln.strip() for ln in log_text.splitlines() if POT_MARKERS.search(ln)]
    download_lines = [
        ln.strip()
        for ln in log_text.splitlines()
        if ln.startswith("[download]") and "Destination" not in ln
    ]

    ok = (
        proc.returncode == 0
        and os.path.exists(output_path)
        and os.path.getsize(output_path) > 0
    )
    if not ok:
        for leftover in (output_path + ".part", output_path):
            if os.path.exists(leftover) and os.path.getsize(leftover) == 0:
                try:
                    os.remove(leftover)
                except OSError:
                    pass

    return {
        "label": label,
        "clients": clients,
        "ok": ok,
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "failure_kind": None if ok else classify_failure(log_text),
        "error_tail": None
        if ok
        else " | ".join(
            ln.strip() for ln in log_text.splitlines() if ln.strip()
        )[-600:],
        "pot_evidence": pot_lines[:25],
        "download_evidence": download_lines[-5:],
        "log_file": os.path.basename(log_path),
    }

def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description="TEST B: Video ID -> MP4")
    parser.add_argument("--video-id", default=DEFAULT_VIDEO_ID)
    parser.add_argument("--url", default=None)
    parser.add_argument("--out", default=None, help="output mp4 path")
    args = parser.parse_args(argv)

    url = args.url or f"https://www.youtube.com/watch?v={args.video_id}"
    output_path = args.out or os.path.join(BASE_DIR, f"test_b_{args.video_id}.mp4")
    os.makedirs(LOG_DIR, exist_ok=True)

    result = {
        "test": "B",
        "name": "video_id->mp4",
        "pass": False,
        "url": url,
        "provider_direct": None,
        "attempts": [],
        "file": None,
    }

    print(f"[test-b] target: {url}")
    print("[test-b] layer 1: provider direct token mint ...")
    provider = probe_provider_direct()
    result["provider_direct"] = provider
    if provider["reachable"]:
        print(
            f"  provider alive (version={provider['version']}), "
            f"get_pot -> token_minted={provider['token_minted']} "
            f"len={provider['token_length']}"
        )
        if not provider["token_minted"]:
            print(f"  provider error: {provider['error']}")
    else:
        print(f"  provider not reachable at {provider['url']} ({provider['error']})")
        print("  (not fatal: the wpc browser provider needs no server)")

    print("[test-b] layers 2-4: per-client yt-dlp attempts ...")
    for label, clients in ATTEMPTS:
        if os.path.exists(output_path):
            os.remove(output_path)
        log_path = os.path.join(LOG_DIR, f"attempt_{label}.log")
        print(f"  attempt '{label}' ...")
        try:
            attempt = run_attempt(label, clients, url, output_path, log_path)
        except subprocess.TimeoutExpired:
            attempt = {
                "label": label,
                "clients": clients,
                "ok": False,
                "returncode": None,
                "elapsed_sec": 300,
                "failure_kind": "TIMEOUT",
                "error_tail": "yt-dlp subprocess exceeded 300s",
                "pot_evidence": [],
                "download_evidence": [],
                "log_file": os.path.basename(log_path),
            }
        result["attempts"].append(attempt)

        if attempt["ok"]:
            size = os.path.getsize(output_path)
            digest = sha256_of(output_path)
            result["file"] = {
                "path": output_path,
                "size_bytes": size,
                "sha256": digest,
                "client_used": label,
                "elapsed_sec": attempt["elapsed_sec"],
            }
            result["pass"] = True
            print(f"  attempt '{label}' OK in {attempt['elapsed_sec']}s")
            print(f"  pot evidence lines: {len(attempt['pot_evidence'])}")
            for line in attempt["pot_evidence"][:8]:
                print(f"    {line[:200]}")
            break

        pot_n = len(attempt["pot_evidence"])
        print(
            f"  attempt '{label}' FAILED "
            f"[{attempt['failure_kind']}] pot_lines={pot_n} "
            f"log={attempt['log_file']}"
        )
        if pot_n:
            for line in attempt["pot_evidence"][:4]:
                print(f"    {line[:200]}")
        else:
            print("    no PO-token evidence in the verbose log "
                  "(provider never engaged)")



    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print("=" * 60)
    if result["pass"]:
        f = result["file"]
        print("TEST B PASS")
        print(f"  client : {f['client_used']}")
        print(f"  path   : {f['path']}")
        print(f"  size   : {f['size_bytes']} bytes")
        print(f"  sha256 : {f['sha256']}")
    else:
        print("TEST B FAIL")
        for attempt in result["attempts"]:
            print(
                f"  client={attempt['label']:<15} "
                f"kind={attempt['failure_kind']:<10} "
                f"pot_lines={len(attempt['pot_evidence'])} "
                f"log={attempt['log_file']}"
            )
    print(f"  result -> {RESULT_PATH}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
