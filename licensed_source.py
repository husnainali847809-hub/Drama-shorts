"""Use manually reviewed, commercially reusable cartoon videos with attribution.

This module never searches for random cartoon uploads. Each item must be explicitly
entered in licensed_assets.json with evidence and rights declarations reviewed by a human.
The declarations are a workflow gate, not an automated legal determination.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import ipaddress
import requests

import main as core

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "licensed_assets.json"
WORK = ROOT / "work" / "licensed"
OUTPUT = ROOT / "output"
MAX_BYTES = 950_000_000
ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "PDM-1.0"}
log = logging.getLogger("licensed_cartoon_source")


def _external_https(url, field):
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError(f"{field} must be an HTTPS URL.")
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise RuntimeError(f"{field} must point to a public source.")
    try:
        if ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback:
            raise RuntimeError(f"{field} must not point to a private network.")
    except ValueError:
        pass
    return str(url)


def _load_asset():
    if not MANIFEST.exists():
        raise RuntimeError("licensed_assets.json is missing; no licensed video can be selected.")
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assets = data.get("assets", [])
    if not isinstance(assets, list) or not assets:
        raise RuntimeError("No reviewed assets are configured in licensed_assets.json. Add a video only after checking its reuse rights.")
    for item in assets:
        required = ("id", "title", "creator", "source_page_url", "video_url",
                    "license", "license_url", "attribution", "rights_verified",
                    "commercial_use", "modifications_allowed", "worldwide_rights_confirmed")
        missing = [key for key in required if key not in item or item[key] in ("", None)]
        if missing:
            raise RuntimeError(f"Licensed asset is missing required rights metadata: {', '.join(missing)}")
        if item["license"] not in ALLOWED_LICENSES:
            raise RuntimeError(f"Unsupported license '{item['license']}' for asset {item['id']}.")
        for flag in ("rights_verified", "commercial_use", "modifications_allowed", "worldwide_rights_confirmed"):
            if item[flag] is not True:
                raise RuntimeError(f"Asset {item['id']} is not approved: {flag} must be explicitly true after human review.")
        if item["license"] == "CC-BY-SA-4.0" and item.get("share_alike_compliance_confirmed") is not True:
            raise RuntimeError(
                f"Asset {item['id']} uses CC-BY-SA-4.0; share_alike_compliance_confirmed must be true "
                "only after confirming the posted adaptation is offered under the same license."
            )
        _external_https(item["source_page_url"], "source_page_url")
        _external_https(item["video_url"], "video_url")
        _external_https(item["license_url"], "license_url")
    index = datetime.now(timezone.utc).date().toordinal() % len(assets)
    return assets[index]


def _download(url, destination):
    with requests.get(url, stream=True, timeout=(20, 90), allow_redirects=True,
                      headers={"User-Agent": "AnimalsAI-CartoonPublisher/1.0"}) as response:
        response.raise_for_status()
        final_url = response.url
        _external_https(final_url, "final video URL after redirect")
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and not (content_type.startswith("video/") or "octet-stream" in content_type):
            raise RuntimeError(f"Source did not return a video file (Content-Type: {content_type}).")
        length = int(response.headers.get("Content-Length", "0") or 0)
        if length > MAX_BYTES:
            raise RuntimeError("Source video exceeds the 950 MB safe download limit.")
        written = 0
        with destination.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_BYTES:
                    raise RuntimeError("Downloaded video exceeded the 950 MB safe limit.")
                output.write(chunk)
    if written < 1024:
        raise RuntimeError("Downloaded source file is empty or too small.")
    log.info("Downloaded reviewed source video: %.1f MB", written / 1_000_000)


def build_licensed_video():
    asset = _load_asset()
    for executable in ("ffmpeg", "ffprobe"):
        core.run([executable, "-version"])
    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = WORK / "source-video"
    _download(asset["video_url"], source)
    probe = json.loads(core.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration:stream=codec_type,width,height",
                                 "-of", "json", str(source)]))
    duration = float(probe.get("format", {}).get("duration", 0))
    video_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video_stream or duration <= 0:
        raise RuntimeError("Licensed source does not contain a valid full-length video stream.")
    brand = os.getenv("BUFFER_EXPECTED_CHANNEL_NAME", core.EXPECTED_PAGE).strip() or "Animated Cartoons"
    brand_file = WORK / "brand.txt"
    credit_file = WORK / "credit.txt"
    brand_file.write_text(brand.replace("\n", " ")[:70], encoding="utf-8")
    credit = f"Source: {asset['creator']} | {asset['license']}"
    credit_file.write_text(credit.replace("\n", " ")[:140], encoding="utf-8")
    output = OUTPUT / f"licensed-cartoon-{datetime.now(timezone.utc):%Y%m%d}-{re.sub(r'[^a-z0-9]+','-',str(asset['id']).lower()).strip('-')[:30]}.mp4"
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    filters = (
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p,"
        "drawbox=x=0:y=0:w=iw:h=66:color=black@0.48:t=fill,"
        f"drawtext=fontfile={font}:textfile={brand_file}:x=28:y=18:fontsize=28:fontcolor=white,"
        "drawbox=x=0:y=h-44:w=iw:h=44:color=black@0.55:t=fill,"
        f"drawtext=fontfile={font}:textfile={credit_file}:x=20:y=h-34:fontsize=17:fontcolor=white"
    )
    # Keep the complete source duration; do not trim it to a short clip or fixed target.
    core.run(["ffmpeg", "-y", "-i", str(source), "-vf", filters,
              "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
              "-threads", "2", "-c:a", "aac", "-b:a", "128k",
              "-movflags", "+faststart", str(output)])
    final = json.loads(core.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration,size:stream=codec_type,width,height",
                                 "-of", "json", str(output)]))
    final_duration = float(final.get("format", {}).get("duration", 0))
    final_size = int(final.get("format", {}).get("size", 0))
    final_video = next((s for s in final.get("streams", []) if s.get("codec_type") == "video"), None)
    if not final_video or (final_video.get("width"), final_video.get("height")) != (1280, 720):
        raise RuntimeError("Branded licensed video failed 1280x720 output validation.")
    if final_duration <= 0 or final_duration < duration * 0.98:
        raise RuntimeError("The processed video appears shorter than the complete source; refusing to publish a trimmed version.")
    if final_size > MAX_BYTES:
        raise RuntimeError("Branded licensed video exceeds the 950 MB upload limit.")
    attribution = str(asset["attribution"]).strip()
    share_alike = ""
    if asset["license"] == "CC-BY-SA-4.0":
        share_alike = (
            "\nAdaptation license: CC BY-SA 4.0 "
            "(the posted adaptation is offered under the same license)."
        )
    caption = (
        f"{asset['title']}\n\n"
        f"Original creator: {asset['creator']}\n"
        f"Source license: {asset['license']} — {asset['license_url']}\n"
        f"Source: {asset['source_page_url']}\n"
        f"Attribution: {attribution}"
        f"{share_alike}\n\n"
        "#Cartoon #Animation #AnimatedStories"
    )
    log.info("Complete licensed source prepared: %s (%.1f minutes). Rights metadata was manually supplied; not independently certified by the software.",
             asset["title"], final_duration / 60)
    return output, str(asset["title"])[:80], caption[:1800]
