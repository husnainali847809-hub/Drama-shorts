#!/usr/bin/env python3
"""AI anime pilot: Fal image generation + Kling image-to-video + Urdu TTS.
Standalone demo only. Does not read drama footage or publish to any platform.
"""
import asyncio, os, subprocess, tempfile, requests
from pathlib import Path
import fal_client

OUT = Path("demo_output/ai_anime_demo.mp4")
OUT.parent.mkdir(parents=True, exist_ok=True)
FAL_KEY = os.environ.get("FAL_KEY")
if not FAL_KEY:
    raise SystemExit("Missing FAL_KEY GitHub Actions secret. Add a Fal.ai API key to run AI video generation.")

os.environ["FAL_KEY"] = FAL_KEY
FFMPEG = "ffmpeg"

CHARACTERS = (
    "Two consistent fictional adult Pakistani anime characters, both clearly adults, "
    "Ayesha age 24 with long dark hair and teal shalwar kameez, Hamza age 26 with short "
    "dark hair and navy kurta. High-end 2D anime film illustration, expressive readable "
    "faces, detailed cinematic living room at night, warm practical lighting, vertical "
    "9:16 composition, polished professional anime art, no text, no watermark."
)
SCENES = [
    ("Ayesha turns toward Hamza, raises one hand with a worried expression, her hair and "
     "clothes move naturally, subtle camera push-in, expressive anime acting.",
     "عائشہ: تم نے مجھ سے سچ کیوں چھپایا؟", "ur-PK-UzmaNeural"),
    ("Hamza looks down, then slowly looks up and gestures with an open hand, regretful "
     "expression, natural body movement, subtle camera movement.",
     "حمزہ: میں تمہیں پریشان نہیں کرنا چاہتا تھا۔", "ur-PK-AsadNeural"),
    ("Ayesha takes a small step back, then both characters look at each other in silence, "
     "emotional facial expressions, cinematic camera pull-back, natural movement.",
     "عائشہ: لیکن سچ جاننا میرا حق تھا۔", "ur-PK-UzmaNeural"),
]

def run(args):
    subprocess.run(args, check=True)

def download(url, path):
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    Path(path).write_bytes(r.content)

async def make_voice(text, voice, path):
    proc = await asyncio.create_subprocess_exec(
        "edge-tts", "--voice", voice, "--text", text, "--write-media", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(err.decode("utf-8", "replace"))

def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print("Generating original anime keyframe...")
        key = fal_client.subscribe(
            "fal-ai/flux/dev",
            arguments={"prompt": CHARACTERS, "image_size": "portrait_16_9",
                       "num_inference_steps": 28, "guidance_scale": 3.5},
            with_logs=True,
        )
        image_url = key["images"][0]["url"]
        clips, voices = [], []
        for i, (motion, dialogue, voice) in enumerate(SCENES):
            print(f"Generating animated scene {i+1}/3...")
            result = fal_client.subscribe(
                "fal-ai/kling-video/v2.1/standard/image-to-video",
                arguments={"prompt": CHARACTERS + " " + motion,
                           "image_url": image_url, "duration": "5",
                           "aspect_ratio": "9:16", "cfg_scale": 0.5},
                with_logs=True,
            )
            clip = tmp / f"scene_{i}.mp4"
            download(result["video"]["url"], clip)
            clips.append(clip)
            voice_path = tmp / f"voice_{i}.mp3"
            try:
                asyncio.run(make_voice(dialogue, voice, voice_path))
            except Exception as e:
                raise RuntimeError(f"Urdu voice generation failed for scene {i+1}: {e}")
            voices.append(voice_path)

        # Normalize all clips before concatenation.
        normalized = []
        for i, clip in enumerate(clips):
            p = tmp / f"norm_{i}.mp4"
            run([FFMPEG, "-y", "-i", str(clip), "-vf",
                 "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=24",
                 "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                 str(p)])
            normalized.append(p)
        concat_file = tmp / "concat.txt"
        concat_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in normalized))
        silent_video = tmp / "video.mp4"
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(silent_video)])

        # Put each Urdu voice line at the beginning of its corresponding 5-second scene.
        voice_inputs = []
        for i, voice in enumerate(voices):
            delayed = tmp / f"delayed_{i}.wav"
            run([FFMPEG, "-y", "-i", str(voice), "-af", f"adelay={i*5000}|{i*5000}",
                 "-ac", "2", "-ar", "44100", str(delayed)])
            voice_inputs.append(delayed)
        cmd = [FFMPEG, "-y", "-i", str(silent_video)]
        for p in voice_inputs:
            cmd += ["-i", str(p)]
        mix = f"amix=inputs={len(voice_inputs)}:duration=longest:dropout_transition=0,volume=1.6"
        cmd += ["-filter_complex", mix, "-map", "0:v:0", "-map", "0:a:0?"]
        # Rebuild mapping explicitly: voice inputs are 1..N.
        cmd = [FFMPEG, "-y", "-i", str(silent_video)]
        for p in voice_inputs:
            cmd += ["-i", str(p)]
        labels = "".join(f"[{i+1}:a]" for i in range(len(voice_inputs)))
        filtergraph = labels + f"amix=inputs={len(voice_inputs)}:duration=longest:dropout_transition=0,volume=1.4[aout]"
        cmd += ["-filter_complex", filtergraph, "-map", "0:v:0", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(OUT)]
        run(cmd)

    print(f"AI anime demo created: {OUT}")
    print("Includes: generated anime keyframe, 3 AI motion scenes, Urdu character dialogue voice.")
    print("Publishing integrations: disabled.")

if __name__ == "__main__":
    main()
