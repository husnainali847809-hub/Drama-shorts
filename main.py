import base64
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
import imageio_ffmpeg
import requests
from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from yt_dlp import YoutubeDL

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "resources" / "drama_sources.txt"
RIGHTS_FILE = ROOT / "resources" / "rights.json"
MUSIC_ROOT = ROOT / "assets" / "music"
STATE_FILE = ROOT / "state" / "processed.json"
OUTPUT_DIR = ROOT / "output"
CLIP_SECONDS = int(os.getenv("CLIP_SECONDS", "85"))
ALLOWED_CATEGORIES = {"action", "emotional", "comedy", "romantic", "suspense", "interesting"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


def log(message):
    print(f"[DramaClips] {message}", flush=True)


def read_sources():
    if not SOURCES_FILE.exists():
        raise RuntimeError(f"Missing source list: {SOURCES_FILE}")
    links = []
    for raw in SOURCES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = urlparse(line)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(
                f"Source must be a complete http/https video or channel URL in "
                f"{SOURCES_FILE.name}: {line}"
            )
        links.append(line)
    return list(dict.fromkeys(links))


def require_rights():
    if not RIGHTS_FILE.exists():
        raise RuntimeError("Missing resources/rights.json. Keep reuse_permission_confirmed=false until written permission is obtained.")
    rights = json.loads(RIGHTS_FILE.read_text(encoding="utf-8"))
    if rights.get("reuse_permission_confirmed") is not True:
        raise RuntimeError(
            "SAFETY STOP: resources/rights.json is not confirmed. "
            "Set reuse_permission_confirmed=true only after obtaining permission from every listed rights holder."
        )
    note = str(rights.get("permission_note", "")).strip()
    if not note:
        raise RuntimeError("SAFETY STOP: add a short permission_note/reference in resources/rights.json.")
    return rights


def read_history():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return {"video_ids": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {"video_ids": list(data.get("video_ids", []))[-1000:]}
    except (ValueError, OSError):
        return {"video_ids": []}


def save_history(history, video_id):
    ids = history.get("video_ids", [])
    if video_id not in ids:
        ids.append(video_id)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"video_ids": ids[-1000:]}, indent=2), encoding="utf-8")


