"""Discover full-length cartoon video candidates from Internet Archive and YouTube.

This module only records source links and declared license metadata. It never downloads
YouTube videos, bypasses access controls, or treats a search result as rights clearance.
"""
import os
import re
from urllib.parse import quote

import requests

IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/"
YT_API = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"

LICENSE_MAP = {
    "creativecommons.org/licenses/by/4.0": "CC-BY-4.0",
    "creativecommons.org/licenses/by-sa/4.0": "CC-BY-SA-4.0",
    "creativecommons.org/publicdomain/zero/1.0": "CC0-1.0",
    "creativecommons.org/publicdomain/mark/1.0": "PDM-1.0",
}

def _text(value):
    if isinstance(value, list):
        value = " ".join(str(x) for x in value)
    return re.sub(r"\s+", " ", str(value or "")).strip()[:1200]

def _license(value):
    raw = _text(value).lower().replace("http://", "https://")
    for needle, code in LICENSE_MAP.items():
        if needle in raw:
            return code
    return None

def discover_internet_archive(limit=15, queries=None):
    """Return Internet Archive animation collection candidates; no automatic approval."""
    found = {}
    for term in (queries or ["animated cartoon", "animated fairy tale", "classic cartoon"]):
        params = {
            "q": f'mediatype:movies AND collection:animationandcartoons AND "{term}"',
            "fl[]": ["identifier", "title", "creator", "licenseurl", "description", "year", "collection"],
            "rows": min(max(limit * 3, 10), 50),
            "page": 1,
            "output": "json",
        }
        try:
            response = requests.get(IA_SEARCH, params=params, timeout=(10, 25),
                                   headers={"User-Agent": "AnimalsAIContentDiscovery/1.2"})
            response.raise_for_status()
            docs = response.json().get("response", {}).get("docs", [])
        except Exception as exc:
            yield {"_source_error": {"source": "Internet Archive", "error": str(exc)[:500]}}
            continue
        for doc in docs:
            identifier = _text(doc.get("identifier"))
            if not identifier or identifier in found:
                continue
            license_code = _license(doc.get("licenseurl"))
            metadata_url = IA_METADATA + quote(identifier, safe="")
            item = {
                "title": _text(doc.get("title")) or identifier,
                "creator": _text(doc.get("creator")) or "Creator not clearly listed",
                "source": "Internet Archive",
                "source_page_url": f"https://archive.org/details/{quote(identifier, safe='')}",
                "metadata_url": metadata_url,
                "license": license_code,
                "license_url": _text(doc.get("licenseurl")),
                "year": _text(doc.get("year")),
                "description": _text(doc.get("description")),
                "matched_search": term,
                "rights_status": "candidate_only_human_review_required" if license_code else "license_not_recognized_manual_review_required",
                "worldwide_rights_confirmed": False,
                "commercial_use_and_modifications": "verify exact license and embedded music, voices, characters and footage",
                "download_url": None,
                "duration_seconds": None,
            }
            try:
                meta_response = requests.get(metadata_url, timeout=(10, 25),
                                             headers={"User-Agent": "AnimalsAIContentDiscovery/1.2"})
                meta_response.raise_for_status()
                metadata = meta_response.json()
                files = metadata.get("files", [])
                video_files = [f for f in files if str(f.get("name", "")).lower().endswith(
                    (".mp4", ".webm", ".ogv", ".mov", ".m4v"))]
                video_files.sort(key=lambda f: (int(f.get("size", 0) or 0), f.get("name", "")), reverse=True)
                if video_files:
                    selected = video_files[0]
                    item["download_url"] = (
                        f"https://archive.org/download/{quote(identifier, safe='')}/"
                        f"{quote(str(selected.get('name', '')), safe='/')}"
                    )
                    try:
                        item["duration_seconds"] = float(selected.get("length") or 0) or None
                    except (TypeError, ValueError):
                        pass
            except Exception as exc:
                item["metadata_error"] = str(exc)[:400]
            if item["download_url"]:
                found[identifier] = item
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break
    return list(found.values())[:limit]

def discover_youtube_creative_commons(limit=10, queries=None):
    """Use YouTube Data API's Creative Commons filter; does not download video files."""
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        return {"status": "not_configured", "notice": "Set YOUTUBE_API_KEY to enable YouTube API discovery.", "candidates": []}
    candidates = {}
    for term in (queries or ["animated cartoon", "cartoon full episode", "animated fairy tale"]):
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
                    "notice": "YouTube API reports Creative Commons; this does not authorize downloading through third-party tools or prove rights to embedded music/characters. Use permitted YouTube features or obtain the creator's source file.",
                }
                if len(candidates) >= limit:
                    break
        except Exception as exc:
            return {"status": "error", "notice": str(exc)[:500], "candidates": list(candidates.values())}
        if len(candidates) >= limit:
            break
    return {"status": "searched", "notice": "Creative Commons API results are candidates only; no video files were downloaded.", "candidates": list(candidates.values())[:limit]}
