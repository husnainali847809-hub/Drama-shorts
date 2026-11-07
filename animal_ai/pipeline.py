"""Fal-powered scene generation and local assembly. Never publishes automatically."""
import json
import os
import subprocess
from pathlib import Path

import edge_tts
import fal_client
import requests

from animal_ai.story import CHARACTERS, SCENES, STYLE, NEGATIVE, TITLE, CAPTION

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "animal_pilot"
OUT.mkdir(parents=True, exist_ok=True)
IMAGE_MODEL = os.getenv("FAL_IMAGE_MODEL", "fal-ai/flux-pro/kontext/max/text-to-image")
EDIT_MODEL = os.getenv("FAL_EDIT_MODEL", "fal-ai/flux-pro/kontext/max/multi")
VIDEO_MODEL = os.getenv("FAL_VIDEO_MODEL", "fal-ai/kling-video/v3/standard/image-to-video")


def run(cmd):
    subprocess.run(cmd, check=True, timeout=1800)


def fal_image(prompt, path):
    result = fal_client.subscribe(IMAGE_MODEL, arguments={
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "num_images": 1,
        "output_format": "png",
        "safety_tolerance": "2",
    })
    url = result["images"][0]["url"]
    download(url, path)
    return url


def download(url, path):
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    Path(path).write_bytes(response.content)


def create_reference_images():
    refs = {}
    for key, description in CHARACTERS.items():
        path = OUT / f"reference_{key}.png"
        if path.exists():
            # Reuse approved references on reruns for character consistency.
            refs[key] = fal_client.upload_file(str(path))
            continue
        prompt = (
            f"Full-body character turnaround-style hero portrait of {description}. "
            f"{STYLE}. Plain softly lit jungle-green studio background, centered, "
            "entire character visible, no other animals, no text."
        )
        fal_image(prompt, path)
        refs[key] = fal_client.upload_file(str(path))
    return refs


def make_scene_image(scene, refs, index):
    path = OUT / f"scene_{index:02d}.png"
    if path.exists():
        return fal_client.upload_file(str(path))
    prompt = (
        f"Create one coherent vertical 9:16 cinematic frame. {scene['visual']} "
        f"Character reference 1 is Timo: {CHARACTERS['timo']}. "
        f"Character reference 2 is Bunny: {CHARACTERS['bunny']}. "
        f"Preserve exact facial features, fur colors, proportions and markings from references. "
        f"{STYLE}. No text, no watermark. Avoid: {NEGATIVE}"
    )
    result = fal_client.subscribe(EDIT_MODEL, arguments={
        "prompt": prompt,
        "image_urls": [refs["timo"], refs["bunny"]],
        "num_images": 1,
        "output_format": "png",
        "safety_tolerance": "2",
    })
    url = result["images"][0]["url"]
    download(url, path)
    return fal_client.upload_file(str(path))


def make_scene_video(scene, image_url, index):
    path = OUT / f"scene_{index:02d}.mp4"
    if path.exists():
        return path
    prompt = (
        f"{scene['motion']} {STYLE}. Camera motion must be subtle and cinematic. "
        f"Keep the same character identity and anatomy as the input frame. "
        f"Negative: {NEGATIVE}"
    )
    result = fal_client.subscribe(VIDEO_MODEL, arguments={
        "prompt": prompt,
        "start_image_url": image_url,
        "duration": str(scene["seconds"]),
        "generate_audio": False,
        "negative_prompt": NEGATIVE,
        "enable_safety_checker": True,
    })
    download(result["video"]["url"], path)
    return path


async def make_voice(lines, output):
    # Alternating English and Pakistani Urdu lines; user can replace voice IDs.
    chunks = []
    for i, (language, text) in enumerate(lines):
        voice = os.getenv(
            "TTS_EN_VOICE" if language == "en" else "TTS_UR_VOICE",
            "en-US-GuyNeural" if language == "en" else "ur-PK-AsadNeural",
        )
        chunk = OUT / f"voice_{i:02d}.mp3"
        await edge_tts.Communicate(text, voice).save(str(chunk))
        chunks.append(chunk)
    listing = OUT / "voice_concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in chunks), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(output)])


def assemble(clips, voice_path):
    listing = OUT / "video_concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips), encoding="utf-8")
    silent = OUT / "joined_silent.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1",
         "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(silent)])
    final = OUT / "PILOT_Timo_and_Bunny_REVIEW_ONLY.mp4"
    run(["ffmpeg", "-y", "-i", str(silent), "-i", str(voice_path),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)])
    return final


def validate(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height",
         "-of", "json", str(path)], capture_output=True, text=True, check=True
    )
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    video = next(s for s in data["streams"] if s.get("width"))
    if not 60 <= duration <= 90:
        raise RuntimeError(f"Pilot duration {duration:.1f}s is outside 60–90 seconds.")
    if (video["width"], video["height"]) != (1080, 1920):
        raise RuntimeError(f"Unexpected video dimensions: {video['width']}x{video['height']}")
    return duration


def generate_pilot():
    if not os.getenv("FAL_KEY"):
        raise RuntimeError("Set the FAL_KEY GitHub secret before generating AI scenes. Generation is paid and may incur provider charges.")
    refs = create_reference_images()
    clips = []
    narration = []
    for index, scene in enumerate(SCENES, start=1):
        print(f"Generating scene {index}/{len(SCENES)}: {scene['name']}", flush=True)
        image_url = make_scene_image(scene, refs, index)
        clips.append(make_scene_video(scene, image_url, index))
        narration.extend([("en", scene["en"]), ("ur", scene["ur"])])
    import asyncio
    voice = OUT / "bilingual_voice.mp3"
    asyncio.run(make_voice(narration, voice))
    final = assemble(clips, voice)
    duration = validate(final)
    (OUT / "review_metadata.json").write_text(json.dumps({
        "title": TITLE, "caption": CAPTION, "duration_seconds": round(duration, 2),
        "status": "REVIEW_REQUIRED_NOT_PUBLISHED",
        "scenes": [s["name"] for s in SCENES],
    }, indent=2), encoding="utf-8")
    print(f"REVIEW FILE: {final}")
    print("NOT PUBLISHED. Review the MP4 manually before any Facebook upload.")
    return final