def discover_youtube_latest(channel_url, seen_ids):
    # Use YouTube's channel RSS feed instead of crawling the channel's full
    # uploads tab, which can contain thousands of historical videos.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    }
    channel_match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{20,})", channel_url)
    channel_id = channel_match.group(1) if channel_match else None

    if not channel_id:
        response = requests.get(channel_url.rstrip("/"), headers=headers, timeout=25)
        response.raise_for_status()
        patterns = [
            r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{20,})"',
            r'"externalId"\s*:\s*"(UC[a-zA-Z0-9_-]{20,})"',
            r'<meta[^>]+itemprop=["\']channelId["\'][^>]+content=["\'](UC[a-zA-Z0-9_-]{20,})',
        ]
        for pattern in patterns:
            match = re.search(pattern, response.text)
            if match:
                channel_id = match.group(1)
                break
    if not channel_id:
        raise RuntimeError(f"Could not resolve YouTube channel ID from {channel_url}")

    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    feed_response = requests.get(feed_url, headers=headers, timeout=25)
    feed_response.raise_for_status()
    root = ET.fromstring(feed_response.content)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    max_age_days = max(1, int(os.getenv("DRAMA_MAX_AGE_DAYS", "30")))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    candidates = []

    for entry in root.findall("atom:entry", ns):
        video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        published_text = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        if not video_id or video_id in seen_ids or not published_text:
            continue
        try:
            published = datetime.fromisoformat(published_text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published < cutoff:
            continue
        candidates.append((published, {
            "id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": title or "Latest Pakistani drama episode",
        }))

    if not candidates:
        log(f"No unseen YouTube uploads from the last {max_age_days} days at {channel_url}.")
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def discover_facebook_candidates(seen_ids):
    """
    Search public Facebook Pages for Pakistani-drama sources through Meta's
    official Pages Search API, then list recent public videos from those Pages.

    Requires META_APP_ACCESS_TOKEN and Meta approval for Page Public Content
    Access (or another permission explicitly sufficient for this use case).
    This discovers Pages/videos only; it does not bypass privacy, login,
    anti-bot, DRM, or media-download restrictions.
    """
    access_token = os.getenv("META_APP_ACCESS_TOKEN", "").strip()
    if not access_token:
        log("Facebook auto-discovery skipped: META_APP_ACCESS_TOKEN GitHub Secret is not set.")
        return []

    api_version = os.getenv("META_GRAPH_API_VERSION", "v26.0").strip() or "v26.0"
    max_age_days = max(1, int(os.getenv("DRAMA_MAX_AGE_DAYS", "30")))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    search_terms = [
        term.strip()
        for term in os.getenv(
            "FACEBOOK_SEARCH_TERMS",
            "Pakistani drama,Pakistani drama official,Pakistani television drama"
        ).split(",")
        if term.strip()
    ]
    base_url = f"https://graph.facebook.com/{api_version}"
    pages_by_id = {}

    for term in search_terms:
        response = requests.get(
            f"{base_url}/pages/search",
            params={
                "q": term,
                "fields": "id,name,link",
                "limit": 25,
                "access_token": access_token,
            },
            timeout=30,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or payload.get("error"):
            error = payload.get("error") or {}
            detail = error.get("message") or response.text[:300] or f"HTTP {response.status_code}"
            log(f"Meta Page Search failed for '{term}': {detail}")
            continue
        for page in payload.get("data", []):
            page_id = str(page.get("id", "")).strip()
            if page_id:
                pages_by_id[page_id] = {
                    "id": page_id,
                    "name": str(page.get("name") or "Facebook Page").strip(),
                    "link": str(page.get("link") or "").strip(),
                }

    if not pages_by_id:
        log("Facebook auto-discovery found no Pages. Check Meta token, API version and approved Page search permissions.")
        return []

    candidates_by_id = {}
    for page_id, page in pages_by_id.items():
        response = requests.get(
            f"{base_url}/{page_id}/videos",
            params={
                "fields": "id,description,created_time,permalink_url",
                "limit": 25,
                "access_token": access_token,
            },
            timeout=30,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or payload.get("error"):
            error = payload.get("error") or {}
            detail = error.get("message") or response.text[:250] or f"HTTP {response.status_code}"
            log(f"Could not list public videos for {page['name']}: {detail}")
            continue

        for item in payload.get("data", []):
            video_id = str(item.get("id", "")).strip()
            permalink = str(item.get("permalink_url", "")).strip()
            created_text = str(item.get("created_time", "")).strip()
            if not video_id or video_id in seen_ids or not permalink.startswith("https://"):
                continue
            try:
                created = datetime.fromisoformat(created_text.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created < cutoff:
                continue
            description = str(item.get("description", "")).strip()
            title = next((line.strip() for line in description.splitlines() if line.strip()), "")
            candidates_by_id[video_id] = {
                "id": video_id,
                "url": permalink,
                "title": title[:180] or f"Latest video from {page['name']}",
                "source_page": page["name"],
                "created_time": created_text,
            }

    candidates = list(candidates_by_id.values())
    candidates.sort(key=lambda item: item.get("created_time", ""), reverse=True)
    max_candidates = max(1, int(os.getenv("FACEBOOK_MAX_CANDIDATES", "30")))
    candidates = candidates[:max_candidates]
    log(
        f"Facebook auto-discovery checked {len(pages_by_id)} public Page(s) "
        f"and found {len(candidates)} unseen recent video(s)."
    )
    return candidates

def discover_episode(source_url, seen_ids):
    lower_url = source_url.lower()
    is_youtube = any(host in lower_url for host in ("youtube.com/", "youtu.be/"))
    is_youtube_channel = is_youtube and any(
        marker in lower_url for marker in ("/@", "/channel/", "/c/", "/user/")
    )
    if is_youtube_channel:
        return discover_youtube_latest(source_url, seen_ids)

    # For individual video links and other supported video platforms, let
    # yt-dlp select the matching public extractor. This includes supported
    # Facebook video/reel URLs and direct media URLs. Channel-wide scanning
    # is intentionally not attempted for generic websites.
    opts = {
        "quiet": True, "no_warnings": True, "extract_flat": False,
        "playlistend": 20, "lazy_playlist": True, "ignoreerrors": True,
        "skip_download": True, "extractor_retries": 2, "socket_timeout": 30,
        "noplaylist": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source_url, download=False)
    entries = info.get("entries") if isinstance(info, dict) else None
    if entries is None and isinstance(info, dict):
        entries = [info]

    for entry in (entries or []):
        if not entry:
            continue
        video_id = str(entry.get("id") or entry.get("display_id") or entry.get("url") or "").strip()
        if not video_id or video_id in seen_ids:
            continue
        url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        if not url:
            continue
        if not str(url).startswith("http"):
            extractor = str(entry.get("extractor_key") or "").lower()
            if extractor == "facebook":
                if str(url).startswith("/"):
                    url = "https://www.facebook.com" + str(url)
                else:
                    url = f"https://www.facebook.com/watch/?v={url}"
            else:
                continue
        return {
            "id": video_id,
            "url": url,
            "title": entry.get("title") or "Drama episode",
        }
    return None


def download_episode(url, destination):
    # Try sensible quality/format fallbacks. No browser cookies or login bypass.
    format_choices = [
        "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "best[height<=720]/best",
        "best",
    ]
    failures = []
    for format_choice in format_choices:
        opts = {
            "format": format_choice,
            "merge_output_format": "mp4",
            "outtmpl": str(destination),
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 5,
            "file_access_retries": 3,
            "socket_timeout": 60,
            "concurrent_fragment_downloads": 1,
            "continuedl": True,
            "overwrites": True,
            "ignoreerrors": False,
            "cachedir": False,
        }
        try:
            with YoutubeDL(opts) as ydl:
                result = ydl.extract_info(url, download=True)
                if not result:
                    raise RuntimeError("yt-dlp returned no episode metadata.")
                actual = Path(ydl.prepare_filename(result))
            if not actual.exists():
                merged = actual.with_suffix(".mp4")
                if merged.exists():
                    actual = merged
            if actual.exists() and actual.stat().st_size >= 1_000_000:
                return actual, result
            raise RuntimeError("Download finished without a usable video file.")
        except Exception as exc:
            message = str(exc)
            if "Sign in to confirm you're not a bot" in message or "confirm you’re not a bot" in message:
                failures.append("YouTube temporarily requires account verification for this video.")
            elif "Requested format is not available" in message:
                failures.append("Requested quality is unavailable; trying a lower format.")
            else:
                failures.append(message[:240])
    raise RuntimeError(
        "All normal yt-dlp download attempts failed: " + " | ".join(failures)
        + ". If YouTube requires sign-in/verification, this runner cannot guarantee access; "
          "use a source that grants authorized public download access or provide an authorized video file."
    )


def get_stream_source(video_url):
    """
    Resolve a public, authorized video URL to a stream URL without saving
    the full episode. The selected short segment is fetched later only.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "best[height<=1080]/best",
        "socket_timeout": 30,
        "extractor_retries": 2,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("Video source did not return usable stream metadata.")

    stream_url = info.get("url")
    if not stream_url:
        # Prefer a single combined audio/video format. Separate DASH tracks
        # require a more complex multi-input stream and are intentionally
        # not guessed here.
        formats = info.get("formats") or []
        combined = [
            item for item in formats
            if item.get("url")
            and item.get("vcodec") not in (None, "none")
            and item.get("acodec") not in (None, "none")
        ]
        combined.sort(key=lambda item: (
            item.get("height") or 0,
            item.get("tbr") or 0
        ), reverse=True)
        if combined:
            stream_url = combined[0]["url"]
            info["http_headers"] = combined[0].get("http_headers") or info.get("http_headers") or {}

    duration = float(info.get("duration") or 0)
    if not stream_url or duration <= CLIP_SECONDS + 5:
        raise RuntimeError(
            "Could not resolve a single public audio/video stream or episode duration. "
            "This source may require sign-in, verification, or separate DASH tracks."
        )
    headers = info.get("http_headers") or {}
    return {
        "url": stream_url,
        "headers": headers,
        "duration": duration,
        "title": info.get("title") or "Drama episode",
    }


def ffmpeg_headers(headers):
    lines = []
    for key, value in (headers or {}).items():
        if key and value is not None:
            lines.append(f"{key}: {value}")
    return ("\r\n".join(lines) + "\r\n") if lines else ""


def extract_stream_frame(stream, second, destination):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-rw_timeout", "30000000",
        "-ss", f"{max(0.0, float(second)):.3f}",
    ]
    header_text = ffmpeg_headers(stream.get("headers"))
    if header_text:
        command.extend(["-headers", header_text])
    command.extend([
        "-i", stream["url"],
        "-frames:v", "1",
        "-vf", "scale='min(640,iw)':-2",
        "-q:v", "3", "-y", str(destination),
    ])
    result = subprocess.run(command, capture_output=True, text=True, timeout=100)
    if result.returncode != 0 or not Path(destination).exists() or Path(destination).stat().st_size == 0:
        detail = (result.stderr or result.stdout or "No frame returned")[-500:]
        raise RuntimeError(f"Could not read frame from online stream: {detail}")


def candidate_starts(duration):
    duration = float(duration)
    if duration < CLIP_SECONDS + 5:
        raise RuntimeError(f"Episode is too short for a {CLIP_SECONDS}-second clip.")
    # Sample up to 12 evenly distributed windows. This avoids downloading
    # or scanning the entire episode locally.
    last_start = max(0.0, duration - CLIP_SECONDS)
    if last_start <= 0:
        return [0.0]
    return [round(last_start * i / 11, 2) for i in range(12)]


def frame_data(clip, second):
    from PIL import Image
    import io
    frame = clip.get_frame(second)
    image = Image.fromarray(frame).convert("RGB")
    image.thumbnail((640, 640))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=78)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def classify_stream_candidates(stream, starts, work_dir):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY GitHub secret.")
    model = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip() or "openrouter/free"
    frames = []
    from PIL import Image
    import io

    for index, start in enumerate(starts):
        for frame_number, offset in enumerate((CLIP_SECONDS * 0.25, CLIP_SECONDS * 0.70)):
            frame_path = Path(work_dir) / f"candidate_{index}_{frame_number}.jpg"
            extract_stream_frame(stream, start + offset, frame_path)
            with Image.open(frame_path) as image:
                image = image.convert("RGB")
                image.thumbnail((640, 640))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=78)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            frames.append((index, encoded))

    prompt = (
        "You are selecting a short Pakistani TV drama scene for an authorized social clip. "
        "Inspect the frames grouped by candidate number. Choose the most engaging coherent candidate. "
        "Classify it as exactly one of: action, emotional, comedy, romantic, suspense, interesting. "
        "Do not invent plot details. Return ONLY JSON: "
        '{"selected_candidate":0,"category":"interesting","reason":"brief visual reason"}. '
        "Candidate number is the integer shown before each pair of frames."
    )
    content = [{"type": "text", "text": prompt}]
    for index, encoded in frames:
        content.append({"type": "text", "text": f"Candidate {index} frame:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.2},
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    raw = payload["choices"][0]["message"]["content"]
    if isinstance(raw, list):
        raw = " ".join(str(x.get("text", "")) for x in raw if isinstance(x, dict))
    match = re.search(r"\{.*\}", str(raw), re.S)
    if not match:
        raise RuntimeError(f"AI scene classifier returned no JSON: {str(raw)[:300]}")
    result = json.loads(match.group(0))
    selected = int(result.get("selected_candidate", -1))
    category = str(result.get("category", "")).strip().lower()
    if selected < 0 or selected >= len(starts) or category not in ALLOWED_CATEGORIES:
        raise RuntimeError(f"AI returned invalid scene selection: {result}")
    return starts[selected], category, str(result.get("reason", "")).strip()


def fetch_selected_stream_clip(stream, start, destination):
    """Fetch only the chosen short segment, not the full episode."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-rw_timeout", "30000000",
        "-ss", f"{max(0.0, float(start)):.3f}",
    ]
    header_text = ffmpeg_headers(stream.get("headers"))
    if header_text:
        command.extend(["-headers", header_text])
    command.extend([
        "-i", stream["url"],
        "-t", str(CLIP_SECONDS),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-y", str(destination),
    ])
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not Path(destination).exists() or Path(destination).stat().st_size < 100_000:
        detail = (result.stderr or result.stdout or "No clip returned")[-700:]
        raise RuntimeError(f"Could not fetch selected segment from online stream: {detail}")
    return Path(destination)


def reusable_music_track(category):
    folder = MUSIC_ROOT / category
    if not folder.exists():
        raise RuntimeError(f"Missing licensed music folder: assets/music/{category}/")
    for track in sorted(folder.iterdir()):
        if track.suffix.lower() not in {".mp3", ".wav", ".m4a", ".aac"}:
            continue
        metadata_path = track.with_suffix(track.suffix + ".license.json")
        if not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        license_name = str(metadata.get("license", "")).strip().lower()
        accepted = {"public domain", "cc0", "cc-by", "cc-by-sa", "direct permission"}
        if license_name not in accepted:
            continue
        if license_name == "direct permission" and not str(metadata.get("permission_reference", "")).strip():
            continue
        if license_name in {"cc-by", "cc-by-sa"} and not str(metadata.get("attribution", "")).strip():
            continue
        return track, metadata
    raise RuntimeError(
        f"No authorized music track found for '{category}'. Add a track and its .license.json sidecar; see assets/music/README.md."
    )


def render_clip(source_path, start, category, output_path):
    music_path, music_meta = reusable_music_track(category)
    source = VideoFileClip(str(source_path))
    clip = source.subclipped(start, min(start + CLIP_SECONDS, source.duration))
    if clip.duration < CLIP_SECONDS - 1:
        source.close()
        clip.close()
        raise RuntimeError("Selected scene window is shorter than the configured clip length.")
    # Vertical 1080x1920 crop, centered, without stretching the source.
    resized = clip.resized(height=1920)
    vertical = resized.cropped(
        x_center=resized.w / 2, y_center=resized.h / 2, width=1080, height=1920
    )
    music = AudioFileClip(str(music_path))
    if music.duration < clip.duration:
        music.close()
        vertical.close()
        resized.close()
        clip.close()
        source.close()
        raise RuntimeError(f"Music track must be at least {clip.duration:.0f} seconds long: {music_path.name}")
    music = music.subclipped(0, clip.duration).with_volume_scaled(0.18)
    audio_layers = [music]
    if vertical.audio is not None:
        audio_layers.insert(0, vertical.audio.with_volume_scaled(1.0))
    mixed_audio = CompositeAudioClip(audio_layers)
    final = vertical.with_audio(mixed_audio)
    final.write_videofile(
        str(output_path), codec="libx264", audio_codec="aac", fps=30,
        preset="medium", bitrate="4500k", audio_bitrate="192k", threads=2,
    )
    final.close()
    mixed_audio.close()
    music.close()
    vertical.close()
    resized.close()
    clip.close()
    source.close()
    return music_meta


def upload_cloudinary(video_path):
    required = ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"]
    missing = [key for key in required if not os.getenv(key, "").strip()]
    if missing:
        raise RuntimeError("Missing Cloudinary GitHub secrets: " + ", ".join(missing))
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    result = cloudinary.uploader.upload(
        str(video_path), resource_type="video",
        folder=os.getenv("CLOUDINARY_FOLDER", "pakistani-drama-clips"),
        timeout=300,
    )
    url = result.get("secure_url", "")
    if not url.startswith("https://res.cloudinary.com/"):
        raise RuntimeError("Cloudinary did not return a verified public HTTPS video URL.")
    return url


def main():
    require_rights()
    sources = read_sources()
    if not sources:
        log("No channel/page links configured yet. Add authorized links to resources/drama_sources.txt.")
        return
    history = read_history()
    episode = None
    stream = None
    source_used = None
    source_errors = []

    # Search Facebook automatically; no manually supplied Facebook URLs or
    # Page-ID mapping file is used. Try recent public Page videos newest first.
    facebook_candidates = discover_facebook_candidates(set(history["video_ids"]))
    candidate_jobs = [
        (f"Facebook Page: {item.get('source_page', 'unknown')}", item)
        for item in facebook_candidates
    ]

    # Keep configured non-Facebook sources (for example YouTube channels) as
    # fallback sources. Facebook links in drama_sources.txt are not required.
    for source_index, source in enumerate(sources):
        try:
            found = discover_episode(source, set(history["video_ids"]))
            if found:
                candidate_jobs.append((source, found))
            else:
                log(f"No unseen episode found at configured source {source_index + 1}.")
        except Exception as exc:
            source_errors.append(f"{source}: {exc}")
            log(f"Configured source {source_index + 1} could not be checked: {exc}")

    for source, found in candidate_jobs:
        try:
            resolved_stream = get_stream_source(found["url"])
            episode = found
            stream = resolved_stream
            source_used = source
            break
        except Exception as stream_error:
            source_errors.append(f"{source}: stream access failed: {stream_error}")
            log(f"{source} could not provide an accessible stream; trying the next candidate.")

    if not episode or not stream:
        raise RuntimeError(
            "No discovered or configured source provided an accessible online stream. "
            "Streaming avoids downloading the full episode, but the platform must still expose "
            "a public stream to this runner; sign-in/anti-bot protected videos will fail. "
            + " | ".join(source_errors[:5])
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="drama-stream-work-") as work_dir:
        starts = candidate_starts(stream["duration"])
        log(
            f"Resolved online stream for '{episode.get('title')}'. "
            f"Checking {len(starts)} candidate windows without saving the full episode."
        )
        start, category, reason = classify_stream_candidates(stream, starts, work_dir)
        selected_path = Path(work_dir) / "selected_scene.mp4"
        fetch_selected_stream_clip(stream, start, selected_path)
        output_path = OUTPUT_DIR / "pakistani_drama_clip.mp4"
        music_meta = render_clip(selected_path, 0, category, output_path)
        public_url = upload_cloudinary(output_path)
        from publisher.buffer import queue_facebook_reel
        caption = f"{category.title()} scene from a Pakistani drama. #PakistaniDrama #DramaClips"
        queued = queue_facebook_reel(public_url, caption)
        save_history(history, episode["id"])
        log(
            f"SUCCESS: queued one {category} clip. Buffer post ID={queued.get('id')}; "
            f"episode={episode.get('title')}; source={source_used}; start={start:.1f}s; "
            f"music={music_meta.get('title') or music_meta.get('attribution') or 'licensed track'}; "
            f"selection_reason={reason}"
        )
    if output_path.exists():
        output_path.unlink()




if __name__ == "__main__":
    main()
