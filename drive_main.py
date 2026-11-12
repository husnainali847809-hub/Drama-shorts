"""Process an authorized video from a Google Drive folder and queue one edited clip."""
import base64
import io
import json
import os
import re
import tempfile
from pathlib import Path

import requests
from PIL import Image
from moviepy import VideoFileClip

import main as pipeline

DRIVE_API = "https://www.googleapis.com/drive/v3"


def log(message):
    pipeline.log("[GoogleDrive] " + message)


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing GitHub Secret/Variable: {name}")
    return value


def access_token():
    payload = {
        "client_id": required_env("DRIVE_CLIENT_ID"),
        "client_secret": required_env("DRIVE_CLIENT_SECRET"),
        "refresh_token": required_env("DRIVE_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }
    response = requests.post(
        "https://oauth2.googleapis.com/token", data=payload, timeout=30
    )
    try:
        token_data = response.json()
    except ValueError:
        token_data = {}

    if response.status_code >= 400:
        # Report Google's error code and description, but never print credentials.
        error_code = str(token_data.get("error", "unknown_error"))[:100]
        error_description = str(
            token_data.get("error_description", "No error description returned.")
        )[:500]
        raise RuntimeError(
            f"Google OAuth token refresh failed (HTTP {response.status_code}; "
            f"{error_code}): {error_description}. Verify that DRIVE_CLIENT_ID, "
            "DRIVE_CLIENT_SECRET and DRIVE_REFRESH_TOKEN all belong to the same "
            "OAuth client, and that the refresh token is still valid."
        )

    token = token_data.get("access_token")
    if not token:
        error_code = str(token_data.get("error", "missing_access_token"))[:100]
        raise RuntimeError(
            f"Google OAuth did not return an access token ({error_code})."
        )
    return token


def drive_headers(token):
    return {"Authorization": f"Bearer {token}"}


def newest_unprocessed_video(token, history):
    folder_id = required_env("DRIVE_FOLDER_ID")
    params = {
        "q": f"'{folder_id}' in parents and trashed = false and mimeType contains 'video/'",
        "pageSize": 100,
        "orderBy": "modifiedTime desc",
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    response = requests.get(
        f"{DRIVE_API}/files", headers=drive_headers(token), params=params, timeout=45
    )
    if response.status_code >= 400:
        raise RuntimeError(
            "Google Drive could not list the configured folder. Check DRIVE_FOLDER_ID, "
            "Drive API enablement, and that the OAuth account can access the folder. "
            + response.text[:300]
        )
    files = response.json().get("files", [])
    for item in files:
        if item.get("id") and item["id"] not in history.get("video_ids", []):
            return item
    return None


def download_video(token, item, destination):
    file_id = item["id"]
    response = requests.get(
        f"{DRIVE_API}/files/{file_id}",
        headers=drive_headers(token),
        params={"alt": "media", "supportsAllDrives": "true"},
        stream=True,
        timeout=(30, 300),
    )
    if response.status_code >= 400:
        raise RuntimeError(
            "Google Drive video download failed. Confirm the file is a normal "
            "video file and the connected account has permission. "
            + response.text[:300]
        )
    total = 0
    with open(destination, "wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                output.write(chunk)
                total += len(chunk)
    if total < 100_000:
        raise RuntimeError("The Google Drive download is empty or too small to be a video.")
    log(f"Downloaded '{item.get('name', 'video')}' ({total // (1024 * 1024)} MB).")


def classify_local_video(video_path, work_dir):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY GitHub secret.")
    model = "google/gemini-2.5-flash"  # Pin a real vision model; never route through openrouter/free.

    clip = VideoFileClip(str(video_path))
    try:
        starts = pipeline.candidate_starts(clip.duration)
        frames = []
        for index, start in enumerate(starts):
            # Three ordered samples keep the vision request compact while preserving
            # enough temporal context to judge the scene.
            for frame_number, offset in enumerate((
                pipeline.CLIP_SECONDS * 0.20, pipeline.CLIP_SECONDS * 0.50,
                pipeline.CLIP_SECONDS * 0.80,
            )):
                frame = Image.fromarray(clip.get_frame(start + offset)).convert("RGB")
                frame.thumbnail((512, 512))
                buffer = io.BytesIO()
                frame.save(buffer, format="JPEG", quality=68)
                frames.append((index, base64.b64encode(buffer.getvalue()).decode("ascii")))

        prompt = (
            "You are an expert drama-scene editor. User's scene preference: "
            + (pipeline.SCENE_PREFERENCE or "Choose the most coherent engaging story moment.")
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
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            })
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2,
            },
            timeout=180,
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
            raw = " ".join(
                str(part.get("text", "")) for part in raw if isinstance(part, dict)
            )
        import re
        match = re.search(r"\{.*\}", str(raw), re.S)
        if not match:
            raise RuntimeError(
                f"AI scene classifier returned no JSON: {str(raw)[:300]}"
            )
        result = json.loads(match.group(0))
        selected = int(result.get("selected_candidate", -1))
        category = str(result.get("category", "")).strip().lower()
        if selected < 0 or selected >= len(starts) or category not in pipeline.ALLOWED_CATEGORIES:
            raise RuntimeError(f"AI returned invalid scene selection: {result}")
        return (
            starts[selected],
            category,
            str(result.get("reason", "")).strip(),
            str(result.get("scene_summary", "")).strip(),
        )
    finally:
        clip.close()


def clean_title_from_filename(filename):
    """Use the supplied source title as the drama label; never invent a show name."""
    title = Path(filename or "").stem
    title = re.sub(r"\(\s*\d{3,4}p\s*\)", " ", title, flags=re.I)
    title = re.sub(r"\b\d{3,4}p\b", " ", title, flags=re.I)
    title = title.replace("_", " ").replace("-", " ")
    title = re.sub(r"\b(official|video|full|hd|4k|1080p|720p|480p)\b", " ", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" ._-")
    return title[:80] or "Pakistani Drama"


def build_facebook_caption(source_name, category, reason="", scene_summary=""):
    """Build a scene-specific caption with a grounded title and exactly five hashtags."""
    category = str(category or "interesting").strip().lower()
    allowed = {"action", "emotional", "comedy", "romantic", "suspense", "interesting"}
    if category not in allowed:
        category = "interesting"

    configured_title = os.getenv("DRAMA_TITLE", "").strip()
    drama_title = configured_title or clean_title_from_filename(source_name)

    scene_lines = {
        "romantic": "A beautiful romantic moment filled with warmth and emotion. ❤️",
        "emotional": "A powerful emotional moment that touches the heart. 💔",
        "comedy": "A light-hearted moment that brings a smile. 😄",
        "action": "An intense moment packed with action and energy. ⚡",
        "suspense": "A gripping moment full of tension and suspense. 👀",
        "interesting": "A memorable drama moment worth watching. ✨",
    }
    description = scene_lines[category]
    # Use the model's visual summary only when it is short and grounded.
    summary = re.sub(r"\s+", " ", str(scene_summary or "")).strip()
    if summary and len(summary) <= 180:
        description = summary.rstrip(".") + "."

    hashtag_title = re.sub(r"[^A-Za-z0-9]", "", drama_title.title().replace(" ", ""))
    hashtag_title = hashtag_title[:32] or "PakistaniDrama"
    candidates = [
        f"#{hashtag_title}",
        f"#{category.title()}Scene",
        "#PakistaniDrama",
        "#DramaClips",
        "#DramaScenes",
        "#DramaMoments",
        "#PakDrama",
    ]
    hashtags = list(dict.fromkeys(candidates))[:5]
    caption = (
        f"{drama_title} | {category.title()} Scene\n\n"
        f"{description}\n\n"
        + " ".join(hashtags)
    )
    return caption


def main():
    pipeline.require_rights()
    token = access_token()
    history = pipeline.read_history()
    item = newest_unprocessed_video(token, history)
    if not item:
        raise RuntimeError(
            "No new video found in the configured Google Drive folder. "
            "Upload a supported video file into that folder and check DRIVE_FOLDER_ID."
        )

    log(f"Found new Drive video: {item.get('name', item['id'])}.")
    pipeline.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="drive-video-work-") as work_dir:
        safe_name = Path(item.get("name") or "drive_video.mp4").name
        suffix = Path(safe_name).suffix.lower() or ".mp4"
        source_path = Path(work_dir) / ("drive_source_video" + suffix)
        download_video(token, item, source_path)
        start, category, reason, scene_summary = classify_local_video(source_path, work_dir)
        log(f"AI selected {category} scene at {start:.1f}s: {reason or 'no reason returned'}")
        output_path = pipeline.OUTPUT_DIR / "pakistani_drama_clip.mp4"
        music_meta = pipeline.render_clip(source_path, start, category, output_path)
        public_url = pipeline.upload_cloudinary(output_path)
        from publisher.buffer import queue_facebook_reel
        caption = build_facebook_caption(
            item.get("name", "Pakistani Drama"),
            category,
            reason=reason,
            scene_summary=scene_summary,
        )
        queued = queue_facebook_reel(public_url, caption)
        pipeline.save_history(history, item["id"])
        log(
            f"SUCCESS: queued one {category} clip. Buffer post ID={queued.get('id')}; "
            f"file={item.get('name')}; music="
            f"{music_meta.get('title') or 'original audio only'}"
        )
    if output_path.exists():
        output_path.unlink()


if __name__ == "__main__":
    main()
