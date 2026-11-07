import re
import unicodedata
import logging
import requests
from sources.license_checker import license_is_allowed

log = logging.getLogger("movie-reels-publisher")
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/{}"
HEADERS = {"User-Agent": "MovieReelsPublisher/1.1 (rights-filtered live-action film source tool)"}

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
    "webcast", "recorded session", "public access", "vlog",
    "behind the scenes", "interview", "audition", "rap battle",
    "team mission", "full version", "official trailer", "teaser",
    "preview", "performance", "풀버전", "무삭제", "브이로그", "예고편",
    "dvdrip", "dvd rip", "brrip", "bdrip", "bluray rip", "blu-ray rip",
    "webrip", "web rip", "camrip", "cam rip", "hdcam", "pre dvdrip",
    "pre-dvdrip", "telesync", "telecine", "480p", "360p"
)
NON_FILM_ASSET_TERMS = (
    "vhs glitch", "glitch overlay", "vhs overlay", "vhs effects",
    "film grain overlay", "noise overlay", "video overlay", "overlay pack",
    "transition pack", "visual effects pack", "stock footage",
    "background loop", "motion graphics", "color bars", "smpte bars",
    "test pattern", "screen effect", "video effect", "film effect",
    "texture pack", "analog video effect"
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


def looks_like_non_film_asset(metadata, fallback_title=""):
    searchable = _metadata_text(metadata, fallback_title)
    title = _normalize(metadata.get("title") or fallback_title)
    title_only_terms = ("overlay", "texture pack", "transition pack", "test pattern")
    return (
        any(term in searchable for term in NON_FILM_ASSET_TERMS)
        or any(term in title for term in title_only_terms)
    )


def has_film_metadata(metadata, fallback_title=""):
    fields = ("genre", "subject", "collection", "type", "description", "director", "cast", "runtime", "imdb", "imdb_id", "mediatype")
    classified = _normalize(" ".join(_text(metadata.get(key, "")) for key in fields))
    if any(term in classified for term in STRONG_FILM_SIGNALS):
        return True
    genres = _normalize(" ".join(_text(metadata.get(key, "")) for key in ("genre", "subject")))
    if any(re.search(r"\b" + re.escape(genre) + r"\b", genres) for genre in FILM_GENRES):
        return True
    # A long description alone is not proof that a record is a feature film.
    return False


def _release_year(metadata, fallback_date=""):
    # Archive search results sometimes contain the year while the metadata
    # endpoint omits it. Check both rather than rejecting valid records.
    for value in (
        metadata.get("release_year"), metadata.get("year"), metadata.get("date"),
        metadata.get("issued"), metadata.get("year_published"), metadata.get("originalyear"), fallback_date
    ):
        if isinstance(value, (list, tuple)):
            value = " ".join(str(part) for part in value)
        match = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", str(value or ""))
        if match:
            return int(match.group(1))
    return None


def _search_docs(query, rows, page=1):
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "licenseurl", "creator", "date", "year", "downloads"],
        "rows": max(1, min(int(rows), 500)),
        "page": max(1, int(page)),
        "sort[]": "downloads desc",
        "output": "json",
    }
    response = requests.get(IA_SEARCH, params=params, headers=HEADERS, timeout=40)
    response.raise_for_status()
    return response.json().get("response", {}).get("docs", [])


