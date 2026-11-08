import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cloudinary
import cloudinary.uploader
import edge_tts
import requests

from config import OUTPUT_DIR
from mixed_content.research import find_licensed_images, get_research
from publisher.buffer import queue_facebook_reel, verify_channel

log = logging.getLogger("hindi-mixed-content")
ROOT = Path(__file__).resolve().parents[1]
WORK = OUTPUT_DIR / "mixed_content"
VOICE = os.getenv("HINDI_TTS_VOICE", "hi-IN-SwaraNeural")
MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
SCHEDULES = {
    "0 3 * * *": "movie_explainer",
    "0 6 * * *": "anime_style",
    "0 9 * * *": "documentary",
    "0 12 * * *": "real_story",
    "0 15 * * *": "original_story",
}
LABELS = {
    "movie_explainer": "Movie Explanation",
    "anime_style": "Anime-Inspired Story",
    "documentary": "Mini Documentary",
    "real_story": "True Story",
    "original_story": "Original Hindi Story",
}

def need(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required GitHub Secret/Variable is missing: {name}")
    return value

def choose_category():
    cron = os.getenv("MIXED_SLOT_CRON", "").strip()
    if cron in SCHEDULES:
        return SCHEDULES[cron]
    day = datetime.now(timezone.utc).timetuple().tm_yday
    return list(LABELS)[day % len(LABELS)]

def make_script(research, category):
    prompt = f"""
Write an original Hindi narration for a Facebook Reel.
Category: {LABELS[category]}
Topic: {research['title']}
Editorial angle: {research.get('editorial_angle', 'Accurate Hindi explainer.')}
Source facts:
{research['source_text'][:8000]}

Return ONLY JSON: {{"title":"Hindi title","segments":["part 1","part 2","part 3","part 4","part 5"],"caption":"Hindi caption"}}
Exactly five segments, each 32-44 words, 170-215 words total.
Use natural spoken Hindi in Devanagari. Hook immediately, tell a coherent story, end strongly.
Use original wording; no copied dialogue, screenplay, lyrics or long source passages.
Never invent facts beyond the supplied source. Original-story category must be fictional and use no known characters.
"""
    key = need("OPENROUTER_API_KEY")
    models = [MODEL, "meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen3-4b:free"]
    error = None
    for model in dict.fromkeys(models):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         "HTTP-Referer": "https://github.com/husnainali847809-hub/animals-ai-automation",
                         "X-Title": "Hindi Mixed Content Factory"},
                json={"model": model, "messages": [
                    {"role": "system", "content": "You are a careful Hindi scriptwriter. Return JSON only."},
                    {"role": "user", "content": prompt}],
                    "temperature": 0.65, "max_tokens": 1800,
                    "response_format": {"type": "json_object"}},
                timeout=90,
            )
            response.raise_for_status()
            choices = response.json().get("choices") or []
            raw = (choices[0].get("message") or {}).get("content") if choices else ""
            if isinstance(raw, list):
                raw = "".join(str(x.get("text", "")) for x in raw if isinstance(x, dict))
            raw = str(raw or "").strip()
            raw = raw.replace(chr(96) * 3 + "json", "").replace(chr(96) * 3, "").strip()
            result = json.loads(raw)
            segments = result.get("segments")
            if not isinstance(segments, list) or len(segments) != 5:
                raise ValueError("AI must return exactly five narration segments.")
            segments = [re.sub(r"\s+", " ", str(x)).strip() for x in segments]
            count = sum(len(x.split()) for x in segments)
            if not 155 <= count <= 230 or any(len(x.split()) < 25 for x in segments):
                raise ValueError(f"Unsuitable narration length: {count} words.")
            result["segments"] = segments
            result["title"] = str(result.get("title") or research["title"])[:90]
            result["caption"] = str(result.get("caption") or result["title"])[:350]
            result["_model"] = model
            return result
        except Exception as exc:
            error = exc
            log.warning("Free script model %s failed: %s", model, exc)
    raise RuntimeError(f"No free OpenRouter model returned a valid Hindi script: {error}")

