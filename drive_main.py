"""Process an authorized video from a Google Drive folder and queue one edited clip."""
import base64
import io
import json
import os
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
    if response.status_code >= 400:
        raise RuntimeError(
            "Google OAuth token refresh failed. Check DRIVE_CLIENT_ID, "
            "DRIVE_CLIENT_SECRET and DRIVE_REFRESH_TOKEN, and ensure the "
            "refresh token was granted the Google Drive read-only scope."
        )
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Google OAuth did not return an access token.")
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
    model = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip() or "openrouter/free"

    clip = VideoFileClip(str(video_path))
    try:
        starts = pipeline.candidate_starts(clip.duration)
        frames = []
        for index, start in enumerate(starts):
            for frame_number, offset in enumerate(
                (pipeline.CLIP_SECONDS * 0.25, pipeline.CLIP_SECONDS * 0.70)
            ):
                frame = Image.fromarray(clip.get_frame(start + offset)).convert("RGB")
                frame.thumbnail((640, 640))
                buffer = io.BytesIO()
                frame.save(buffer, format="JPEG", quality=78)
                frames.append((index, base64.b64encode(buffer.getvalue()).decode("ascii")))

        prompt = (
            "You are selecting a short engaging scene from a user-provided video. "
            "Inspect frames grouped by candidate number. Choose the most engaging "
            "coherent candidate. Classify it as exactly one of: action, emotional, "
            "comedy, romantic, suspense, interesting. Do not invent plot details. "
            'Return ONLY JSON: {"selected_candidate":0,"category":"interesting",'
            '"reason":"brief visual reason"}. Candidate number is shown before each pair.'
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
        response.raise_for_status()
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
        return starts[selected], category, str(result.get("reason", "")).strip()
    finally:
        clip.close()


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
        start, category, reason = classify_local_video(source_path, work_dir)
        log(f"AI selected {category} scene at {start:.1f}s: {reason or 'no reason returned'}")
        output_path = pipeline.OUTPUT_DIR / "pakistani_drama_clip.mp4"
        music_meta = pipeline.render_clip(source_path, start, category, output_path)
        public_url = pipeline.upload_cloudinary(output_path)
        from publisher.buffer import queue_facebook_reel
        caption = f"{category.title()} scene. #DramaClips #ShortVideos"
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
