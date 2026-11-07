"""Generate original 5–10 minute narrated cartoon stories for Facebook video posts.

This deliberately creates original artwork and scripts. It does not download or re-upload
third-party cartoons. Rendering is 16:9 landscape so Facebook receives a native video post,
not a vertical Reel with a shorter duration limit.
"""
import asyncio
import json
import logging
import math
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFont

import main as core

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work" / "longform"
OUTPUT = ROOT / "output"
WIDTH, HEIGHT, FPS = 1280, 720, 24
GENRES = {
    "comedy": "funny animal comedy with clever jokes and a satisfying playful twist",
    "kids-adventure": "gentle, colorful, age-appropriate adventure for children with teamwork",
    "moral-story": "an emotionally engaging story that naturally teaches kindness, honesty, or courage",
    "fantasy": "magical fantasy adventure with original creatures, wonder, and clear stakes",
    "mystery": "family-friendly mystery with clues, red herrings, and a fair surprising reveal",
    "horror": "mild atmospheric spooky suspense, eerie mystery, and a clever reveal; no gore or graphic violence",
    "adventure": "exciting animal adventure with obstacles, teamwork, and a strong ending",
}
log = logging.getLogger("longform_cartoon")


def font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def wrap_text(draw, value, face, max_width):
    lines, current = [], ""
    for word in str(value).split():
        candidate = (current + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=face)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_story(genre, minutes):
    key = core.need("OPENROUTER_API_KEY")
    scene_count = minutes * 4
    target_words = minutes * 145
    prompt = f"""Create a completely ORIGINAL English animated cartoon story for a worldwide Facebook audience.
Genre: {genre}. Style: {GENRES[genre]}.
Target runtime: {minutes} minutes of natural English narration, about {target_words} spoken words.
Return valid JSON only in this exact shape:
{{"title":"short original title","caption":"engaging Facebook description with 3-5 relevant hashtags",
"characters":[{{"name":"unique name","species":"cat"}}],
"scenes":[{{"visual":"one clear visual action, 8-18 words","narration":"spoken narration, 32-45 words"}}]}}
Requirements:
- Exactly 2 original animal characters; keep names and species identical in every scene.
- Exactly {scene_count} scenes, in chronological order, with a beginning, rising conflict, climax, and satisfying ending.
- Total narration should be approximately {target_words} words; do not shorten the story.
- Each scene narration must contain 32-45 spoken words. Use natural dialogue and narration.
- Each scene must advance the plot; avoid repeating the same event or padding.
- Write for the selected genre. For horror, use atmosphere and suspense only, no gore or graphic violence.
- No copyrighted characters, franchises, existing cartoon plots, brands, celebrities, or copied scripts.
- Make the story understandable without relying on copyrighted references.
- Caption must be under 450 characters and include a few relevant hashtags.
Return JSON only, with no markdown fences."""
    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         "X-Title": "Original Longform Cartoon Studio"},
                json={"model": "openrouter/free",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.85, "max_tokens": 7000},
                timeout=150,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            if isinstance(raw, list):
                raw = "".join(x.get("text", "") for x in raw if isinstance(x, dict))
            cleaned = re.sub(r"^\s*```(?:json)?", "", str(raw).strip(), flags=re.I)
            cleaned = re.sub(r"```\s*$", "", cleaned)
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Model did not return a JSON object")
            story = json.loads(cleaned[start:end + 1])
            if not isinstance(story.get("characters"), list) or len(story["characters"]) != 2:
                raise ValueError("Story must contain exactly two characters")
            if not isinstance(story.get("scenes"), list) or len(story["scenes"]) != scene_count:
                raise ValueError(f"Story must contain exactly {scene_count} scenes")
            for character in story["characters"]:
                if not isinstance(character, dict):
                    raise ValueError("Invalid character")
                character["name"] = str(character.get("name", "Pal"))[:24]
                character["species"] = str(character.get("species", "fox")).lower()[:20]
            total_words = 0
            for scene in story["scenes"]:
                if not isinstance(scene, dict):
                    raise ValueError("Invalid scene")
                scene["visual"] = str(scene.get("visual", "The friends explore a new place"))[:180]
                scene["narration"] = str(scene.get("narration", "")).strip()
                words = len(scene["narration"].split())
                if not 25 <= words <= 65:
                    raise ValueError(f"Scene narration length outside safe range: {words} words")
                total_words += words
            if total_words < target_words * 0.78:
                raise ValueError(f"Story too short: {total_words} words; target about {target_words}")
            story["title"] = str(story.get("title", "The Hidden Valley"))[:80]
            story["caption"] = str(story.get("caption", f"An original {genre} cartoon story. #AnimatedStory"))[:450]
            log.info("Original %s story generated: %s (%s scenes, %s words)",
                     genre, story["title"], scene_count, total_words)
            return story
        except Exception as exc:
            last_error = exc
            log.warning("Story generation attempt %s/3 failed: %s", attempt + 1, exc)
            if attempt < 2:
                awaitable = asyncio.sleep(4 * (attempt + 1))
                asyncio.run(awaitable)
    raise RuntimeError(f"Could not generate a complete {minutes}-minute original story: {last_error}")


