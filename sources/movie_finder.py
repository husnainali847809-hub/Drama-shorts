import requests
from sources.license_checker import license_is_allowed

IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/{}"
HEADERS = {"User-Agent": "MovieReelsPublisher/1.0 (rights-filtered film source tool)"}

ANIMATION_TERMS = (
    "animation", "animated", "cartoon", "anime", "puppet animation",
    "stop motion", "stop-motion", "children's cartoon"
)
NON_MOVIE_TERMS = (
    "general strike", "strike", "protest", "demonstration", "news report",
    "newsreel", "press conference", "election", "campaign rally",
    "lecture", "classroom", "tutorial", "how to", "sports match",
    "football match", "concert", "music video", "advertisement",
    "commercial", "industrial film", "government film", "training film",
    "meeting", "meeting recording", "conference", "webinar", "module",
    "lecture recording", "seminar", "presentation", "eudamed", "generalstreik",
    "general strike", "town hall", "committee session", "class recording",
    "course material", "educational recording", "workshop"
)
FILM_SIGNALS = (
    "feature film", "motion picture", "fiction film", "feature-length",
    "movie", "cinema", "film", "drama", "comedy", "romance",
    "thriller", "western", "horror", "action film"
)

def _text(value):
    if isinstance(value, (list, tuple)):
        return " ".join(str(part) for part in value)
    if isinstance(value, dict):
        return " ".join(str(part) for part in value.values())
    return str(value or "")

def _metadata_text(metadata, fallback_title=""):
    keys = ("title", "description", "subject", "collection", "genre", "type", "language")
    parts = [_text(metadata.get(key, "")) for key in keys]
    parts.append(_text(fallback_title))
    return " ".join(parts).lower()

def looks_animated(metadata, fallback_title=""):
    searchable = _metadata_text(metadata, fallback_title)
    return any(term in searchable for term in ANIMATION_TERMS)

def looks_like_non_movie(metadata, fallback_title=""):
    searchable = _metadata_text(metadata, fallback_title)
    return any(term in searchable for term in NON_MOVIE_TERMS)

def has_film_metadata(metadata, fallback_title=""):
    searchable = _metadata_text(metadata, fallback_title)
    return any(term in searchable for term in FILM_SIGNALS)


MIN_RELEASE_YEAR = 2008
MIN_SOURCE_WIDTH = 1920
MIN_SOURCE_HEIGHT = 1080
MIN_SOURCE_BITRATE = 2_000_000


def _release_year(metadata):
    # Prefer explicit release/publication year fields. Do not use Archive upload
    # timestamps as a substitute for a film's release year.
    for key in ("release_year", "year", "date", "issued", "year_published"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            value = " ".join(str(part) for part in value)
        match = __import__("re").search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", str(value or ""))
        if match:
            return int(match.group(1))
    return None


def search_movies(rows=30):
    params = {
        "q": 'mediatype:movies AND (licenseurl:"https://creativecommons.org/publicdomain/mark/1.0/" '
             'OR licenseurl:"https://creativecommons.org/publicdomain/zero/1.0/" '
             'OR licenseurl:"https://creativecommons.org/licenses/by/4.0/")',
        "fl[]": ["identifier", "title", "licenseurl", "creator", "date"],
        "rows": rows,
        "page": 1,
        "output": "json",
    }
    response = requests.get(IA_SEARCH, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    docs = response.json().get("response", {}).get("docs", [])
    candidates = []

    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        title = str(doc.get("title") or identifier)

        try:
            metadata_response = requests.get(
                IA_METADATA.format(identifier), headers=HEADERS, timeout=30
            )
            metadata_response.raise_for_status()
            record = metadata_response.json()
        except (requests.RequestException, ValueError):
            continue

        metadata = record.get("metadata", {})
        license_url = metadata.get("licenseurl") or doc.get("licenseurl") or ""
        if not license_is_allowed(license_url):
            continue

        # Reject known animation and non-film material, including news and events.
        if looks_animated(metadata, title) or looks_like_non_movie(metadata, title):
            continue

        # Keep the catalog focused on releases from 2008 onward. Missing/ambiguous years
        # are rejected; Archive upload dates are never treated as release dates.
        release_year = _release_year(metadata)
        if release_year is None or release_year < MIN_RELEASE_YEAR:
            continue

        # Require explicit film/movie-style metadata. This reduces unrelated archive
        # videos but cannot establish popularity or prove blockbuster status.
        if not has_film_metadata(metadata, title):
            continue

        files = record.get("files", [])
        # Archive often omits width/height/bitrate in its metadata API.
        # Do not reject a potentially good encode based on missing metadata here;
        # main.py probes the actual downloaded file with ffprobe before editing.
        mp4s = []
        for file_info in files:
            name = str(file_info.get("name", ""))
            try:
                size = int(file_info.get("size", 0))
            except (TypeError, ValueError):
                continue
            if (
                name.lower().endswith(".mp4")
                and size > 0
                and size <= 800 * 1024 * 1024
                and not file_info.get("private")
            ):
                mp4s.append({**file_info, "_size": size})
        if not mp4s:
            continue

        # Prefer the largest available MP4 as a rough pre-download heuristic.
        # Actual resolution and bitrate are verified after download.
        chosen = max(mp4s, key=lambda item: item["_size"])
        candidates.append({
            "identifier": identifier,
            "title": title,
            "creator": _text(metadata.get("creator") or doc.get("creator") or "Unknown"),
            "license_url": license_url,
            "date": _text(metadata.get("date") or doc.get("date") or ""),
            "release_year": release_year,
            "file_name": chosen["name"],
            "file_size": chosen["_size"],
            "download_url": (
                f"https://archive.org/download/{identifier}/"
                f"{requests.utils.quote(chosen['name'])}"
            ),
            "details_url": f"https://archive.org/details/{identifier}",
        })

    return candidates
