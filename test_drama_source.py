"""Read-only diagnostics for alternative, openly accessible video sources.

This workflow only searches APIs and checks whether candidate media URLs respond.
It does not download, edit, upload, or publish any video. A reachable file is not
automatically reusable: a clear license or direct permission is still required.
"""
import os
import sys
from urllib.parse import quote

import requests

TIMEOUT = 25
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "VideoSourceDiagnostics/1.0 (read-only source availability check)"
})


def log(message):
    print(f"[SourceTest] {message}", flush=True)


def check_media_url(url):
    """Check reachability without saving media; some hosts reject HEAD."""
    if not url or not str(url).startswith("https://"):
        return False, "No HTTPS media URL"
    try:
        response = SESSION.head(url, allow_redirects=True, timeout=TIMEOUT)
        if response.status_code in (403, 405, 501) or response.status_code >= 500:
            response.close()
            response = SESSION.get(
                url, headers={"Range": "bytes=0-0"},
                stream=True, allow_redirects=True, timeout=TIMEOUT
            )
        status = response.status_code
        content_type = response.headers.get("Content-Type", "")
        content_length = response.headers.get("Content-Length", "")
        response.close()
        if status in (200, 206):
            return True, f"HTTP {status}; type={content_type or 'unknown'}; size={content_length or 'unknown'}"
        return False, f"HTTP {status}"
    except requests.RequestException as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:180]}"


def test_pexels():
    log("Checking Pexels API...")
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        log("SKIP Pexels: add optional GitHub secret PEXELS_API_KEY to enable API search.")
        return 0
    try:
        response = SESSION.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": api_key},
            params={"query": "cricket sports action", "per_page": 5},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        videos = response.json().get("videos", [])
        log(f"Pexels returned {len(videos)} result(s).")
        for video in videos[:5]:
            files = sorted(
                video.get("video_files", []),
                key=lambda item: (item.get("width") or 0, item.get("height") or 0),
                reverse=True,
            )
            candidate = next((item for item in files if item.get("link")), None)
            if not candidate:
                continue
            ok, detail = check_media_url(candidate["link"])
            log(
                f"Pexels video id={video.get('id')} "
                f"duration={video.get('duration')}s reachable={ok}: {detail}"
            )
            if ok:
                log("Pexels candidate found. Check the Pexels license before reuse.")
                return 1
        log("Pexels: no reachable video file found in the returned results.")
    except (requests.RequestException, ValueError, KeyError) as exc:
        log(f"Pexels ERROR: {type(exc).__name__}: {str(exc)[:240]}")
    return 0