def palette(genre):
    if genre == "horror":
        return ("#17243B", "#344B64", "#182D2A", "#E7D8B0", "#E8B85A")
    if genre in ("fantasy", "mystery"):
        return ("#493D76", "#A78AC8", "#304C65", "#F4E9CE", "#F6D36B")
    return ("#74C9E8", "#DDF4F6", "#5BA76B", "#FFF4DC", "#F6D36B")


def draw_scene(story, scene, index, genre, image_path, brand):
    im = Image.new("RGB", (WIDTH, HEIGHT), "#DDF4F6")
    d = ImageDraw.Draw(im)
    sky, horizon, ground, cream, accent = palette(genre)
    for y in range(HEIGHT):
        k = y / HEIGHT
        c1 = tuple(int(sky[i:i+2], 16) for i in (1, 3, 5))
        c2 = tuple(int(horizon[i:i+2], 16) for i in (1, 3, 5))
        color = tuple(int(c1[j] * (1-k) + c2[j] * k) for j in range(3))
        d.line((0, y, WIDTH, y), fill=color)
    # Layered hills and a simple scene-specific environment.
    d.ellipse((-180, 360, 620, 900), fill=ground)
    d.ellipse((500, 390, 1450, 900), fill=ground)
    d.ellipse((80, 430, 360, 690), fill=accent)
    d.ellipse((930, 400, 1200, 700), fill=accent)
    if genre == "horror":
        for x in (120, 1080):
            d.rectangle((x-18, 250, x+18, 590), fill="#26352E")
            for ox, oy, radius in [(-55, 290, 80), (45, 270, 95), (0, 190, 100)]:
                d.ellipse((x+ox-radius, oy-radius, x+ox+radius, oy+radius), fill="#26352E")
        d.ellipse((930, 75, 1080, 225), fill="#E7E0C8")
    else:
        d.ellipse((1010, 65, 1140, 195), fill="#FFE58A")
        for x in (100, 1160):
            d.rectangle((x-15, 330, x+15, 610), fill="#80583C")
            for ox, oy, radius in [(-45, 310, 65), (40, 285, 75), (0, 235, 70)]:
                d.ellipse((x+ox-radius, oy-radius, x+ox+radius, oy+radius), fill="#32865B")
    # Header and scene cue.
    d.rounded_rectangle((28, 24, WIDTH-28, 132), radius=26, fill="#17243C", outline="#FFFFFF", width=3)
    d.text((58, 39), brand[:30], font=font(25, True), fill=accent)
    d.text((58, 77), story["title"][:55], font=font(27, True), fill="white")
    d.rounded_rectangle((35, 150, WIDTH-35, 232), radius=22, fill=cream, outline="#17243C", width=3)
    cue_lines = wrap_text(d, scene["visual"], font(25, True), WIDTH-100)[:2]
    for row, line in enumerate(cue_lines):
        d.text((62, 162 + row*31), line, font=font(25, True), fill="#17243C")
    # Two consistent, original animal mascots.
    species_colors = {"dog":"#C98A52","cat":"#E7A35A","rabbit":"#E8D5C7","fox":"#D96D35",
                      "bear":"#8C654C","panda":"#F3F3F3","monkey":"#A96F45","duck":"#F5D447",
                      "lion":"#C78B39","pig":"#F2A6A6","wolf":"#9BA9B8","owl":"#9A7654"}
    for ci, character in enumerate(story["characters"]):
        cx = 430 if ci == 0 else 850
        cy = 420 + (ci * 18)
        fur = species_colors.get(character["species"], "#91AFC0")
        # Body, face, ears, eyes, smile and feet.
        d.ellipse((cx-82, cy+35, cx+82, cy+235), fill=fur, outline="#263047", width=6)
        d.ellipse((cx-95, cy-105, cx+95, cy+90), fill=fur, outline="#263047", width=6)
        if character["species"] == "rabbit":
            d.ellipse((cx-65, cy-245, cx-12, cy-45), fill=fur, outline="#263047", width=5)
            d.ellipse((cx+12, cy-245, cx+65, cy-45), fill=fur, outline="#263047", width=5)
        elif character["species"] in ("cat", "fox", "wolf"):
            d.polygon([(cx-85,cy-55),(cx-60,cy-180),(cx-5,cy-80)], fill=fur, outline="#263047")
            d.polygon([(cx+5,cy-80),(cx+60,cy-180),(cx+85,cy-55)], fill=fur, outline="#263047")
        else:
            d.ellipse((cx-105,cy-100,cx-50,cy-35), fill=fur, outline="#263047", width=4)
            d.ellipse((cx+50,cy-100,cx+105,cy-35), fill=fur, outline="#263047", width=4)
        for eye in (-38, 38):
            d.ellipse((cx+eye-12,cy-35,cx+eye+12,cy-3), fill="white", outline="#263047", width=2)
            d.ellipse((cx+eye-5,cy-26,cx+eye+5,cy-8), fill="#17243C")
        d.ellipse((cx-10,cy+5,cx+10,cy+20), fill="#17243C")
        d.arc((cx-34,cy+13,cx+34,cy+64), 10, 170, fill="#17243C", width=4)
        d.ellipse((cx-72,cy+218,cx-10,cy+252), fill="#263047")
        d.ellipse((cx+10,cy+218,cx+72,cy+252), fill="#263047")
        d.rounded_rectangle((cx-95,cy+265,cx+95,cy+309), radius=15, fill="white", outline="#263047", width=3)
        label = character["name"][:18]
        box = d.textbbox((0,0), label, font=font(21,True))
        d.text((cx-(box[2]-box[0])/2,cy+275), label, font=font(21,True), fill="#17243C")
    # Burn in narration as readable subtitles for viewers watching without sound.
    narration_lines = wrap_text(d, scene["narration"], font(23, True), WIDTH-100)
    narration_lines = narration_lines[:4]
    top = HEIGHT - 190
    d.rounded_rectangle((30, top, WIDTH-30, HEIGHT-28), radius=25, fill="#17243C", outline=accent, width=4)
    for row, line in enumerate(narration_lines):
        box = d.textbbox((0,0), line, font=font(23,True))
        d.text(((WIDTH-(box[2]-box[0]))//2, top+20+row*37), line, font=font(23,True), fill="white")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(image_path, format="JPEG", quality=90, optimize=True)


async def make_voice(text, path):
    voice = os.getenv("TTS_VOICE", "en-US-AriaNeural")
    await edge_tts.Communicate(text=text, voice=voice, rate="+0%").save(str(path))


def render_long_video(story, genre, minutes):
    for executable in ("ffmpeg", "ffprobe"):
        core.run([executable, "-version"])
    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for old in WORK.glob("*"):
        if old.is_file():
            old.unlink()
        elif old.is_dir():
            import shutil
            shutil.rmtree(old)
    brand = os.getenv("BUFFER_EXPECTED_CHANNEL_NAME", core.EXPECTED_PAGE).strip() or "Animated Cartoons"
    segments = []
    total_audio = 0.0
    for index, scene in enumerate(story["scenes"]):
        image_path = WORK / f"scene_{index+1:02d}.jpg"
        audio_path = WORK / f"voice_{index+1:02d}.mp3"
        segment_path = WORK / f"segment_{index+1:02d}.mp4"
        draw_scene(story, scene, index, genre, image_path, brand)
        asyncio.run(make_voice(scene["narration"], audio_path))
        audio_seconds = float(core.run(["ffprobe","-v","error","-show_entries","format=duration",
                                        "-of","default=noprint_wrappers=1:nokey=1",str(audio_path)]))
        total_audio += audio_seconds
        seconds = audio_seconds + 0.45
        zoom = "scale=1280:720,zoompan=z='min(zoom+0.00035,1.035)':d=1:s=1280x720:fps=24,format=yuv420p"
        core.run(["ffmpeg","-y","-loop","1","-framerate",str(FPS),"-i",str(image_path),
                  "-i",str(audio_path),"-t",f"{seconds:.2f}","-vf",zoom,
                  "-r",str(FPS),"-c:v","libx264","-preset","ultrafast","-crf","25",
                  "-threads","2","-c:a","aac","-b:a","128k","-shortest",str(segment_path)])
        segments.append(segment_path)
        log.info("Rendered scene %s/%s", index+1, len(story["scenes"]))
    concat = WORK / "concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8")
    slug = re.sub(r"[^a-z0-9]+","-",story["title"].lower()).strip("-")[:38] or "original-cartoon"
    output = OUTPUT / f"cartoon-{datetime.now(timezone.utc):%Y%m%d}-{slug}.mp4"
    core.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),
              "-c","copy","-movflags","+faststart",str(output)])
    info = json.loads(core.run(["ffprobe","-v","error","-show_entries",
                                "format=duration,size:stream=codec_type,width,height,r_frame_rate",
                                "-of","json",str(output)]))
    video = next((s for s in info.get("streams",[]) if s.get("codec_type")=="video"), None)
    duration = float(info["format"]["duration"])
    size = int(info["format"].get("size", 0))
    if not video or (video.get("width"),video.get("height")) != (WIDTH,HEIGHT):
        raise RuntimeError("Final video failed 1280x720 landscape validation.")
    if not (minutes*60*0.82 <= duration <= minutes*60*1.20):
        raise RuntimeError(f"Final narration duration {duration/60:.1f} minutes is outside target for {minutes} minutes.")
    if size > 950_000_000:
        raise RuntimeError("Video exceeds the safe 950 MB upload limit for Buffer/Facebook.")
    log.info("Long-form cartoon rendered: %.1f minutes, %.1f MB, %s", duration/60, size/1_000_000, output)
    return output