def download_images(items):
    WORK.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, item in enumerate(items, 1):
        path = WORK / f"visual_{i:02d}.jpg"
        response = requests.get(item["url"], stream=True, timeout=(20, 60))
        response.raise_for_status()
        size = 0
        with path.open("wb") as out:
            for chunk in response.iter_content(512 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > 20 * 1024 * 1024:
                    raise RuntimeError("A Commons image exceeded 20 MB.")
                out.write(chunk)
        if size >= 2048:
            paths.append(path)
        else:
            path.unlink(missing_ok=True)
    if len(paths) < 3:
        raise RuntimeError("Fewer than three valid licensed visuals downloaded.")
    return paths

async def create_voice(segments):
    files = []
    for i, text in enumerate(segments, 1):
        path = WORK / f"voice_{i:02d}.mp3"
        await edge_tts.Communicate(text, VOICE, rate="+0%").save(str(path))
        if not path.exists() or path.stat().st_size < 1000:
            raise RuntimeError(f"Hindi voice generation failed for segment {i}.")
        files.append(path)
    return files

def duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True, timeout=30)
    return float(result.stdout.strip())

def ffmpeg(args):
    subprocess.run(args, check=True, timeout=900)

def render(images, voice_files, segments, category, output):
    audio_list = WORK / "audio.txt"
    audio_list.write_text("".join(f"file '{p.as_posix()}'\n" for p in voice_files), encoding="utf-8")
    voice = WORK / "voice_full.mp3"
    ffmpeg(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
            "-safe", "0", "-i", str(audio_list), "-c:a", "libmp3lame", "-q:a", "3", str(voice)])
    voice_duration = duration(voice)
    if not 72 <= voice_duration <= 86.5:
        raise RuntimeError(f"Voice duration {voice_duration:.1f}s is outside production limits.")

    font = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"
    if not Path(font).is_file():
        font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    clips = []
    for i, line in enumerate(segments):
        image = images[i % len(images)]
        subtitle = WORK / f"caption_{i + 1}.txt"
        words = line.split()
        rows, current = [], []
        for word in words:
            current.append(word)
            if len(" ".join(current)) > 34:
                rows.append(" ".join(current[:-1]))
                current = [word]
        if current:
            rows.append(" ".join(current))
        subtitle.write_text("\\n".join(rows), encoding="utf-8")
        seconds = duration(voice_files[i])
        clip = WORK / f"scene_{i + 1}.mp4"
        look = ("eq=saturation=1.55:contrast=1.10,unsharp=5:5:0.8:3:3:0.0"
                if category == "anime_style" else "eq=saturation=1.18:contrast=1.04")
        vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
              "zoompan=z='min(zoom+0.00045,1.08)':d=1:s=1080x1920:fps=30,"
              + look + f",drawtext=fontfile={font}:textfile={subtitle}:fontcolor=white:fontsize=46:"
              "box=1:boxcolor=black@0.62:boxborderw=24:x=(w-text_w)/2:y=h-text_h-180:text_shaping=1")
        ffmpeg(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-framerate", "30", "-i", str(image),
                "-t", f"{seconds:.3f}", "-vf", vf, "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                "-r", "30", "-movflags", "+faststart", str(clip)])
        clips.append(clip)

    video_list = WORK / "video.txt"
    video_list.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips), encoding="utf-8")
    silent = WORK / "silent.mp4"
    ffmpeg(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
            "-safe", "0", "-i", str(video_list), "-c:v", "libx264", "-preset",
            "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30", str(silent)])
    music = WORK / "original_music.wav"
    tones = "0.035*sin(2*PI*110*t)+0.025*sin(2*PI*164.81*t)+0.018*sin(2*PI*220*t)"
    ffmpeg(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", f"aevalsrc={tones}:s=44100:d=90", "-af",
            "lowpass=f=5000,afade=t=in:st=0:d=2,afade=t=out:st=84:d=3",
            "-c:a", "pcm_s16le", str(music)])
    ffmpeg(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(silent), "-i", str(voice), "-i", str(music),
            "-vf", "tpad=stop_mode=clone:stop_duration=30",
            "-filter_complex",
            "[1:a]volume=1.0[v];[2:a]volume=0.12[m];"
            "[v][m]amix=inputs=2:duration=longest:dropout_transition=2:normalize=0,"
            "alimiter=limit=0.95[a]",
            "-map", "0:v:0", "-map", "[a]", "-t", "87",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(output)])
    if not 85 <= duration(output) <= 89:
        raise RuntimeError("Final Reel duration failed the 85–89 second quality check.")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "json", str(output)],
                           check=True, capture_output=True, text=True, timeout=30)
    video = json.loads(probe.stdout)["streams"][0]
    if (video.get("width"), video.get("height")) != (1080, 1920):
        raise RuntimeError("Final Reel resolution is not 1080x1920.")
    return voice_duration

