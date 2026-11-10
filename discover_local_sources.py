import csv
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
SOURCE_FILE = ROOT / "resources" / "discovery_sources.txt"
OUT_DIR = ROOT / "output"
OUT_FILE = OUT_DIR / "local_channel_discoveries.csv"
MAX_AGE_DAYS = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DramaSourceDiscovery/1.0)"}
NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def channel_id_from_url(url):
    match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{20,})", url)
    if match:
        return match.group(1)
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    patterns = [
        r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{20,})"',
        r'"externalId"\s*:\s*"(UC[a-zA-Z0-9_-]{20,})"',
        r"""<meta[^>]+itemprop=["']channelId["'][^>]+content=["'](UC[a-zA-Z0-9_-]{20,})""",
    ]
    for pattern in patterns:
        found = re.search(pattern, response.text)
        if found:
            return found.group(1)
    raise RuntimeError("Could not resolve channel ID")


def main():
    if not SOURCE_FILE.exists():
        raise RuntimeError(f"Missing {SOURCE_FILE}")
    sources = []
    for raw in SOURCE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if urlparse(line).netloc.lower() not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            print(f"SKIP invalid/non-YouTube discovery URL: {line}")
            continue
        sources.append(line)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    rows, seen = [], set()
    for channel_url in dict.fromkeys(sources):
        try:
            cid = channel_id_from_url(channel_url)
            feed = requests.get(
                f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                headers=HEADERS, timeout=25
            )
            feed.raise_for_status()
            root = ET.fromstring(feed.content)
            for entry in root.findall("atom:entry", NS):
                vid = (entry.findtext("yt:videoId", default="", namespaces=NS) or "").strip()
                title = (entry.findtext("atom:title", default="", namespaces=NS) or "").strip()
                published_raw = (entry.findtext("atom:published", default="", namespaces=NS) or "").strip()
                if not vid or vid in seen or not published_raw:
                    continue
                published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                if published < cutoff:
                    continue
                seen.add(vid)
                rows.append({
                    "channel_url": channel_url,
                    "title": title,
                    "published_utc": published.isoformat(),
                    "video_url": f"https://www.youtube.com/watch?v={vid}",
                    "video_id": vid,
                    "status": "DISCOVERY_ONLY - review source and rights before any reuse",
                })
            print(f"OK discovered recent uploads: {channel_url}")
        except Exception as exc:
            print(f"WARN discovery failed for {channel_url}: {str(exc)[:240]}")

    with OUT_FILE.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "channel_url", "title", "published_utc", "video_url", "video_id", "status"
        ])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["published_utc"], reverse=True))
    print(f"Discovery complete: {len(rows)} recent videos saved to {OUT_FILE}")


if __name__ == "__main__":
    main()
