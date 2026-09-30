# -*- coding: utf-8 -*-
"""Fetch commercially-safe photos for long-form scenes.

Only CC0 / Public-Domain images are accepted, so the channel can be monetized with
zero copyright risk. Sources (no API key needed):
  1) Openverse  (license=cc0,pdm)
  2) Wikimedia Commons (licence filtered to CC0 / Public domain)

Images are cached inside the repo (longform_images/<topic>/scene_NN.jpg) together with
a credits json, so GitHub runs never depend on the network for visuals.
"""
import json
import os
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_ROOT = os.path.join(BASE_DIR, "longform_images")
UA_JSON = "PadizStudioBot/1.0 (educational video automation; contact: local)"
UA_IMG = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

OPENVERSE = "https://api.openverse.org/v1/images/"
COMMONS = "https://commons.wikimedia.org/w/api.php"

# Global, persistent registry of every photo already used on the channel.
# Owner directive 2026-09-30: "هیچ چیز تکراری نباشه" - a photo must never appear
# twice, not even in the EN and FA version of the same topic. The old code reset
# `used = set()` on every run, which is why both money videos shared ~all imagery.
USED_IMAGES_PATH = os.path.join(IMG_ROOT, "_used_images.json")

_last_api_call = [0.0]          # throttle for Wikimedia (avoids HTTP 429)

# Wikimedia/Openverse are full of diagrams, charts, scans and maps. They look like
# lecture slides inside a video, so anything matching these words is rejected.
# Single words are matched on word boundaries (otherwise "graph" kills "photograph").
_BAD_WORDS = (
    "diagram", "chart", "charts", "map", "maps", "logo", "icon", "icons", "seal",
    "poster", "screenshot", "scan", "scans", "table", "infographic", "scheme",
    "topographic", "timeline", "cover", "stamp", "panel", "panels", "comics",
    "plaque", "inscription", "cuneiform", "hieroglyph", "manuscript", "form",
    "page", "pages", "list", "file", "symbol", "glyph", "illustration",
)
_BAD_PHRASES = (
    "coat of arms", "title page", "list of", "sketch map", "newspaper", "periodical",
    "journal", "magazine", "book cover", "label of", "flag of", "map of",
)


def _title_is_usable(title):
    """Reject diagrams/charts/scans - we want cinematic photography, not documents."""
    import re
    low = str(title or "").lower()
    if any(p in low for p in _BAD_PHRASES):
        return False
    tokens = set(re.split(r"[^a-z0-9]+", low))
    return not (tokens & set(_BAD_WORDS))


