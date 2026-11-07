"""Discover cartoon videos and popular classic-story sources with rights metadata.

Discovery is research-only: it never downloads or publishes a candidate and never
marks a work as legally approved. A human must review the exact work and every
embedded element before copying a candidate into licensed_assets.json.
"""
import argparse
import html
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
USER_AGENT = "AnimalsAIContentDiscovery/1.1 (rights-review workflow)"
DISCOVERY_WARNINGS = []
SESSION = requests.Session()
RETRY_POLICY = Retry(
    total=2,
    connect=2,
    read=1,
    status=2,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)
ADAPTER = HTTPAdapter(max_retries=RETRY_POLICY)
SESSION.mount("https://", ADAPTER)
SESSION.mount("http://", ADAPTER)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
GUTENDEX_API = "https://gutendex.com/books/"
VIDEO_LICENSES = {
    "cc0 1.0": "CC0-1.0",
    "cc by 4.0": "CC-BY-4.0",
    "cc by-sa 4.0": "CC-BY-SA-4.0",
    "public domain mark 1.0": "PDM-1.0",
}
STORY_SEARCHES = (
    "children fairy tales",
    "fables",
    "folk tales",
    "classic adventure stories",
    "myths legends",
)
CARTOON_SEARCHES = (
    "animated cartoon",
    "cartoon short film",
    "traditional animation film",
    "animated fairy tale",
)
# These are discovery/search names only. They are not licensed assets and must
# never be downloaded or published unless the exact work is independently cleared.
REFERENCE_ONLY_FRANCHISES = (
    "Motu Patlu",
    "Chhota Bheem",
    "Tom and Jerry",
    "Doraemon",
    "Shinchan",
    "Oggy and the Cockroaches",
    "The Jungle Book (cartoon adaptations)",
)
CLASSIC_STORY_SEARCHES = (
    "Cinderella",
    "Alice's Adventures in Wonderland",
    "The Adventures of Pinocchio",
    "The Wonderful Wizard of Oz",
    "Peter Pan",
    "The Jungle Book",
    "Snow White",
    "Hansel and Gretel",
    "The Three Little Pigs",
    "Robin Hood",
    "The Little Mermaid",
    "Arabian Nights",
)


def clean(value, limit=500):
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def get_json(url, params=None):
    try:
        response = SESSION.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=(10, 25),
        )
        response.raise_for_status()
        time.sleep(1.0)  # Be polite to public APIs and reduce HTTP 429 responses.
        return response.json()
    except Exception as exc:
        DISCOVERY_WARNINGS.append({"source": url, "error": str(exc)[:500]})
        logging.warning("Discovery request failed after retries: %s | %s", url, exc)
        return {}


def normalize_video_license(short_name):
    return VIDEO_LICENSES.get(clean(short_name).lower())


def discover_cartoon_videos(limit=15, queries=None):
    """Find Commons video files with recognized reuse-friendly license labels."""
    found = {}
    for term in dict.fromkeys(queries or CARTOON_SEARCHES):
        data = get_json(COMMONS_API, {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:video {term}",
            "gsrnamespace": 6,
            "gsrlimit": min(max(limit * 2, 10), 50),
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
        })
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            title = clean(page.get("title"), 180)
            info_list = page.get("imageinfo") or []
            if not info_list:
                continue
            info = info_list[0]
            mime = str(info.get("mime", "")).lower()
            if not mime.startswith("video/"):
                continue
            metadata = info.get("extmetadata") or {}

            def meta(key):
                value = metadata.get(key, {})
                return clean(value.get("value") if isinstance(value, dict) else value, 800)

            short_license = meta("LicenseShortName")
            normalized = normalize_video_license(short_license)
            if not normalized:
                continue
            page_id = page.get("pageid")
            page_url = f"https://commons.wikimedia.org/wiki/{quote(str(page.get('title', '')).replace(' ', '_'))}"
            found[str(page_id or title)] = {
                "title": title,
                "search_term": term,
                "creator": meta("Artist") or meta("Credit") or "Creator not clearly listed",
                "source_page_url": page_url,
                "video_url": info.get("url", ""),
                "mime_type": mime,
                "license": normalized,
                "license_label_from_source": short_license,
                "license_url": meta("LicenseUrl"),
                "description": meta("ImageDescription"),
                "rights_status": "candidate_only_human_review_required",
                "commercial_use_and_modifications": "generally permitted by this license; verify exact work and embedded elements",
                "worldwide_rights_confirmed": False,
                "share_alike_obligation": normalized == "CC-BY-SA-4.0",
                "duration_check_required": True,
            }
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break
    return list(found.values())[:limit]