def search_movies(rows=250, pages=2):
    # The licenseurl field is inconsistently indexed by Archive.org. Search
    # the movie collection broadly if the indexed-license query returns none;
    # every record still passes the exact license allowlist below.
    licensed_query = (
        'mediatype:movies AND (licenseurl:"https://creativecommons.org/publicdomain/mark/1.0/" '
        'OR licenseurl:"https://creativecommons.org/publicdomain/zero/1.0/" '
        'OR licenseurl:"https://creativecommons.org/licenses/by/4.0/")'
    )
    pages = max(1, min(int(pages), 5))
    docs = []
    seen_identifiers = set()

    def collect_pages(query):
        collected = []
        for page in range(1, pages + 1):
            page_docs = _search_docs(query, rows, page=page)
            if not page_docs:
                break
            added = 0
            for doc in page_docs:
                identifier = doc.get("identifier")
                if identifier and identifier not in seen_identifiers:
                    seen_identifiers.add(identifier)
                    collected.append(doc)
                    added += 1
            if len(page_docs) < max(1, min(int(rows), 500)) or added == 0:
                break
        return collected

    docs.extend(collect_pages(licensed_query))
    if not docs:
        log.warning(
            "Internet Archive returned 0 results for its indexed license search; "
            "trying the movie collection and verifying each record's declared license."
        )
        docs.extend(collect_pages("mediatype:movies"))

    log.info(
        "Internet Archive discovery returned %d unique movie records to inspect across %d page(s).",
        len(docs), pages
    )
    candidates = []
    rejected = {
        "missing_identifier": 0, "metadata_unavailable": 0, "license": 0,
        "animation_or_non_movie": 0, "non_movie_asset": 0, "year_missing_or_old": 0,
        "film_metadata": 0, "no_mp4": 0
    }

    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            rejected["missing_identifier"] += 1
            continue
        title = str(doc.get("title") or identifier)
        if str(identifier).casefold().startswith("youtube-"):
            rejected["animation_or_non_movie"] += 1
            continue
        try:
            metadata_response = requests.get(
                IA_METADATA.format(identifier), headers=HEADERS, timeout=25
            )
            metadata_response.raise_for_status()
            record = metadata_response.json()
        except (requests.RequestException, ValueError):
            rejected["metadata_unavailable"] += 1
            continue

        metadata = record.get("metadata", {})
        license_url = metadata.get("licenseurl") or doc.get("licenseurl") or ""
        if not license_is_allowed(license_url):
            rejected["license"] += 1
            continue
        if looks_animated(metadata, title) or looks_like_non_movie(metadata, title):
            rejected["animation_or_non_movie"] += 1
            continue
        if looks_like_non_film_asset(metadata, title):
            rejected["non_movie_asset"] += 1
            continue

        release_year = _release_year(metadata, doc.get("year") or doc.get("date", ""))
        if release_year is None or release_year < MIN_RELEASE_YEAR:
            rejected["year_missing_or_old"] += 1
            continue
        if not has_film_metadata(metadata, title):
            rejected["film_metadata"] += 1
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
            rejected["no_mp4"] += 1
            continue

        # Prefer a genuine Full-HD MP4 variant over a larger low-resolution copy.
        # Archive.org file metadata may omit dimensions; ffprobe remains the final authority.
        def file_quality_rank(file_info):
            try:
                width = int(file_info.get("width", 0) or 0)
                height = int(file_info.get("height", 0) or 0)
                bitrate = int(file_info.get("bitrate") or file_info.get("bit_rate") or 0)
            except (TypeError, ValueError):
                width, height, bitrate = 0, 0, 0
            full_hd = (
                (width >= 1920 and height >= 1080)
                or (width >= 1080 and height >= 1920)
            )
            return (int(full_hd), width * height, bitrate, int(file_info.get("_size", 0)))

        chosen = max(mp4s, key=file_quality_rank)
        try:
            source_width = int(chosen.get("width", 0) or 0)
            source_height = int(chosen.get("height", 0) or 0)
        except (TypeError, ValueError):
            source_width, source_height = 0, 0

        if source_width and source_height:
            full_hd = (
                (source_width >= 1920 and source_height >= 1080)
                or (source_width >= 1080 and source_height >= 1920)
            )
            if not full_hd:
                rejected.setdefault("source_below_full_hd", 0)
                rejected["source_below_full_hd"] += 1
                continue

        candidates.append({
            "identifier": identifier,
            "title": title,
            "creator": _text(metadata.get("creator") or doc.get("creator") or "Unknown"),
            "license_url": license_url,
            "date": _text(metadata.get("date") or doc.get("date") or ""),
            "release_year": release_year,
            "file_name": chosen["name"],
            "file_size": chosen["_size"],
            "source_width": source_width,
            "source_height": source_height,
            "download_url": f"https://archive.org/download/{identifier}/{requests.utils.quote(chosen['name'])}",
            "details_url": f"https://archive.org/details/{identifier}",
        })

    log.info("Movie source rejection counts: %s", rejected)
    log.info("Eligible licensed live-action movie candidates: %d", len(candidates))
    return candidates