def test_pixabay():
    log("Checking Pixabay API...")
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        log("SKIP Pixabay: add optional GitHub secret PIXABAY_API_KEY to enable API search.")
        return 0
    try:
        response = SESSION.get(
            "https://pixabay.com/api/videos/",
            params={"key": api_key, "q": "cricket sports action", "per_page": 5},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        hits = response.json().get("hits", [])
        log(f"Pixabay returned {len(hits)} result(s).")
        for hit in hits[:5]:
            variants = hit.get("videos", {})
            candidate = next(
                (variants.get(size, {}).get("url")
                 for size in ("large", "medium", "small", "tiny")
                 if variants.get(size, {}).get("url")),
                None,
            )
            if not candidate:
                continue
            ok, detail = check_media_url(candidate)
            log(
                f"Pixabay video id={hit.get('id')} duration={hit.get('duration')}s "
                f"reachable={ok}: {detail}"
            )
            if ok:
                log("Pixabay candidate found. Check the Pixabay license before reuse.")
                return 1
        log("Pixabay: no reachable video file found in the returned results.")
    except (requests.RequestException, ValueError, KeyError) as exc:
        log(f"Pixabay ERROR: {type(exc).__name__}: {str(exc)[:240]}")
    return 0


def test_internet_archive():
    log("Checking Internet Archive public metadata...")
    queries = [
        'mediatype:movies AND subject:cricket',
        'mediatype:movies AND subject:sports',
        'mediatype:movies AND (subject:public domain OR subject:public-domain)',
    ]
    seen = set()
    checked = 0
    for query in queries:
        try:
            response = SESSION.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": query,
                    "fl[]": ["identifier", "title"],
                    "rows": 8,
                    "page": 1,
                    "output": "json",
                },
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            docs = response.json().get("response", {}).get("docs", [])
        except (requests.RequestException, ValueError) as exc:
            log(f"Internet Archive search ERROR: {type(exc).__name__}: {str(exc)[:180]}")
            continue

        for doc in docs:
            identifier = str(doc.get("identifier", "")).strip()
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            checked += 1
            try:
                metadata_response = SESSION.get(
                    f"https://archive.org/metadata/{quote(identifier, safe='')}",
                    timeout=TIMEOUT,
                )
                metadata_response.raise_for_status()
                metadata = metadata_response.json().get("metadata", {})
                files = metadata_response.json().get("files", [])
            except (requests.RequestException, ValueError) as exc:
                log(f"Internet Archive item {identifier}: metadata unavailable ({str(exc)[:140]}).")
                continue

            license_url = str(metadata.get("licenseurl") or metadata.get("license_url") or "").strip()
            rights_text = str(metadata.get("rights") or "").strip()
            mp4 = next(
                (item for item in files
                 if str(item.get("name", "")).lower().endswith(".mp4")
                 and item.get("size") and int(item.get("size", 0) or 0) > 0),
                None,
            )
            if not mp4:
                continue
            media_url = (
                "https://archive.org/download/"
                + quote(identifier, safe="")
                + "/"
                + quote(str(mp4["name"]), safe="/")
            )
            ok, detail = check_media_url(media_url)
            clearly_licensed = bool(license_url or rights_text)
            log(
                f"Internet Archive item={identifier} mp4={mp4.get('name')} "
                f"reachable={ok} explicit_rights_metadata={clearly_licensed} "
                f"license={license_url or rights_text or 'not stated'}; {detail}"
            )
            if ok and clearly_licensed:
                log("Internet Archive candidate found; manually verify item-level rights and license terms.")
                return 1
    log(f"Internet Archive: checked {checked} item(s); no candidate passed both reachability and rights-metadata checks.")
    return 0


def test_wikimedia_cricket():
    log("Checking Wikimedia Commons cricket video category...")
    endpoint = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "generator": "categorymembers",
        "gcmtitle": "Category:Videos_of_cricket",
        "gcmtype": "file",
        "gcmlimit": 20,
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
    }
    try:
        response = SESSION.get(endpoint, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
    except (requests.RequestException, ValueError) as exc:
        log(f"Wikimedia ERROR: {type(exc).__name__}: {str(exc)[:220]}")
        return 0

    checked = 0
    for page in pages.values():
        info_list = page.get("imageinfo", [])
        if not info_list:
            continue
        info = info_list[0]
        if not str(info.get("mime", "")).startswith("video/"):
            continue
        checked += 1
        metadata = info.get("extmetadata", {})
        license_name = str(metadata.get("LicenseShortName", {}).get("value", "")).strip()
        license_url = str(metadata.get("LicenseUrl", {}).get("value", "")).strip()
        title = page.get("title", "untitled")
        media_url = info.get("url", "")
        ok, detail = check_media_url(media_url)
        clearly_licensed = bool(license_name and license_url)
        log(
            f"Wikimedia file={title} license={license_name or 'not stated'} "
            f"license_url={license_url or 'not stated'} reachable={ok}; {detail}"
        )
        if ok and clearly_licensed:
            log("Wikimedia candidate found; preserve required attribution and follow its exact license.")
            return 1
    log(f"Wikimedia: checked {checked} video file(s); no candidate passed reachability and license checks.")
    return 0


def main():
    log("Read-only source test started. No media will be downloaded or published.")
    results = {
        "Pexels": test_pexels(),
        "Pixabay": test_pixabay(),
        "Internet Archive": test_internet_archive(),
        "Wikimedia Commons": test_wikimedia_cricket(),
    }
    log("Summary: " + ", ".join(
        f"{name}={'CANDIDATE FOUND' if passed else 'NO VERIFIED CANDIDATE'}"
        for name, passed in results.items()
    ))
    log("A candidate is only a technical/licensing lead, not automatic permission to republish.")
    if any(results.values()):
        log("PASS: at least one source exposed a reachable candidate with rights metadata.")
        return 0
    log("No source passed both availability and rights-metadata checks. No download or publishing was attempted.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