def discover_story_sources(limit=20, searches=None):
    """Find popular classic story texts; Gutenberg jurisdiction must be reviewed."""
    found = {}
    for term in dict.fromkeys(searches or STORY_SEARCHES):
        data = get_json(GUTENDEX_API, {"search": term, "page": 1})
        for book in data.get("results", []):
            book_id = book.get("id")
            if not book_id or str(book_id) in found:
                continue
            formats = book.get("formats") or {}
            text_url = (
                formats.get("text/plain; charset=utf-8")
                or formats.get("text/plain; charset=us-ascii")
                or formats.get("text/plain")
            )
            found[str(book_id)] = {
                "gutenberg_id": book_id,
                "title": clean(book.get("title"), 180),
                "matched_search": term,
                "authors": [clean(a.get("name"), 120) for a in book.get("authors", [])],
                "subjects": [clean(s, 100) for s in book.get("subjects", [])[:8]],
                "download_count": int(book.get("download_count") or 0),
                "source_page_url": f"https://www.gutenberg.org/ebooks/{book_id}",
                "text_url": text_url,
                "rights_status": "US_public_domain_catalog_candidate_only",
                "worldwide_rights_confirmed": False,
                "review_note": "Project Gutenberg distribution is based on US copyright status; verify the story, translation, edition and local law before worldwide commercial adaptation.",
            }
        if len(found) >= limit * 3:
            break
    books = sorted(found.values(), key=lambda item: item["download_count"], reverse=True)
    return books[:limit]


def build_report(limit=15, franchise="all", story="all"):
    if franchise != "all" and franchise not in REFERENCE_ONLY_FRANCHISES:
        raise ValueError(f"Unknown cartoon franchise search: {franchise}")
    if story != "all" and story not in CLASSIC_STORY_SEARCHES:
        raise ValueError(f"Unknown classic story search: {story}")
    franchise_queries = list(REFERENCE_ONLY_FRANCHISES) if franchise == "all" else [franchise]
    story_queries = list(CLASSIC_STORY_SEARCHES) if story == "all" else [story]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_franchise": franchise,
        "selected_story": story,
        "notice": (
            "Discovery results are candidates, not legal clearance. Nothing is downloaded, "
            "added to the approved manifest, or published automatically."
        ),
        "cartoon_video_candidates": [],
        "story_based_cartoon_video_candidates": [],
        "popular_story_source_candidates": [],
        "franchise_searches": [],
        "reference_only_copyrighted_franchises": [
            {
                "name": name,
                "status": "do_not_download_or_reupload_without_rightsholder_permission",
                "note": "Search reference only; no permission or reuse license is implied.",
            }
            for name in REFERENCE_ONLY_FRANCHISES
        ],
        "source_errors": [],
    }
    stories = []
    try:
        gutenberg_queries = (story_queries if story != "all" else []) + list(STORY_SEARCHES[:3])
        stories = discover_story_sources(limit, searches=list(dict.fromkeys(gutenberg_queries)))
        report["popular_story_source_candidates"] = stories
        logging.info("Project Gutenberg story sources: %s candidate(s)", len(stories))
    except Exception as exc:
        logging.exception("Project Gutenberg story discovery failed")
        report["source_errors"].append({"source": "Project Gutenberg story sources", "error": str(exc)[:500]})

    try:
        report["cartoon_video_candidates"] = discover_cartoon_videos(
            limit, queries=list(dict.fromkeys(franchise_queries + list(CARTOON_SEARCHES)))
        )
        logging.info("Wikimedia Commons cartoon videos: %s candidate(s)", len(report["cartoon_video_candidates"]))
        report["franchise_searches"] = [
            {
                "name": name,
                "search_status": "searched_in_commons_for_reuse-friendly_video_metadata",
                "candidate_count": sum(
                    1 for item in report["cartoon_video_candidates"]
                    if item.get("search_term", "").lower() == name.lower()
                ),
                "notice": "This does not locate or authorize official copyrighted episodes."
            }
            for name in franchise_queries
        ]
    except Exception as exc:
        logging.exception("Wikimedia Commons cartoon discovery failed")
        report["source_errors"].append({"source": "Wikimedia Commons cartoon videos", "error": str(exc)[:500]})

    story_titles = [item["title"] for item in stories[:5] if item.get("title")]
    if story_titles:
        try:
            report["story_based_cartoon_video_candidates"] = discover_cartoon_videos(
                limit, queries=story_titles
            )
            logging.info(
                "Story-title-matched cartoon videos: %s candidate(s)",
                len(report["story_based_cartoon_video_candidates"]),
            )
        except Exception as exc:
            logging.exception("Story-title cartoon search failed")
            report["source_errors"].append({"source": "Story-title cartoon videos", "error": str(exc)[:500]})
    report["source_errors"].extend(DISCOVERY_WARNINGS)
    return report

