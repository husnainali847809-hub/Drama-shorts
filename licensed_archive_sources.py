"""Discover openly licensed Pakistani/Urdu drama videos on Internet Archive.

Only CC0 and Public Domain Mark items are considered. Internet Archive metadata
is uploader-supplied, so rights metadata is a screening signal, not a legal
guarantee; operators should still review the item page before enabling reuse.
"""
import re
import shutil
import subprocess
from urllib.parse import quote

import requests

SEARCH_URL = "https://archive.org/advancedsearch.php"
HEADERS = {"User-Agent": "DramaClipSourceDiscovery/1.0 (authorized-media-only)"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_LICENSE_MARKERS = (
    "creativecommons.org/publicdomain/zero/1.0",
    "creativecommons.org/publicdomain/mark/1.0",
)


def _is_open_license(value):
    license_url = str(value or "").strip().lower()
    return any(marker in license_url for marker in ALLOWED_LICENSE_MARKERS)


def discover_latest(seen_ids=None, rows=50):
    """Return the newest eligible Pakistani/Urdu drama item with a video file."""
    seen_ids = set(seen_ids or [])
    query = (
        "mediatype:movies AND "
        "(title:Pakistani OR title:Pakistan OR title:Urdu OR "
        "subject:Pakistani OR subject:Pakistan OR subject:Urdu OR "
        "description:Pakistani OR description:Pakistan OR description:Urdu)"
    )
    response = requests.get(
        SEARCH_URL,
        params={
            "q": query,
            "fl[]": ["identifier", "title", "date"],
            "rows": max(1, min(int(rows), 100)),
            "page": 1,
            "output": "json",
            "sort[]": "date desc",
        },
        headers=HEADERS,
        timeout=35,
    )
    response.raise_for_status()
    docs = response.json().get("response", {}).get("docs", [])
    for doc in docs:
        identifier = str(doc.get("identifier", "")).strip()
        if not identifier or identifier in seen_ids or f"archive:{identifier}" in seen_ids:
            continue
        metadata_response = requests.get(
            f"https://archive.org/metadata/{quote(identifier, safe='')}",
            headers=HEADERS,
            timeout=30,
        )
        metadata_response.raise_for_status()
        item = metadata_response.json()
        meta = item.get("metadata") or {}
        if not _is_open_license(meta.get("licenseurl")):
            continue

        searchable = " ".join(
            str(meta.get(key, "")) for key in ("title", "description", "subject", "creator")
        ).lower()
        if not re.search(r"pakistan|pakistani|urdu", searchable):
            continue
        if not re.search(r"drama|serial|television|tv show", searchable):
            continue

        candidates = []
        for file_info in item.get("files", []):
            name = str(file_info.get("name", ""))
            suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if suffix not in VIDEO_EXTENSIONS:
                continue
            if file_info.get("source") not in (None, "", "original"):
                continue
            if str(file_info.get("private", "")).lower() in {"true", "1"}:
                continue
            try:
                size = int(file_info.get("size", 0))
            except (TypeError, ValueError):
                continue
            if size < 1_000_000 or size > MAX_FILE_BYTES:
                continue
            candidates.append((0 if suffix == ".mp4" else 1, size, name))
        if not candidates:
            continue
        candidates.sort()
        filename = candidates[0][2]
        return {
            "id": f"archive:{identifier}",
            "archive_identifier": identifier,
            "url": f"https://archive.org/download/{quote(identifier, safe='')}/{quote(filename, safe='')}",
            "title": str(meta.get("title") or doc.get("title") or "Openly licensed Urdu drama"),
            "license": str(meta.get("licenseurl")),
            "filename": filename,
        }
    return None


def get_stream(candidate, clip_seconds):
    """Probe an openly downloadable Archive.org file without fetching the full episode."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required to inspect direct video files (install FFmpeg).")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", candidate["url"],
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffprobe could not read the file")[-400:]
        raise RuntimeError(f"Archive.org video is not directly readable: {detail}")
    try:
        duration = float(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        duration = 0.0
    if duration <= float(clip_seconds) + 5:
        raise RuntimeError("Archive.org video is shorter than the required clip length.")
    return {
        "url": candidate["url"],
        "headers": {},
        "duration": duration,
        "title": candidate["title"],
    }