def run():
    genre = os.getenv("CARTOON_GENRE", "comedy").strip().lower()
    if genre not in GENRES:
        raise RuntimeError(f"Unsupported CARTOON_GENRE '{genre}'. Allowed: {', '.join(GENRES)}")
    try:
        minutes = int(os.getenv("CARTOON_DURATION_MINUTES", "7"))
    except ValueError as exc:
        raise RuntimeError("CARTOON_DURATION_MINUTES must be 5, 7, or 10.") from exc
    if minutes not in (5, 7, 10):
        raise RuntimeError("CARTOON_DURATION_MINUTES must be 5, 7, or 10.")
    today = datetime.now(timezone.utc).date().isoformat()
    previous, sha = core.read_state()
    if previous == today:
        log.info("Already queued one long-form cartoon for %s; skipping duplicate.", today)
        return
    core.verify_channel()
    story = generate_story(genre, minutes)
    log.info("Producing %s-minute %s cartoon: %s", minutes, genre, story["title"])
    video = render_long_video(story, genre, minutes)
    public_url = core.upload_video(video)
    post = core.queue_reel(public_url, story["caption"], post_type="post")
    core.write_state(today, sha)
    log.info("COMPLETE: Buffer accepted Facebook video post %s. Facebook publication still needs confirmation.", post["id"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    run()
