"""Process an authorized video from a Google Drive folder and queue one edited clip."""
import base64
import io
import json
import os
import re
import tempfile
import time
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


class NoUnusedSceneWindows(RuntimeError):
    """Raised when this episode has no remaining distinct candidate windows."""


def newest_unprocessed_video(token, history):
    folder_id = required_env("DRIVE_FOLDER_ID")
    params = {
        "q": f"'{folder_id}' in parents and trashed = false and mimeType contains 'video/'",
        "pageSize": 100,
        "orderBy": "modifiedTime desc",
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink,parents)",
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


def list_folder_audio(token, folder_id):
    """Find audio files stored beside the drama videos in the configured Drive folder."""
    params = {
        "q": f"'{folder_id}' in parents and trashed = false and mimeType contains 'audio/'",
        "pageSize": 100,
        "orderBy": "name",
        "fields": "files(id,name,mimeType,size)",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    response = requests.get(
        f"{DRIVE_API}/files", headers=drive_headers(token), params=params, timeout=45
    )
    if response.status_code >= 400:
        raise RuntimeError("Google Drive could not list music files: " + response.text[:300])
    audio_files = response.json().get("files", [])
    log(f"Found {len(audio_files)} audio file(s) beside the drama videos in Google Drive.")
    return audio_files


def download_drive_file(token, item, destination):
    """Download a Drive audio file to the temporary work directory."""
    response = requests.get(
        f"{DRIVE_API}/files/{item['id']}",
        headers=drive_headers(token),
        params={"alt": "media", "supportsAllDrives": "true"},
        stream=True,
        timeout=(30, 300),
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Google Drive audio download failed for {item.get('name', 'audio')}: "
            + response.text[:250]
        )
    total = 0
    with open(destination, "wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                output.write(chunk)
                total += len(chunk)
    if total < 1024:
        raise RuntimeError(f"Downloaded audio file is empty: {item.get('name', 'audio')}")
    log(f"Downloaded music track '{item.get('name', destination.name)}'.")
    return destination


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


def post_with_retry(url, *, max_attempts=5, **kwargs):
    """Retry temporary provider overloads and network failures with bounded backoff."""
    retryable_statuses = {500, 502, 503, 504}
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, **kwargs)
            if response.status_code == 429:
                # A 429 without Retry-After is commonly a hard quota/rate-limit
                # response. Repeating it five times wastes the run's time budget.
                retry_after = response.headers.get("Retry-After", "").strip()
                body_lower = response.text.lower()
                hard_limit = any(term in body_lower for term in (
                    "quota", "resource_exhausted", "daily limit",
                    "per day", "billing", "insufficient"
                ))
                if not retry_after or hard_limit or attempt == max_attempts:
                    return response
            elif response.status_code not in retryable_statuses:
                return response

            last_error = RuntimeError(
                f"Temporary API response HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
            if attempt == max_attempts:
                return response

            retry_after = response.headers.get("Retry-After", "").strip()
            try:
                delay = min(60, max(1, int(float(retry_after)))) if retry_after else min(30, 5 * (2 ** (attempt - 1)))
            except ValueError:
                delay = min(30, 5 * (2 ** (attempt - 1)))
            log(
                f"AI provider temporarily unavailable (HTTP {response.status_code}); "
                f"retrying attempt {attempt + 1}/{max_attempts} in {delay}s."
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt == max_attempts:
                raise RuntimeError(
                    f"AI provider request failed after {max_attempts} attempts: {exc}"
                ) from exc
            delay = min(30, 5 * (2 ** (attempt - 1)))
            log(
                f"Temporary AI network error; retrying attempt "
                f"{attempt + 1}/{max_attempts} in {delay}s."
            )

        time.sleep(delay)

    raise RuntimeError(f"AI provider request failed: {last_error}")


def _extract_model_text(payload):
    """Normalize common vision-chat response shapes to plain text."""
    if isinstance(payload, dict) and payload.get("candidates"):
        parts = payload["candidates"][0].get("content", {}).get("parts", [])
        return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("Provider returned no choices.")
    message = choices[0].get("message") or {}
    raw = message.get("content")
    if isinstance(raw, str) and raw.strip():
        return raw
    if isinstance(raw, list):
        return "".join(
            str(part.get("text", "")) for part in raw
            if isinstance(part, dict) and part.get("type") == "text"
        )
    raise RuntimeError(
        f"Provider returned no final text (finish_reason={choices[0].get('finish_reason')})."
    )


def _validate_scene_result(raw, starts):
    match = re.search(r"\{.*\}", str(raw), re.S)
    if not match:
        raise RuntimeError(f"AI scene classifier returned no JSON: {str(raw)[:300]}")
    result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise RuntimeError("AI scene classifier JSON must be an object.")
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


def _openai_vision_request(provider_name, endpoint, api_key, model, content, timeout=180):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider_name == "OpenRouter":
        headers.update({
            "HTTP-Referer": "https://github.com/",
            "X-Title": "DramaClips Scene Classifier",
        })
    response = post_with_retry(
        endpoint,
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "max_tokens": 1800,
        },
        timeout=(30, timeout),
    )
    if response.status_code >= 400:
        detail = response.text[:900].replace(api_key, "[REDACTED]")
        raise RuntimeError(
            f"{provider_name} failed (HTTP {response.status_code}; model={model}): {detail}"
        )
    return _extract_model_text(response.json())


def _local_visual_fallback(frames, starts):
    """Deterministic CV fallback: choose the clearest, most visually active window."""
    from PIL import Image, ImageChops, ImageFilter, ImageStat

    best_index = None
    best_score = float("-inf")
    best_reason = ""
    for candidate_index in range(len(starts)):
        candidate_images = []
        for frame_index, encoded in frames:
            if frame_index != candidate_index:
                continue
            try:
                image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("L")
                image.thumbnail((256, 256))
                candidate_images.append(image)
            except Exception:
                continue
        if len(candidate_images) < 2:
            continue

        brightness = sum(ImageStat.Stat(image).mean[0] for image in candidate_images) / len(candidate_images)
        contrast = sum(ImageStat.Stat(image).stddev[0] for image in candidate_images) / len(candidate_images)
        edge_strength = sum(
            ImageStat.Stat(image.filter(ImageFilter.FIND_EDGES)).mean[0]
            for image in candidate_images
        ) / len(candidate_images)
        changes = []
        for previous, current in zip(candidate_images, candidate_images[1:]):
            difference = ImageChops.difference(previous, current)
            changes.append(ImageStat.Stat(difference).mean[0])
        motion_change = sum(changes) / max(1, len(changes))
        # Penalize near-black and nearly static windows; reward visible detail
        # and moderate frame-to-frame change. This is not a mood classifier.
        visibility = max(0.0, min(1.0, brightness / 70.0))
        score = (contrast * 0.35) + (edge_strength * 0.35) + (motion_change * 0.45) + (visibility * 12.0)
        if brightness < 12:
            score -= 35
        if score > best_score:
            best_score = score
            best_index = candidate_index
            best_reason = (
                f"Local visual fallback score={score:.1f}; selected for visible detail "
                "and frame-to-frame activity. Mood was not guessed."
            )

    if best_index is None:
        raise RuntimeError("Local visual fallback could not decode enough candidate frames.")
    log("All configured AI vision providers were unavailable; using deterministic local visual fallback.")
    return (
        starts[best_index],
        "interesting",
        best_reason,
        "A visually active drama moment selected by local frame analysis.",
    )


def classify_local_video(video_path, work_dir, excluded_starts=None):
    """Try configured vision providers in order, then use local CV as final fallback."""
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()


    clip = VideoFileClip(str(video_path))
    try:
        starts = pipeline.candidate_starts(clip.duration)
        excluded_starts = [float(value) for value in (excluded_starts or [])]
        starts = [
            candidate for candidate in starts
            if all(abs(candidate - previous) >= 100.0 for previous in excluded_starts)
        ]
        if not starts:
            raise NoUnusedSceneWindows(
                "This source has no remaining distinct scene windows; it will be marked complete."
            )
        log(f"Checking {len(starts)} unused candidate windows for this episode.")
        frames = []
        for index, start in enumerate(starts):
            for offset in (
                pipeline.CLIP_SECONDS * 0.20,
                pipeline.CLIP_SECONDS * 0.50,
                pipeline.CLIP_SECONDS * 0.80,
            ):
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
            '{"selected_candidate":0,"category":"interesting",'
            '"reason":"clear character reaction","scene_summary":"two characters react to news"}.'
        )
        openai_content = [{"type": "text", "text": prompt}]
        for index, encoded in frames:
            openai_content.append({"type": "text", "text": f"Candidate {index} frame:"})
            openai_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            })

        errors = []
        # Keep the fallback list aligned with the AI services configured in this
        # repository: Gemini direct API above, then OpenRouter if its secret exists.
        provider_specs = [
            (
                "OpenRouter",
                "OPENROUTER_API_KEY",
                "https://openrouter.ai/api/v1/chat/completions",
                os.getenv("OPENROUTER_MODEL", "").strip() or "google/gemini-2.5-flash",
            ),
        ]
        # Google model variants are attempted first; quota exhaustion may affect
        # the whole project, but another available model can still respond.
        if gemini_api_key:
            gemini_models = []
            configured = (os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.8-flash")
            for candidate in [configured, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
                if candidate and candidate not in gemini_models:
                    gemini_models.append(candidate)
            gemini_parts = [{"text": prompt}]
            for index, encoded in frames:
                gemini_parts.append({"text": f"Candidate {index} frame:"})
                gemini_parts.append({
                    "inline_data": {"mime_type": "image/jpeg", "data": encoded}
                })
            for model in gemini_models:
                try:
                    log(f"Trying Gemini vision model '{model}'.")
                    response = post_with_retry(
                        "https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{model}:generateContent",
                        headers={
                            "x-goog-api-key": gemini_api_key,
                            "Content-Type": "application/json",
                        },
                        json={
                            "contents": [{"parts": gemini_parts}],
                            "generationConfig": {
                                "temperature": 0.2,
                                "responseMimeType": "application/json",
                            },
                        },
                        timeout=(30, 180),
                    )
                    if response.status_code >= 400:
                        detail = response.text[:700].replace(gemini_api_key, "[REDACTED]")
                        raise RuntimeError(
                            f"HTTP {response.status_code}; model={model}: {detail}"
                        )
                    result = _validate_scene_result(_extract_model_text(response.json()), starts)
                    log(f"Scene classification succeeded with Gemini model '{model}'.")
                    return result
                except Exception as exc:
                    errors.append(f"Gemini/{model}: {str(exc)[:220]}")
                    log(f"Gemini model '{model}' unavailable; trying next provider/model.")

        # Every optional provider is skipped unless its API key is configured.
        for provider_name, key_name, endpoint, model in provider_specs:
            api_key = os.getenv(key_name, "").strip()
            if not api_key or not model:
                continue
            try:
                log(f"Trying {provider_name} vision model '{model}'.")
                raw = _openai_vision_request(
                    provider_name, endpoint, api_key, model, openai_content
                )
                result = _validate_scene_result(raw, starts)
                log(f"Scene classification succeeded with {provider_name} ({model}).")
                return result
            except Exception as exc:
                errors.append(f"{provider_name}/{model}: {str(exc)[:220]}")
                log(f"{provider_name} unavailable; trying the next configured provider.")

        if errors:
            log("Cloud AI fallback chain exhausted: " + " | ".join(errors[:8]))
        return _local_visual_fallback(frames, starts)
    finally:
        clip.close()

def clean_title_from_filename(filename):
    """Clean a drama filename into a readable title."""
    title = Path(filename or "").stem
    title = re.sub(r"\b(official|full|hd|4k|1080p|720p|480p)\b", " ", title, flags=re.I)
    title = title.replace("_", " ").replace("-", " ")
    title = re.sub(r"\s+", " ", title).strip(" ._-")
    return title[:80] or "Pakistani Drama"


def build_facebook_caption(source_title, category, reason="", scene_summary=""):
    """Create a scene-aware Facebook caption with exactly five relevant hashtags."""
    category = str(category or "interesting").strip().lower()
    allowed = {"action", "emotional", "comedy", "romantic", "suspense", "interesting"}
    if category not in allowed:
        category = "interesting"

    title = os.getenv("DRAMA_TITLE", "").strip() or clean_title_from_filename(source_title)
    default_descriptions = {
        "romantic": "A beautiful romantic moment filled with warmth and emotion. ❤️",
        "emotional": "A powerful emotional moment that touches the heart. 💔",
        "comedy": "A light-hearted moment that brings a smile. 😄",
        "action": "An intense moment packed with action and energy. ⚡",
        "suspense": "A gripping moment full of tension and suspense. 👀",
        "interesting": "A memorable drama moment worth watching. ✨",
    }
    description = default_descriptions[category]
    summary = re.sub(r"\s+", " ", str(scene_summary or "")).strip()
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
    return f"{title} | {category.title()} Scene\n\n{description}\n\n" + " ".join(hashtags)

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
        music_dir = Path(work_dir) / "drive_music"
        music_dir.mkdir(parents=True, exist_ok=True)
        audio_files = list_folder_audio(token, required_env("DRIVE_FOLDER_ID"))
        for audio_item in audio_files:
            audio_name = Path(audio_item.get("name") or audio_item["id"]).name
            audio_suffix = Path(audio_name).suffix.lower()
            if audio_suffix not in {".mp3", ".wav", ".m4a", ".aac"}:
                continue
            try:
                download_drive_file(
                    token, audio_item, music_dir / f"{audio_item['id']}{audio_suffix}"
                )
            except Exception as audio_error:
                log(f"Skipping unavailable music file '{audio_name}': {audio_error}")
        prior_starts = history.get("video_clips", {}).get(item["id"], [])
        try:
            start, category, reason, scene_summary = classify_local_video(
                source_path, work_dir, excluded_starts=prior_starts
            )
        except NoUnusedSceneWindows as exc:
            pipeline.save_history(history, item["id"])
            log(f"EPISODE COMPLETE: {exc}")
            return
        except Exception as exc:
            log(
                f"SCENE ANALYSIS DEFERRED ({type(exc).__name__}): {str(exc)[:700]}. "
                "No clip was rendered or queued; this Drive video remains unprocessed "
                "and will be retried on the next run."
            )
            return
        log(f"AI selected {category} scene at {start:.1f}s: {reason or 'no reason returned'}")
        output_path = pipeline.OUTPUT_DIR / "pakistani_drama_clip.mp4"
        clip_seconds = min(90, pipeline.adaptive_clip_seconds(source_path, start, category))
        log(f"Facebook Reel duration safety cap applied: {clip_seconds}s (maximum 90s).")
        music_meta = pipeline.render_clip(
            source_path, start, category, output_path,
            clip_seconds=clip_seconds, music_dir=music_dir
        )
        public_url = pipeline.upload_cloudinary(output_path)
        from publisher.buffer import queue_facebook_reel
        caption = build_facebook_caption(
            item.get("name", "Pakistani Drama"),
            category,
            reason=reason,
            scene_summary=scene_summary,
        )
        queued = queue_facebook_reel(public_url, caption)
        pipeline.save_history(history, item["id"], clip_start=start, max_clips=4)
        log(
            f"SUCCESS: queued one {category} clip. Buffer post ID={queued.get('id')}; "
            f"file={item.get('name')}; duration={clip_seconds}s; music="
            f"{music_meta.get('title') or 'original instrumental'}"
        )
    if output_path.exists():
        output_path.unlink()


if __name__ == "__main__":
    main()