def upload(path, category):
    cloudinary.config(cloud_name=need("CLOUDINARY_CLOUD_NAME"),
                      api_key=need("CLOUDINARY_API_KEY"),
                      api_secret=need("CLOUDINARY_API_SECRET"), secure=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    result = cloudinary.uploader.upload(
        str(path), resource_type="video", folder="mixed-content-factory",
        public_id=f"{category}-{stamp}", overwrite=False, unique_filename=False)
    url = str(result.get("secure_url") or "")
    if not url.startswith("https://res.cloudinary.com/"):
        raise RuntimeError("Cloudinary did not return a public HTTPS video URL.")
    return url

def run_once():
    WORK.mkdir(parents=True, exist_ok=True)
    category = choose_category()
    log.info("Hindi Mixed Content Factory | %s | destination=Animated Jungle", category)
    channel = verify_channel()
    channel_name = channel.get("displayName") or channel.get("name") or ""
    if channel_name.strip().casefold() != "animated jungle":
        raise RuntimeError(f"Safety stop: expected Animated Jungle, got {channel_name!r}.")
    day = datetime.now(timezone.utc).timetuple().tm_yday
    research = get_research(category, day)
    with sqlite3.connect(ROOT / "history.sqlite3") as db:
        db.execute("""CREATE TABLE IF NOT EXISTS mixed_content_history (
            topic_key TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
            post_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        key = f"{category}:{research['title'].casefold()}"
        if db.execute("SELECT 1 FROM mixed_content_history WHERE topic_key=?", (key,)).fetchone():
            raise RuntimeError("Duplicate topic blocked; nothing was published.")
    script = make_script(research, category)
    images_meta = find_licensed_images(research["search_terms"], limit=3)
    images = download_images(images_meta)
    voice_files = asyncio.run(create_voice(script["segments"]))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = WORK / f"{category}-{stamp}.mp4"
    voice_duration = render(images, voice_files, script["segments"], category, output)
    if not output.is_file() or output.stat().st_size < 2_000_000:
        raise RuntimeError("Quality gate failed: output file is missing or too small.")
    credits = [f"{x['creator']} — {x['title']} ({x['license_url']}) {x['page_url']}" for x in images_meta]
    caption = (script["caption"] + f"\n\nFormat: {LABELS[category]} | Hindi narration | Original editing and music."
               + (f"\nText: Wikipedia contributors, {research['title']} — {research['source_url']} (CC BY-SA 4.0). This adapted script/video is shared under CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/"
                  if research.get("source_url") else "\nStory: Original AI-generated fiction.")
               + "\nVisual credits: " + " | ".join(credits))
    if len(caption) > 1800:
        raise RuntimeError("Attribution text exceeds Buffer caption limit; refusing to publish without full credits.")
    public_url = upload(output, category)
    post = queue_facebook_reel(public_url, caption)
    with sqlite3.connect(ROOT / "history.sqlite3") as db:
        db.execute("INSERT OR REPLACE INTO mixed_content_history(topic_key,category,title,post_id) VALUES(?,?,?,?)",
                   (f"{category}:{research['title'].casefold()}", category, research["title"], post["id"]))
    metadata = {"category": category, "title": script["title"], "source_url": research.get("source_url", ""),
                "duration_seconds": 87, "voice_seconds": voice_duration, "resolution": "1080x1920",
                "fps": 30, "voice": VOICE, "script_model": script["_model"],
                "destination": channel_name, "buffer_post_id": post["id"],
                "status": "BUFFER_QUEUE_ACCEPTED", "visual_credits": credits}
    (WORK / f"{category}-{stamp}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Buffer accepted %s Reel for %s. post_id=%s dueAt=%s",
             category, channel_name, post["id"], post.get("dueAt"))
    return post

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_once()