def write_report(report):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    json_path = OUTPUT / f"content-discovery-{stamp}.json"
    md_path = OUTPUT / f"content-discovery-{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Internet cartoon and story discovery",
        "",
        f"Generated: {report['generated_at_utc']}",
        "",
        f"> {report['notice']}",
        "",
        "## Cartoon video candidates (Wikimedia Commons)",
        "",
    ]
    for item in report["cartoon_video_candidates"]:
        lines.extend([
            f"### {item['title']}",
            f"- Creator: {item['creator']}",
            f"- License: {item['license_label_from_source']} ({item['license']})",
            f"- Source: {item['source_page_url']}",
            f"- Direct video: {item['video_url']}",
            "- Status: candidate only; check music, voices, characters, duration and worldwide rights.",
            "",
        ])
    if not report["cartoon_video_candidates"]:
        lines.append("No matching video candidates with recognized license metadata were returned.")
        lines.append("")
    lines.extend(["## Videos matching popular story titles", ""])
    for item in report["story_based_cartoon_video_candidates"]:
        lines.extend([
            f"### {item['title']}",
            f"- Matched story search: {item.get('search_term', 'classic story')}",
            f"- Creator: {item['creator']}",
            f"- License: {item['license_label_from_source']} ({item['license']})",
            f"- Source: {item['source_page_url']}",
            f"- Direct video: {item['video_url']}",
            "- Status: candidate only; verify every embedded right and global reuse terms.",
            "",
        ])
    if not report["story_based_cartoon_video_candidates"]:
        lines.append("No matching story-title videos with recognized license metadata were returned.")
        lines.append("")
    lines.extend(["## Famous cartoon franchise searches (reference only)", ""])
    for item in report.get("franchise_searches", []):
        lines.extend([
            f"### {item['name']}",
            f"- Reuse-friendly Commons candidates matching this name: {item['candidate_count']}",
            f"- Notice: {item['notice']}",
            "",
        ])
    lines.extend(["## Popular classic-story sources (Project Gutenberg)", ""])
    for item in report["popular_story_source_candidates"]:
        authors = ", ".join(item["authors"]) or "Author not listed"
        lines.extend([
            f"### {item['title']}",
            f"- Author(s): {authors}",
            f"- Catalog downloads (rough popularity signal): {item['download_count']}",
            f"- Matched search: {item.get('matched_search', 'classic story')}",
            f"- Source: {item['source_page_url']}",
            f"- Rights note: {item['review_note']}",
            "",
        ])
    if not report["popular_story_source_candidates"]:
        lines.append("No story records were returned.")
        lines.append("")
    lines.extend(["", "## Source errors", ""])
    if report["source_errors"]:
        for error in report["source_errors"]:
            lines.append(f"- {error['source']}: {error['error']}")
    else:
        lines.append("- None")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Discover reusable cartoon video and classic story candidates.")
    parser.add_argument("--limit", type=int, default=15, help="Maximum candidates per source (1-30).")
    parser.add_argument("--franchise", choices=["all", *REFERENCE_ONLY_FRANCHISES], default="all",
                        help="Search a famous cartoon name for openly licensed candidates; never fetches official episodes.")
    parser.add_argument("--story", choices=["all", *CLASSIC_STORY_SEARCHES], default="all",
                        help="Focus story discovery on a famous classic title.")
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error("--limit must be between 1 and 30")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    report = build_report(args.limit, franchise=args.franchise, story=args.story)
    json_path, md_path = write_report(report)
    print(f"Cartoon video candidates: {len(report['cartoon_video_candidates'])}")
    print(f"Popular story candidates: {len(report['popular_story_source_candidates'])}")
    print(f"Report JSON: {json_path}")
    print(f"Report Markdown: {md_path}")
    if report["source_errors"]:
        print("One or more discovery sources failed; see report for details.")


if __name__ == "__main__":
    main()
