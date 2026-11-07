import re
import unicodedata
import requests
from sources.license_checker import license_is_allowed

IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/{}"
HEADERS = {"User-Agent": "MovieReelsPublisher/1.0 (rights-filtered live-action film source tool)"}

ANIMATION_TERMS = (
    "animation", "animated", "cartoon", "anime", "manga", "puppet animation",
    "stop motion", "stop-motion", "computer animation", "3d animation",
    "animated movie", "animated film", "animation film", "children's cartoon"
)
NON_MOVIE_TERMS = (
    "gameplay", "game play", "video game", "gaming", "boss fight", "boss fights",
    "walkthrough", "playthrough", "let's play", "game trailer", "game footage",
    "fan edit", "fan-made", "remix", "reaction video", "commentary",
    "sub español", "sub espanol", "subtitles", "episode", "season",
    "general strike", "strike", "protest", "demonstration", "news report",
    "newsreel", "press conference", "election", "campaign rally",
    "lecture", "classroom", "tutorial", "how to", "sports match",
    "football match", "concert", "music video", "advertisement",
    "commercial", "industrial film", "government film", "training film",
    "meeting", "meeting recording", "conference", "webinar", "module",
    "lecture recording", "seminar", "presentation", "eudamed", "generalstreik",
    "town hall", "committee session", "class recording", "course material",
    "educational recording", "workshop", "commission", "sewer",
    "city council", "public hearing", "board meeting", "municipal",
    "township", "agenda", "meeting minutes", "livestream", "live stream",
    "webcast", "recorded session", "public access"
)

STRONG_FILM_SIGNALS = (
    "feature film", "feature-length film", "feature length film",
    "full-length film", "full length film", "motion picture",
    "fiction film", "narrative feature", "independent feature film",
    "feature movie", "fictional feature"
)
FILM_GENRES = (
    "action", "adventure", "comedy", "crime", "drama", "fantasy",
    "horror", "mystery", "romance", "science fiction", "sci-fi",
    "thriller", "war film", "western", "musical", "biographical film"
)

MIN_RELEASE_YEAR = 2008
MIN_SOURCE_WIDTH = 1920
MIN_SOURCE_HEIGHT = 1080
MIN_SOURCE_BITRATE = 2_000_000


def _text(value):
    if isinstance(value, (list, tuple)):
        return " ".join(str(part) for part in value)
    if isinstance(value, dict):
        return " ".join(str(part) for part in value.values())
    return str(value or "")


def _normalize(value):
    value = unicodedata.normalize("NFKD", _text(value).casefold())
    return " ".join("".join(ch for ch in value if not unicodedata.combining(ch)).split())


def _metadata_text(metadata, fallback_title=""):
    keys = ("title", "description", "subject", "collection", "genre", "type", "language")
    parts = [_text(metadata.get(key, "")) for key in keys]
    parts.append(_text(fallback_title))
    return _normalize(" ".join(parts))


def looks_animated(metadata, fallback_title=""):
    searchable = _metadata_text(metadata, fallback_title)
    return any(term in searchable for term in ANIMATION_TERMS)


def looks_like_non_movie(metadata, fallback_title=""):
    searchable = _metadata_text(metadata, fallback_title)
    if any(term in searchable for term in NON_MOVIE_TERMS):
        return True
    title = _normalize(metadata.get("title") or fallback_title)
    if re.search(r"\bs\d{1,2}\s*e\d{1,3}\b", title):
        return True
    if re.search(r"\bseason\s*\d+\s*episode\s*\d+\b", title):
        return True
    return False


def has_film_metadata(metadata, fallback_title=""):
    # Archive's broad "movies" category also contains games and recordings.
    # Require a real feature-film classification or a recognized movie genre.
    fields = ("genre", "subject", "collection", "type")
    classified = _normalize(" ".join(_text(metadata.get(key, "")) for key in fields))
    if any(term in classified for term in STRONG_FILM_SIGNALS):
        return True
    genres = _normalize(metadata.get("genre", ""))
    return any(re.search(r"\b" + re.escape(genre) + r"\b", genres) for genre in FILM_GENRES)


def _release_year(metadata):
    for key in ("release_year", "year", "date", "issued", "year_published"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            value = " ".join(str(part) for part in value)
        match = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", str(value or ""))
        if match:
            return int(match.group(1))
    return None


def search_movies(rows=100):
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
        if looks_animated(metadata, title) or looks_like_non_movie(metadata, title):
            continue

        release_year = _release_year(metadata)
        if release_year is None or release_year < MIN_RELEASE_YEAR:
            continue
        if not has_film_metadata(metadata, title):
            continue

        mp4s = []
        for file_info in record.get("files", []):
            name = str(file_info.get("name", ""))
            try:
                size = int(file_info.get("size", 0))
            except (TypeError, ValueError):
                continue
            if name.lower().endswith(".mp4") and 0 < size <= 800 * 1024 * 1024 and not file_info.get("private"):
                mp4s.append({**file_info, "_size": size})
        if not mp4s:
            continue

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
            "download_url": f"https://archive.org/download/{identifier}/{requests.utils.quote(chosen['name'])}",
            "details_url": f"https://archive.org/details/{identifier}",
        })
    return candidates
