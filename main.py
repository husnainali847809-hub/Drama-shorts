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
MUSIC_ROOT = ROOT / "dramas"
STATE_FILE = ROOT / "state" / "processed.json"
OUTPUT_DIR = ROOT / "output"
ALLOWED_CLIP_SECONDS = {30, 45, 60, 180}
CLIP_SECONDS = int(os.getenv("CLIP_SECONDS", "60"))
if CLIP_SECONDS not in ALLOWED_CLIP_SECONDS:
    raise ValueError(f"CLIP_SECONDS must be one of {sorted(ALLOWED_CLIP_SECONDS)}; got {CLIP_SECONDS}.")
SCENE_PREFERENCE = os.getenv(
    "SCENE_PREFERENCE",
    "Choose the most coherent, engaging story moment with a clear beginning and payoff."
).strip()
ALLOWED_CATEGORIES = {"action", "emotional", "comedy", "romantic", "suspense", "interesting"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


def log(message):
    print(f"[DramaClips] {message}", flush=True)

def build_facebook_caption(source_title, category, scene_summary=""):
    """Create a scene-aware Facebook caption with exactly five relevant hashtags."""
    category = str(category or "interesting").strip().lower()
    allowed = {"action", "emotional", "comedy", "romantic", "suspense", "interesting"}
    if category not in allowed:
        category = "interesting"

    title = os.getenv("DRAMA_TITLE", "").strip() or str(source_title or "").strip()
    title = Path(title).stem
    title = re.sub(r"\\b(official|full|hd|4k|1080p|720p|480p)\\b", " ", title, flags=re.I)
    title = title.replace("_", " ").replace("-", " ")
    title = re.sub(r"\\s+", " ", title).strip(" ._-")[:80] or "Pakistani Drama"

    default_descriptions = {
        "romantic": "A beautiful romantic moment filled with warmth and emotion. ❤️",
        "emotional": "A powerful emotional moment that touches the heart. 💔",
        "comedy": "A light-hearted moment that brings a smile. 😄",
        "action": "An intense moment packed with action and energy. ⚡",
        "suspense": "A gripping moment full of tension and suspense. 👀",
        "interesting": "A memorable drama moment worth watching. ✨",
    }
    description = default_descriptions[category]
    summary = re.sub(r"\\s+", " ", str(scene_summary or "")).strip()
    if summary and len(summary) <= 180:
        description = summary.rstrip(".") + "."

    title_tag = re.sub(r"[^A-Za-z0-9]", "", title.title().replace(" ", ""))[:32]
    candidates = [
        f"#{title_tag or 'PakistaniDrama'}",
        f"#{category.title()}Scene",
        "#PakistaniDrama",
        "#DramaClips",
        "#DramaScenes",
        "#DramaMoments",
        "#PakDrama",
    ]
    hashtags = list(dict.fromkeys(candidates))[:5]
    return f"{title} | {category.title()} Scene\\n\\n{description}\\n\\n" + " ".join(hashtags)


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
        return {"video_ids": [], "video_clips": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        clips = data.get("video_clips", {})
        if not isinstance(clips, dict):
            clips = {}
        clean_clips = {}
        for key, values in clips.items():
            if isinstance(values, list):
                clean_clips[str(key)] = [
                    round(float(value), 2) for value in values
                    if isinstance(value, (int, float))
                ][-4:]
        return {
            "video_ids": list(data.get("video_ids", []))[-1000:],
            "video_clips": clean_clips,
        }
    except (ValueError, OSError, TypeError):
        return {"video_ids": [], "video_clips": {}}


def save_history(history, video_id, clip_start=None, max_clips=4):
    ids = list(history.get("video_ids", []))
    clips = dict(history.get("video_clips", {}))
    if clip_start is None:
        if video_id not in ids:
            ids.append(video_id)
    else:
        starts = list(clips.get(video_id, []))
        start_value = round(float(clip_start), 2)
        if not any(abs(existing - start_value) < 1.0 for existing in starts):
            starts.append(start_value)
        clips[video_id] = starts[-max_clips:]
        if len(clips[video_id]) >= max_clips and video_id not in ids:
            ids.append(video_id)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({
            "video_ids": ids[-1000:],
            "video_clips": dict(list(clips.items())[-1000:]),
        }, indent=2),
        encoding="utf-8",
    )


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


def discover_facebook_latest(page_url, seen_ids):
    """
    Discover recent videos from an authorized Facebook Page through Meta's
    Graph API. The API lists candidate posts; yt-dlp is still used only for
    ordinary, permitted access to the selected public video permalink.
    """
    config_file = ROOT / "resources" / "facebook_pages.json"
    if not config_file.exists():
        raise RuntimeError(
            "Missing resources/facebook_pages.json. Add each Facebook Page URL and Page ID."
        )
    try:
        pages = json.loads(config_file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"Could not read Facebook Page config: {exc}") from exc

    normalized_source = page_url.rstrip("/").lower()
    page = next(
        (
            item for item in pages
            if str(item.get("page_url", "")).rstrip("/").lower() == normalized_source
        ),
        None,
    )
    if not page:
        raise RuntimeError(
            f"No Facebook Page ID mapping found for {page_url}. "
            "Add its canonical Page URL and numeric Page ID to resources/facebook_pages.json."
        )

    page_id = str(page.get("page_id", "")).strip()
    page_name = str(page.get("name", "Facebook Page")).strip() or "Facebook Page"
    if not page_id:
        raise RuntimeError(
            f"Facebook Page ID is missing for {page_name}. "
            "Fill page_id in resources/facebook_pages.json."
        )

    raw_tokens = os.getenv("FACEBOOK_PAGE_ACCESS_TOKENS", "").strip()
    if not raw_tokens:
        raise RuntimeError(
            "Missing FACEBOOK_PAGE_ACCESS_TOKENS GitHub Secret. "
            "Add a JSON object mapping each Page ID to its Page access token."
        )
    try:
        token_map = json.loads(raw_tokens)
    except ValueError as exc:
        raise RuntimeError("FACEBOOK_PAGE_ACCESS_TOKENS must be valid JSON.") from exc
    access_token = str(token_map.get(page_id, "")).strip()
    if not access_token:
        raise RuntimeError(
            f"No Page access token configured for {page_name} (Page ID {page_id})."
        )

    api_version = os.getenv("FACEBOOK_GRAPH_API_VERSION", "v24.0").strip() or "v24.0"
    max_age_days = max(1, int(os.getenv("DRAMA_MAX_AGE_DAYS", "30")))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    endpoint = f"https://graph.facebook.com/{api_version}/{page_id}/videos"
    params = {
        "fields": "id,description,created_time,permalink_url",
        "limit": 50,
        "access_token": access_token,
    }
    candidates = []
    pages_checked = 0

    # Follow a small number of official API pages so a busy Page does not
    # hide recent unseen uploads. Never scrape or bypass Facebook access rules.
    while endpoint and pages_checked < 3:
        response = requests.get(endpoint, params=params, timeout=30)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or payload.get("error"):
            error = payload.get("error", {})
            detail = error.get("message") or response.text[:300] or f"HTTP {response.status_code}"
            raise RuntimeError(f"Facebook Graph API could not list {page_name} videos: {detail}")
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
            candidates.append((created, {
                "id": video_id,
                "url": permalink,
                "title": title[:180] or f"Latest video from {page_name}",
            }))
        pages_checked += 1
        paging = payload.get("paging") or {}
        endpoint = paging.get("next")
        params = None

    if not candidates:
        log(f"No unseen Facebook videos from the last {max_age_days} days at {page_name}.")
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[0][1]
    log(f"Facebook API discovered {len(candidates)} unseen recent video(s) from {page_name}.")
    return selected


def discover_episode(source_url, seen_ids):
    lower_url = source_url.lower()
    if "facebook.com/" in lower_url or "fb.watch/" in lower_url:
        return discover_facebook_latest(source_url, seen_ids)

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
        # Do not force a named quality while extracting metadata. Some videos
        # expose only a different set of formats, so yt-dlp's strict selector
        # can fail before we get a chance to inspect the available formats.
        "ignore_no_formats_error": True,
        "socket_timeout": 30,
        "extractor_retries": 2,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("Video source did not return usable stream metadata.")

    stream_url = None
    headers = info.get("http_headers") or {}

    # Use a direct top-level URL only when yt-dlp actually returned one.
    candidate_url = info.get("url")
    if candidate_url and info.get("vcodec") not in (None, "none") and info.get("acodec") not in (None, "none"):
        stream_url = candidate_url

    # Prefer one combined audio/video format, avoiding separate DASH tracks
    # because the downstream frame/clip reader expects one input stream.
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
        selected = next(
            (item for item in combined if (item.get("height") or 0) <= 1080),
            combined[0],
        )
        stream_url = selected["url"]
        headers = selected.get("http_headers") or headers

    duration = float(info.get("duration") or 0)
    if not stream_url or duration <= CLIP_SECONDS + 5:
        available_count = len(formats)
        raise RuntimeError(
            "No single combined audio/video stream is available "
            f"(yt-dlp exposed {available_count} format(s)); "
            "the video may require sign-in, verification, or separate DASH tracks."
        )
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


def extract_stream_frame(stream, second, destination, video_url=None):
    """
    Extract one frame. If a signed media URL has expired or the CDN rejects it,
    resolve a fresh public stream URL and retry; never reuse the stale URL.
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    last_error = "No frame returned"

    for attempt in range(3):
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

        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=100)
        except subprocess.TimeoutExpired:
            last_error = "FFmpeg timed out while reading the online stream."
            result = None

        if result is not None and result.returncode == 0 and Path(destination).exists() and Path(destination).stat().st_size > 0:
            return

        if result is not None:
            last_error = (result.stderr or result.stdout or "No frame returned")[-500:]
        if attempt >= 2 or not video_url:
            break

        log(f"Frame request failed (attempt {attempt + 1}); refreshing the stream URL.")
        try:
            refreshed = get_stream_source(video_url)
            stream.clear()
            stream.update(refreshed)
        except Exception as refresh_error:
            refresh_detail = str(refresh_error)
            last_error = f"{last_error}; stream refresh failed: {refresh_detail[:200]}"
            if "sign in to confirm" in refresh_detail.lower() or "confirm you're not a bot" in refresh_detail.lower() or "confirm you’re not a bot" in refresh_detail.lower():
                log("YouTube requires account verification for this video; stopping retries for this source.")
                break

    safe_error = re.sub(r"https?://\S+", "<media-url>", last_error)
    raise RuntimeError(f"Could not read frame from online stream after refreshing: {safe_error}")


def candidate_starts(duration):
    duration = float(duration)
    if duration < CLIP_SECONDS + 5:
        raise RuntimeError(f"Episode is too short for a {CLIP_SECONDS}-second clip.")
    # Sample 12 evenly distributed windows for distinct clips across daily slots.
    last_start = max(0.0, duration - CLIP_SECONDS)
    if last_start <= 0:
        return [0.0]
    return [round(last_start * i / 11, 2) for i in range(12)]


def frame_data(clip, second):
    from PIL import Image
    import io
    frame = clip.get_frame(second)
    image = Image.fromarray(frame).convert("RGB")
    image.thumbnail((512, 512))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=68)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def classify_stream_candidates(stream, starts, work_dir, video_url=None):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY GitHub secret.")
    model = "google/gemini-2.5-flash"  # Pin a real vision model; never route through openrouter/free.
    frames = []
    from PIL import Image
    import io

    for index, start in enumerate(starts):
        # Three ordered samples keep the vision request compact while preserving
        # enough temporal context to judge the scene.
        for frame_number, offset in enumerate((
            CLIP_SECONDS * 0.20, CLIP_SECONDS * 0.50,
            CLIP_SECONDS * 0.80,
        )):
            frame_path = Path(work_dir) / f"candidate_{index}_{frame_number}.jpg"
            extract_stream_frame(stream, start + offset, frame_path, video_url=video_url)
            with Image.open(frame_path) as image:
                image = image.convert("RGB")
                image.thumbnail((640, 640))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=78)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            frames.append((index, encoded))

    prompt = (
        "You are an expert drama-scene editor. User's scene preference: "
        + (SCENE_PREFERENCE or "Choose the most coherent engaging story moment.")
        + " Each candidate contains three frames in time order. Select the strongest "
        "continuous scene: frames should belong to one understandable moment, with "
        "a clear emotional or story beat. Prefer meaningful character interaction, "
        "visible action, reaction, or payoff. Reject unrelated shots, empty establishing "
        "shots, black frames, and candidates with confusing jumps. Do not infer dialogue "
        "or plot facts that are not visible. Classify the visible mood as exactly one of: "
        "action, emotional, comedy, romantic, suspense, interesting. Return ONLY JSON "
        "with selected_candidate, category, reason, and scene_summary. "
        + '{"selected_candidate":0,"category":"interesting",'
        + '"reason":"clear character reaction","scene_summary":"two characters react to news"}.'
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
    if response.status_code >= 400:
        # OpenRouter's 4xx response explains model/vision/payload validation failures.
        detail = response.text[:1200].replace(api_key, "[REDACTED]")
        raise RuntimeError(
            f"OpenRouter scene-classification failed (HTTP {response.status_code}; "
            f"model={model}): {detail}"
        )
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
    """Find a local background-music file without requiring sidecar licence metadata."""
    folder = MUSIC_ROOT / category
    if not folder.exists():
        return None, {"title": "Original audio only", "attribution": ""}
    for track in sorted(folder.iterdir()):
        if track.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}:
            return track, {"title": track.stem, "attribution": ""}
    return None, {"title": "Original audio only", "attribution": ""}


def adaptive_clip_seconds(source_path, start, category):
    """Choose a category-aware scene length, always capped at three minutes."""
    from moviepy import VideoFileClip

    # Keep a coherent story beat long enough to develop, without forcing
    # every mood into the same duration.
    # Buffer's Facebook Reels destination rejects videos longer than 90 seconds.
    # Keep every category within that platform limit.
    targets = {
        "comedy": 45,
        "interesting": 60,
        "action": 75,
        "romantic": 90,
        "suspense": 90,
        "emotional": 90,
    }
    target = targets.get(str(category or "interesting").lower(), 60)
    source = VideoFileClip(str(source_path))
    try:
        available = max(0.0, float(source.duration) - float(start))
    finally:
        source.close()

    duration = min(float(target), available, 90.0)
    duration = int(duration)
    if duration < 10:
        raise RuntimeError(
            f"Selected scene has only {duration} seconds available; "
            "at least 10 seconds are needed to create a clip."
        )
    log(
        f"Adaptive scene duration: {duration}s "
        f"(category={category}, target={target}s, hard_max=90s)."
    )
    return duration


def render_clip(source_path, start, category, output_path, clip_seconds=None, music_dir=None):
    """Use the shared three-style professional editing engine."""
    from editing_engine import render_professional_clip
    duration = int(clip_seconds or adaptive_clip_seconds(source_path, start, category))
    # Final renderer-level guard: never create a Facebook Reel over 90 seconds.
    duration = max(10, min(duration, 90))
    return render_professional_clip(
        source_path,
        start,
        category,
        output_path,
        clip_seconds=duration,
        music_dir=music_dir,
    )

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
    selected_start = None
    selected_category = None
    selection_reason = ""
    source_errors = []

    # Validate each source through frame classification before choosing it.
    # A stream URL may resolve successfully while the CDN still blocks FFmpeg
    # or YouTube demands account verification. In that case, skip this source.
    with tempfile.TemporaryDirectory(prefix="drama-stream-work-") as work_dir:
        for source_index, source in enumerate(sources):
            try:
                found = discover_episode(source, set(history["video_ids"]))
                if not found:
                    log(f"No unseen episode found at source {source_index + 1}; checking next source.")
                    continue
                resolved_stream = get_stream_source(found["url"])
                starts = candidate_starts(resolved_stream["duration"])
                log(
                    f"Resolved online stream for '{found.get('title')}'. "
                    f"Checking {len(starts)} candidate windows without saving the full episode."
                )
                try:
                    chosen_start, chosen_category, chosen_reason = classify_stream_candidates(
                        resolved_stream, starts, work_dir, video_url=found["url"]
                    )
                except Exception as frame_error:
                    detail = str(frame_error)
                    source_errors.append(f"{source}: frame/classification failed: {detail[:300]}")
                    log(
                        f"Source {source_index + 1} could not provide readable frames "
                        f"(possibly sign-in/anti-bot protected); trying the next source."
                    )
                    continue

                episode = found
                stream = resolved_stream
                source_used = source
                selected_start = chosen_start
                selected_category = chosen_category
                selection_reason = chosen_reason
                break
            except Exception as exc:
                source_errors.append(f"{source}: {str(exc)[:300]}")
                log(f"Source {source_index + 1} could not be checked; trying the next source.")

        if not episode or not stream or selected_start is None:
            raise RuntimeError(
                "No configured source provided a stream that this runner could read and classify. "
                "YouTube sign-in/anti-bot checks and inaccessible CDN streams cannot be bypassed; "
                "add another source that provides authorized, accessible video access. "
                + " | ".join(source_errors[:5])
            )

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        start = selected_start
        category = selected_category
        reason = selection_reason
        selected_path = Path(work_dir) / "selected_scene.mp4"
        fetch_selected_stream_clip(stream, start, selected_path)
        output_path = OUTPUT_DIR / "pakistani_drama_clip.mp4"
        music_meta = render_clip(selected_path, 0, category, output_path)
        public_url = upload_cloudinary(output_path)
        from publisher.buffer import queue_facebook_reel
        caption = build_facebook_caption(
            episode.get("title", "Pakistani Drama"),
            category,
        )
        queued = queue_facebook_reel(public_url, caption)
        save_history(history, episode["id"])
        log(
            f"SUCCESS: queued one {category} clip. Buffer post ID={queued.get('id')}; "
            f"episode={episode.get('title')}; source={source_used}; start={start:.1f}s; "
            f"music={music_meta.get('title') or 'original audio only'}; "
            f"selection_reason={reason}"
        )
    if output_path.exists():
        output_path.unlink()




if __name__ == "__main__":
    main()