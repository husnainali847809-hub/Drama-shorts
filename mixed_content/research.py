import html
import re
import requests
from sources.license_checker import license_is_allowed

WIKI_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "HindiMixedContentFactory/1.0 (licensed educational video production)"}

MOVIES = [
    "Dune: Part Two", "Oppenheimer", "Jawan", "12th Fail",
    "Animal (2023 Indian film)", "Kalki 2898 AD", "Laapataa Ladies",
    "The Batman (film)", "Top Gun: Maverick", "RRR",
]
QUERIES = {
    "documentary": ["space exploration scientific discovery", "ancient civilization history", "wildlife conservation remarkable animal"],
    "real_story": ["survival story explorer", "remarkable historical biography", "real life rescue story"],
    "anime_style": ["space exploration", "wildlife nature", "ancient mythology"],
}

def _clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()

def _wiki_page(query):
    response = requests.get(WIKI_API, params={
        "action": "query", "format": "json", "list": "search",
        "srsearch": query, "srnamespace": 0, "srlimit": 8,
    }, headers=HEADERS, timeout=35)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("search", [])
    for item in pages:
        title = item.get("title", "")
        if not title:
            continue
        detail = requests.get(WIKI_API, params={
            "action": "query", "format": "json", "prop": "extracts",
            "explaintext": 1, "exintro": 1, "titles": title,
        }, headers=HEADERS, timeout=35)
        detail.raise_for_status()
        page = next(iter(detail.json().get("query", {}).get("pages", {}).values()), {})
        extract = _clean(page.get("extract", ""))
        if len(extract) >= 500:
            return {
                "title": title,
                "source_text": extract[:9000],
                "source_url": "https://en.wikipedia.org/wiki/" + requests.utils.quote(title.replace(" ", "_")),
                "source_license": "CC BY-SA 4.0",
                "search_terms": title,
            }
    raise RuntimeError("Research source did not provide enough reliable text; no video will be published.")

def get_research(category, day_index=0):
    if category == "movie_explainer":
        title = MOVIES[day_index % len(MOVIES)]
        item = _wiki_page(title + " film plot production")
        item["title"] = title
        item["search_terms"] = title + " film"
        item["editorial_angle"] = "Hindi movie story explanation with original commentary; do not reproduce dialogue or screenplay."
        return item
    if category == "original_story":
        return {
            "title": "An Original Hindi Short Story",
            "source_text": "Create a completely fictional, family-friendly short story. Theme: courage, kindness, curiosity, and a surprising but uplifting ending. Do not use copyrighted characters or existing franchise worlds.",
            "source_url": "",
            "source_license": "Original AI-generated story",
            "search_terms": "nature friendship cinematic landscape",
        }
    query = QUERIES.get(category, QUERIES["documentary"])[day_index % len(QUERIES.get(category, QUERIES["documentary"]))]
    item = _wiki_page(query)
    item["search_terms"] = item["title"] + " " + query
    item["editorial_angle"] = {
        "documentary": "A factual mini-documentary in simple Hindi.",
        "real_story": "A respectful true-story narration; distinguish verified facts from uncertainty.",
        "anime_style": "An anime/comic-inspired visual retelling of the topic, with original Hindi narration.",
    }.get(category, "A short Hindi explainer.")
    return item

def _license_url(ext):
    raw = str((ext.get("LicenseUrl") or {}).get("value", "") or "")
    match = re.search(r"""href=["']([^"']+)["']""", raw, flags=re.I)
    return match.group(1) if match else _clean(raw)

def find_licensed_images(query, limit=6):
    response = requests.get(COMMONS_API, params={
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": "filetype:bitmap " + query, "gsrnamespace": 6,
        "gsrlimit": 30, "prop": "imageinfo", "iiprop": "url|extmetadata|size",
        "iiextmetadatalanguage": "en",
        "iiextmetadatafilter": "LicenseUrl|Artist|Credit|ObjectName|ImageDescription",
    }, headers=HEADERS, timeout=45)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    found = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        ext = info.get("extmetadata") or {}
        license_url = _license_url(ext)
        url = str(info.get("url") or "")
        try:
            size = int(info.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if not url.startswith("https://upload.wikimedia.org/") or not license_is_allowed(license_url):
            continue
        if size <= 0 or size > 20 * 1024 * 1024:
            continue
        creator = _clean((ext.get("Artist") or {}).get("value") or (ext.get("Credit") or {}).get("value") or "Unknown")
        title = _clean((ext.get("ObjectName") or {}).get("value") or page.get("title", "Wikimedia Commons image"))
        found.append({
            "url": url, "title": title, "creator": creator,
            "license_url": license_url,
            "page_url": "https://commons.wikimedia.org/wiki/" + requests.utils.quote(page.get("title", "").replace(" ", "_"), safe=":"),
        })
        if len(found) >= limit:
            break
    if len(found) < 3:
        raise RuntimeError(f"Only {len(found)} reusable images found for '{query}'. Refusing to create a low-quality or unlicensed video.")
    return found
