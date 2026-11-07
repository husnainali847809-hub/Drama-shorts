"""Discover full-length cartoon video candidates from public catalogs.

This module records source links and declared license metadata only. It never
downloads YouTube videos, bypasses access controls, approves rights, or publishes.
"""
import os
import re
from urllib.parse import quote

import requests

IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/"
YT_API = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"
MIN_VIDEO_SECONDS = 180
IA_QUERIES = [
    "animated cartoon",
    "cartoon full movie",
    "animated feature film",
    "animated fairy tale",
    "public domain cartoon",
    "classic animated film",
    "family animation",
    "animated story",
]

LICENSE_MAP = {
    "creativecommons.org/licenses/by/4.0": "CC-BY-4.0",
    "creativecommons.org/licenses/by-sa/4.0": "CC-BY-SA-4.0",
    "creativecommons.org/publicdomain/zero/1.0": "CC0-1.0",
    "creativecommons.org/publicdomain/mark/1.0": "PDM-1.0",
}


def _text(value):
    if isinstance(value, list):
        value = " ".join(str(x) for x in value)
    return re.sub(r"\\s+", " ", str(value or "")).strip()[:1200]


def _license(value):
    raw = _text(value).lower().replace("http://", "https://")
    for needle, code in LICENSE_MAP.items():
        if needle in raw:
            return code
    return None


def _duration(value):
    try:
        if value in (None, ""):
            return None
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def discover_internet_archive(limit=15, queries=None, min_duration=MIN_VIDEO_SECONDS):
    """Search broad Internet Archive movie records; return candidates and source errors."""
    found = {}
    terms = queries or IA_QUERIES
    for term in terms:
        params = {
            "q": f'mediatype:movies AND "{term}"',
            "fl[]": ["identifier", "title", "creator", "licenseurl", "description", "year"],
            "rows": min(max(limit * 4, 20), 100),
            "page": 1,
            "output": "json",
        }
        try:
            response = requests.get(
                IA_SEARCH, params=params, timeout=(10, 25),
                headers={"User-Agent": "AnimalsAIContentDiscovery/1.3"},
            )
            response.raise_for_status()
            docs = response.json().get("response", {}).get("docs", [])
        except Exception as exc:
            found[f"error:{term}"] = {
                "_source_error": {"source": "Internet Archive", "error": str(exc)[:500], "query": term}
            }
            continue

        for doc in docs:
            identifier = _text(doc.get("identifier"))
            if not identifier or identifier in found:
                continue
            metadata_url = IA_METADATA + quote(identifier, safe="")
            item = {
                "title": _text(doc.get("title")) or identifier,
                "creator": _text(doc.get("creator")) or "Creator not clearly listed",
                "source": "Internet Archive",
                "source_page_url": f"https://archive.org/details/{quote(identifier, safe='')}",
                "metadata_url": metadata_url,
                "license": _license(doc.get("licenseurl")),
                "license_url": _text(doc.get("licenseurl")),
                "year": _text(doc.get("year")),
                "description": _text(doc.get("description")),
                "matched_search": term,
                "rights_status": "candidate_only_human_review_required",
                "worldwide_rights_confirmed": False,
                "commercial_use_and_modifications": "verify exact license and embedded music, voices, characters and footage",
                "download_url": None,
                "duration_seconds": None,
                "duration_status": "unknown_manual_check_required",
            }
            try:
                meta_response = requests.get(
                    metadata_url, timeout=(10, 25),
                    headers={"User-Agent": "AnimalsAIContentDiscovery/1.3"},
                )
                meta_response.raise_for_status()
                files = meta_response.json().get("files", [])
                video_files = []
                for file_info in files:
                    name = str(file_info.get("name", ""))
                    if name.lower().endswith((".mp4", ".webm", ".ogv", ".mov", ".m4v")):
                        duration = _duration(file_info.get("length"))
                        if duration is not None and duration < min_duration:
                            continue
                        video_files.append((file_info, duration))
                video_files.sort(
                    key=lambda pair: (pair[1] or 0, int(pair[0].get("size", 0) or 0)),
                    reverse=True,
                )
                if video_files:
                    selected, duration = video_files[0]
                    item["download_url"] = (
                        f"https://archive.org/download/{quote(identifier, safe='')}/"
                        f"{quote(str(selected.get('name', '')), safe='/')}"
                    )
                    item["duration_seconds"] = duration
                    item["duration_status"] = (
                        "meets_minimum_duration" if duration is not None
                        else "duration_unknown_manual_check_required"
                    )
            except Exception as exc:
                item["metadata_error"] = str(exc)[:400]
            if item["download_url"]:
                found[identifier] = item
            if len([x for x in found.values() if "_source_error" not in x]) >= limit:
                break
        if len([x for x in found.values() if "_source_error" not in x]) >= limit:
            break

    results = list(found.values())
    candidates = [x for x in results if "_source_error" not in x][:limit]
    errors = [x for x in results if "_source_error" in x]
    return errors + candidates


def discover_youtube_creative_commons(limit=10, queries=None):
    """Use YouTube Data API's CC filter; never downloads YouTube video files."""
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        return {
            "status": "not_configured",
            "notice": "YOUTUBE_API_KEY is optional; other public sources still run.",
            "candidates": [],
        }
    candidates = {}
    for term in (queries or ["animated cartoon full episode", "classic animated film", "animated fairy tale"]):
        try:
            response = requests.get(YT_API, params={
                "part": "snippet", "type": "video", "videoLicense": "creativeCommon",
                "q": term, "maxResults": min(max(limit, 1), 50), "key": key,
            }, timeout=(10, 25))
            response.raise_for_status()
            items = response.json().get("items", [])
            ids = [x.get("id", {}).get("videoId") for x in items if x.get("id", {}).get("videoId")]
            if not ids:
                continue
            details = requests.get(YT_VIDEOS_API, params={
                "part": "snippet,contentDetails,status", "id": ",".join(ids), "key": key,
            }, timeout=(10, 25))
            details.raise_for_status()
            for video in details.json().get("items", []):
                vid = video.get("id")
                snippet = video.get("snippet", {})
                status = video.get("status", {})
                if not vid or status.get("license") != "creativeCommon":
                    continue
                candidates[vid] = {
                    "title": _text(snippet.get("title")),
                    "creator": _text(snippet.get("channelTitle")) or "Channel not listed",
                    "source": "YouTube",
                    "source_page_url": f"https://www.youtube.com/watch?v={vid}",
                    "license": "CC-BY-4.0",
                    "license_label_from_source": "Creative Commons Attribution",
                    "matched_search": term,
                    "published_at": snippet.get("publishedAt"),
                    "duration_iso8601": video.get("contentDetails", {}).get("duration"),
                    "rights_status": "candidate_only_human_review_required",
                    "worldwide_rights_confirmed": False,
                    "download_url": None,
                    "notice": "API license label is a lead only; verify embedded rights. Use permitted YouTube features or obtain the creator's source file.",
                }
                if len(candidates) >= limit:
                    break
        except Exception as exc:
            return {"status": "error", "notice": str(exc)[:500], "candidates": list(candidates.values())}
        if len(candidates) >= limit:
            break
    return {
        "status": "searched",
        "notice": "Creative Commons API results are candidates only; no video files were downloaded.",
        "candidates": list(candidates.values())[:limit],
    }
