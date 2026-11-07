import json
import logging
import re
import subprocess
from datetime import datetime, timezone

import cloudinary
import cloudinary.uploader
import requests

from config import DOWNLOAD_DIR, OUTPUT_DIR, MAX_SOURCE_MB, IA_SEARCH_ROWS, CLIP_MIN_SECONDS, CLIP_MAX_SECONDS, MUSIC_DIR, CLOUDINARY_FOLDER
from sources.movie_finder import search_movies
from sources.license_checker import attribution_required, license_label
from ai.scene_selector import find_candidate_scenes
from editor.video_editor import make_vertical_clip
from publisher.buffer import verify_channel, queue_facebook_video
from database.history import was_used, mark_used

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("movie-reels-publisher")


def need(name):
    import os
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required GitHub Secret/Variable is missing: {name}")
    return value


def download_source(item):
    destination = DOWNLOAD_DIR / f"{item['identifier']}.mp4"
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    response = requests.get(item["download_url"], stream=True, timeout=(30, 120))
    response.raise_for_status()
    total = 0
    try:
        with destination.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_SOURCE_MB * 1024 * 1024:
                    raise RuntimeError("Source exceeded MAX_SOURCE_MB; skipped.")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def probe_source_quality(source):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,bit_rate:format=bit_rate",
         "-of", "json", str(source)],
        capture_output=True, text=True, timeout=45, check=True,
    )
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError("Source has no readable video stream.")
    video = streams[0]
    width, height = int(video.get("width", 0) or 0), int(video.get("height", 0) or 0)
    bitrate = int(video.get("bit_rate") or data.get("format", {}).get("bit_rate") or 0)
    full_hd = ((width >= 1920 and height >= 1080) or (width >= 1080 and height >= 1920))
    if not full_hd:
        raise RuntimeError(f"Source is not native Full HD: {width}x{height}; rejected.")
    if bitrate < 2_000_000:
        raise RuntimeError(f"Source bitrate is below 2 Mbps ({bitrate} bps); rejected.")
    return width, height, bitrate


def upload_video(path):
    cloudinary.config(
        cloud_name=need("CLOUDINARY_CLOUD_NAME"),
        api_key=need("CLOUDINARY_API_KEY"),
        api_secret=need("CLOUDINARY_API_SECRET"),
        secure=True,
    )
    result = cloudinary.uploader.upload(
        str(path), resource_type="video", folder=CLOUDINARY_FOLDER,
        public_id=f"movie-reel-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}",
        overwrite=False, unique_filename=False, type="upload",
    )
    url = str(result.get("secure_url") or "")
    if not url.startswith("https://res.cloudinary.com/"):
        raise RuntimeError("Cloudinary did not return a public HTTPS video URL.")
    return url


def main():
    log.info("Movie Reels Publisher | one video per run | duration=%s-%ss | Buffer queue | 1080x1920",
             CLIP_MIN_SECONDS, CLIP_MAX_SECONDS)
    channel = verify_channel()
    log.info("Facebook destination verified through Buffer: %s",
             channel.get("displayName") or channel.get("name"))
    candidates = search_movies(rows=IA_SEARCH_ROWS)
    log.info("Found %d candidates after license and film-metadata filters.", len(candidates))

    for item in candidates:
        if was_used(item["identifier"]):
            continue
        log.info("Checking licensed candidate: %s (%s)", item["title"], item["identifier"])
        try:
            if item.get("file_size", 0) > MAX_SOURCE_MB * 1024 * 1024:
                log.warning("Candidate exceeds MAX_SOURCE_MB before download; skipped.")
                continue
            source = download_source(item)
            width, height, bitrate = probe_source_quality(source)
            log.info("Verified source quality: %sx%s, bitrate=%s bps", width, height, bitrate)
            scenes = find_candidate_scenes(source, CLIP_MIN_SECONDS, CLIP_MAX_SECONDS)
            if not scenes:
                log.warning("No usable 120-180 second scene window; skipped.")
                continue
            chosen = scenes[0]
            duration = float(chosen["duration"])
            if not CLIP_MIN_SECONDS <= duration <= CLIP_MAX_SECONDS:
                log.warning("Selected duration outside configured range; skipped.")
                continue
            safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", item["identifier"])[:80]
            clip_path = OUTPUT_DIR / f"{safe_name}_reel.mp4"
            fighting = bool(chosen.get("is_fighting", False))
            log.info("Scene pace: %s; detected cuts=%s",
                     "action-like (heuristic)" if fighting else "non-fighting/uncertain",
                     chosen.get("detected_cuts", 0))
            music = make_vertical_clip(source, chosen["start"], duration, clip_path, fighting_scene=fighting)
            if not clip_path.exists() or clip_path.stat().st_size == 0:
                raise RuntimeError("FFmpeg did not create a valid output file.")
            caption = (f"{item['title']} — selected movie scene.\n\n"
                       f"Source: {item['details_url']}\n"
                       f"Declared license: {license_label(item['license_url'])} ({item['license_url']})\n"
                       f"Creator: {item['creator']}.")
            if attribution_required(item["license_url"]):
                caption += f"\nAttribution: {item['creator']} — {item['title']}."
            caption += (f"\n\nBackground music: {music['title']} by {music['creator']}. "
                        f"{music['license_url']} {music['source_url']}")
            public_url = upload_video(clip_path)
            post = queue_facebook_reel(public_url, caption[:1800])
            mark_used(item["identifier"], str(clip_path), post["id"])
            log.info("SUCCESS: Buffer accepted Facebook Reel into queue. post_id=%s status=%s dueAt=%s. "
                     "Queue acceptance is not proof of publication.",
                     post["id"], post.get("status"), post.get("dueAt"))
            return
        except Exception as exc:
            log.exception("Candidate failed and will be skipped: %s", exc)
    log.warning("No eligible unused licensed film source was processed. Nothing was queued; retrying next slot.")


if __name__ == "__main__":
    main()
