import base64
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import cloudinary
import cloudinary.uploader
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
        if not line.startswith(("https://www.youtube.com/", "https://youtube.com/",
                                "https://m.youtube.com/", "https://www.facebook.com/",
                                "https://facebook.com/", "https://fb.watch/")):
            raise RuntimeError(f"Unsupported source URL in {SOURCES_FILE.name}: {line}")
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


def discover_episode(channel_url, seen_ids):
    opts = {
        "quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
        "playlistend": 20, "ignoreerrors": True, "skip_download": True,
        "extractor_retries": 2, "socket_timeout": 30,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    entries = info.get("entries") if isinstance(info, dict) else None
    if entries is None and isinstance(info, dict):
        entries = [info]
    for entry in (entries or []):
        if not entry:
            continue
        video_id = str(entry.get("id") or entry.get("url") or "").strip()
        if not video_id or video_id in seen_ids:
            continue
        url = entry.get("webpage_url") or entry.get("url")
        if url and not str(url).startswith("http"):
            if "facebook.com" in channel_url or "fb.watch" in channel_url:
                if str(url).startswith("/"):
                    url = "https://www.facebook.com" + str(url)
                else:
                    url = f"https://www.facebook.com/watch/?v={url}"
            else:
                url = f"https://www.youtube.com/watch?v={url}"
        if not url:
            continue
        return {"id": video_id, "url": url, "title": entry.get("title") or "Pakistani drama episode"}
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


def candidate_starts(video_path):
    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=15))
    manager.detect_scenes(video)
    scenes = manager.get_scene_list()
    duration = float(video.duration.get_seconds())
    video.close()
    if duration < CLIP_SECONDS + 5:
        raise RuntimeError(f"Episode is too short for a {CLIP_SECONDS}-second clip.")
    starts = [max(0.0, scene[0].get_seconds()) for scene in scenes]
    starts.extend([0.0, max(0.0, duration - CLIP_SECONDS)])
    valid = sorted({round(min(s, duration - CLIP_SECONDS), 2) for s in starts})
    if len(valid) > 12:
        indexes = [round(i * (len(valid) - 1) / 11) for i in range(12)]
        valid = [valid[i] for i in indexes]
    return valid, duration


def frame_data(clip, second):
    from PIL import Image
    import io
    frame = clip.get_frame(second)
    image = Image.fromarray(frame).convert("RGB")
    image.thumbnail((640, 640))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=78)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def classify_candidates(video_path, starts):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY GitHub secret.")
    model = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip() or "openrouter/free"
    frames = []
    with VideoFileClip(str(video_path)) as video:
        for index, start in enumerate(starts):
            for offset in (CLIP_SECONDS * 0.25, CLIP_SECONDS * 0.70):
                frames.append((index, frame_data(video, min(start + offset, video.duration - 0.1))))
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
    source_used = None
    episode_path = None
    source_errors = []
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="drama-clip-")
    temp_dir = temp_dir_obj.name
    for source_index, source in enumerate(sources):
        try:
            found = discover_episode(source, set(history["video_ids"]))
            if not found:
                log(f"No unseen episode found at source {source_index + 1}; checking next source.")
                continue
            source_template = Path(temp_dir) / f"episode_{source_index}.%(ext)s"
            try:
                downloaded_path, metadata = download_episode(found["url"], source_template)
            except Exception as download_error:
                source_errors.append(f"{source}: download failed: {download_error}")
                log(f"Source {source_index + 1} download failed; trying the next configured source.")
                continue
            episode = found
            episode_path = downloaded_path
            source_used = source
            break
        except Exception as exc:
            source_errors.append(f"{source}: {exc}")
            log(f"Source {source_index + 1} could not be checked; trying the next configured source.")
    if not episode or not episode_path:
        temp_dir_obj.cleanup()
        raise RuntimeError(
            "No configured source could provide a new downloadable episode. "
            + " | ".join(source_errors[:5])
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="drama-work-") as work_dir:
        starts, duration = candidate_starts(episode_path)
        if not starts:
            raise RuntimeError("No usable scene windows were detected.")
        start, category, reason = classify_candidates(episode_path, starts)
        output_path = OUTPUT_DIR / "pakistani_drama_clip.mp4"
        music_meta = render_clip(episode_path, start, category, output_path)
        public_url = upload_cloudinary(output_path)
        from publisher.buffer import queue_facebook_reel
        caption = f"{category.title()} scene from a Pakistani drama. #PakistaniDrama #DramaClips"
        queued = queue_facebook_reel(public_url, caption)
        save_history(history, episode["id"])
        log(
            f"SUCCESS: queued one {category} clip. Buffer post ID={queued.get('id')}; "
            f"episode={episode.get('title')}; source={source_used}; start={start:.1f}s; "
            f"music={music_meta.get('title') or music_meta.get('attribution') or 'licensed track'}"
        )
    if output_path.exists():
        output_path.unlink()
    temp_dir_obj.cleanup()


if __name__ == "__main__":
    main()