def load_used_registry():
    """Read the channel-wide used-image hashes."""
    try:
        with open(USED_IMAGES_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_used_registry(hashes):
    os.makedirs(IMG_ROOT, exist_ok=True)
    with open(USED_IMAGES_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(hashes), f, indent=1)


def _log(msg):
    """Print safely - Windows consoles choke on non-ascii credits."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def _get(url, timeout=25, tries=3):
    last = None
    for attempt in range(tries):
        # Wikimedia asks for polite pacing between API calls.
        wait = 1.2 - (time.time() - _last_api_call[0])
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={
            "User-Agent": UA_JSON, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                _last_api_call[0] = time.time()
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            last = e
            if "429" in str(e) or "503" in str(e):
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
    raise last


def _download(url, out_path):
    headers = {
        "User-Agent": UA_IMG,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if "wikimedia.org" in url or "wikipedia.org" in url:
        headers["Referer"] = "https://commons.wikimedia.org/"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    if len(data) < 12000:          # too small to be a usable 16:9 photo
        return False
    is_jpeg = data[:3] == b"\xff\xd8\xff"
    is_png = data[:4] == b"\x89PNG"
    is_webp = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if not (is_jpeg or is_png or is_webp):
        return False
    with open(out_path, "wb") as f:
        f.write(data)
    return True


def _openverse(query, limit=8):
    params = urllib.parse.urlencode({
        "q": query, "license": "cc0,pdm", "page_size": limit,
        "mature": "false", "aspect_ratio": "wide",
    })
    try:
        data = _get(f"{OPENVERSE}?{params}")
    except Exception as e:
        _log(f"  [img] openverse failed ({e})")
        return []
    out = []
    for item in data.get("results", []):
        if not _title_is_usable(item.get("title")):
            continue
        # Direct source URLs often 403; Openverse's own thumb proxy is reliable.
        thumb = item.get("thumbnail")
        url = f"{thumb}?full_size=true" if thumb else item.get("url")
        if url:
            out.append((url, f"Openverse/{item.get('license', 'cc0')}/{item.get('creator') or 'unknown'}"))
    return out


def _clean_html(value):
    import re
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return " ".join(text.split())[:80] or "unknown"


def _commons(query, limit=10):
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": limit,
        "gsrnamespace": "6", "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": "1920",
    })
    try:
        data = _get(f"{COMMONS}?{params}")
    except Exception as e:
        _log(f"  [img] commons failed ({e})")
        return []
    out = []
    for page in (data.get("query", {}).get("pages") or {}).values():
        if not _title_is_usable(page.get("title")):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName", {}) or {}).get("value", "").lower()
        if not url:
            continue
        # Monetization-safe licenses only (CC0 / public domain).
        safe = any(k in lic for k in
                   ("cc0", "cc-zero", "public domain", "pdm", "no restrictions")) \
            or lic.strip() in ("pd", "pd-1996", "cc pdm 1.0")
        if not safe:
            continue
        artist = _clean_html((meta.get("Artist", {}) or {}).get("value"))
        out.append((url, f"Wikimedia/{lic or 'pd'}/{artist}"))
    return out


def _photo_looks_fine(path):
    """Reject low-res, wrongly-shaped or document/scan-looking images.

    Commons happily returns 300px thumbnails and black-and-white scans. Those read
    as broken slides on screen, so they are rejected before they enter the video.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            # Free photo sources (Openverse, Wikimedia) cap most results near
            # 1024px on the long edge. 1100 rejected perfectly good 16:9 photos
            # and left whole videos with no artwork at all, so the floor is 1024.
            if w < 1024 or h < 576:
                return False, f"too small ({w}x{h})"
            ratio = w / h
            if not (1.25 <= ratio <= 2.7):
                return False, f"bad aspect ({ratio:.2f})"
            small = im.convert("RGB").resize((160, 90))
            pixels = list(small.getdata())
            # Near-uniform colour = synthetic graphic, not a photograph.
            avg = sum(sum(p) for p in pixels) / (len(pixels) * 3)
            spread = sum(abs(sum(p) / 3 - avg) for p in pixels) / len(pixels)
            if spread < 13:
                return False, f"flat graphic (spread {spread:.1f})"
            return True, "ok"
    except Exception as e:
        return False, f"unreadable ({e})"


def fetch_scene_image(topic_id, scene_idx, query, force=False, used_hashes=None):
    """Download one safe photo for a scene and return its path (or None)."""
    import hashlib

    folder = os.path.join(IMG_ROOT, topic_id)
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, f"scene_{scene_idx:02d}.jpg")
    credit_path = os.path.join(folder, f"scene_{scene_idx:02d}.credit.txt")
    used_hashes = used_hashes if used_hashes is not None else set()

    def _digest(path):
        try:
            with open(path, "rb") as fh:
                return hashlib.md5(fh.read()).hexdigest()
        except OSError:
            return None

    if os.path.exists(out_path) and not force:
        # Cached hit - but reject it if an earlier scene or another video uses it.
        cached = _digest(out_path)
        if cached and cached not in used_hashes:
            ok, why = _photo_looks_fine(out_path)
            if ok:
                used_hashes.add(cached)
                return out_path
            _log(f"  [img] cached scene {scene_idx} rejected: {why} -> refetching")
        elif cached:
            os.remove(out_path)          # duplicate cache -> re-download

    # Scene-specific words first; broader variants only as fallbacks.
    words = str(query).split()
    attempts = []
    if words:
        attempts.append(" ".join(words[:5]))
    if len(words) > 2:
        attempts.append(" ".join(words[:2]))
    if len(words) > 5:
        attempts.append(" ".join(words))
    if not attempts:
        attempts.append(topic_id.replace("_", " "))
    attempts = list(dict.fromkeys(attempts))       # keep order, drop dups

    for provider in (_commons, _openverse):
        for q in attempts:
            for url, credit in provider(q):
                try:
                    if not _download(url, out_path):
                        continue
                    ok, why = _photo_looks_fine(out_path)
                    if not ok:
                        _log(f"  [img] scene {scene_idx}: rejected - {why}")
                        os.remove(out_path)
                        continue
                    digest = _digest(out_path)
                    if not digest:
                        continue
                    if digest in used_hashes:
                        os.remove(out_path)          # every scene gets a different photo
                        continue
                    used_hashes.add(digest)
                    with open(credit_path, "w", encoding="utf-8") as f:
                        f.write(f"{credit}\n{url}\n{q}\n")
                    _log(f"  [img] scene {scene_idx}: {credit}")
                    return out_path
                except Exception as e:
                    _log(f"  [img] download failed ({e})")
    _log(f"  [img] scene {scene_idx}: no free image found for '{query}'")
    return None


def fetch_topic_images(topic, extra_used=None):
    """Fetch a photo for every scene (cached). Returns {scene_idx: path}.

    `extra_used` lets a caller reserve hashes before this topic runs. The channel-wide
    registry is loaded and saved so no photo is ever reused on a later video.
    """
    mapping = {}
    used = load_used_registry()
    if extra_used:
        used |= set(extra_used)
    for idx, scene in enumerate(topic.get("scenes", []), start=1):
        query = scene.get("image_query") or f"{scene.get('title', '')} {topic.get('series', '')}".strip()
        path = fetch_scene_image(topic["id"], idx, query, used_hashes=used)
        if path:
            mapping[idx] = path
    save_used_registry(used)
    _log(f"  [img] {len(mapping)}/{len(topic.get('scenes', []))} photos ready, "
         f"{len(used)} images used channel-wide")
    return mapping
