#!/usr/bin/env python3
"""Magic Hour realistic drama pilot + Urdu TTS.
Standalone demo only. Does not read copyrighted drama footage or publish anywhere.
A manual workflow run sends billable generation requests to Magic Hour.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from magic_hour import Client

OUT = Path("demo_output/ai_realistic_drama_demo.mp4")
OUT.parent.mkdir(parents=True, exist_ok=True)

API_KEY = os.environ.get("MAGIC_HOUR_API_KEY")
if not API_KEY:
    raise SystemExit(
        "Missing MAGIC_HOUR_API_KEY GitHub Actions secret. "
        "Add the Magic Hour key in repository Actions secrets."
    )

FFMPEG = "ffmpeg"
MODEL = os.environ.get("MAGIC_HOUR_VIDEO_MODEL", "ltx-2.5")
RESOLUTION = os.environ.get("MAGIC_HOUR_RESOLUTION", "480p")
DURATION_SECONDS = 5.0

CHARACTERS = (
    "Photorealistic live-action Pakistani drama, two fictional adult Pakistani actors. "
    "Ayesha is a 24-year-old woman wearing an elegant teal shalwar kameez, with long "
    "dark hair. Hamza is a 26-year-old man wearing a navy kurta, with short dark hair. "
    "Natural human facial features, realistic skin texture, believable expressions, "
    "cinematic practical lighting, grounded acting, shallow depth of field, "
    "professional television drama cinematography. Vertical 9:16 framing. "
    "Keep both characters' clothing and appearance consistent. No subtitles, no text, "
    "no logos, no watermark."
)

SCENES = [
    (
        CHARACTERS
        + " Medium two-shot in a modern Pakistani living room at night. Ayesha turns "
        "toward Hamza with a worried, serious expression and asks him a difficult "
        "question. She makes a small natural hand gesture. Subtle slow camera push-in.",
        "عائشہ: تم نے مجھ سے سچ کیوں چھپایا؟",
        "ur-PK-UzmaNeural",
    ),
    (
        CHARACTERS
        + " Same living room, same two characters and same clothing. Medium close-up "
        "of Hamza. He looks down briefly, then looks toward Ayesha with a regretful "
        "expression and replies calmly. Natural eye movement and restrained acting. "
        "Slow cinematic camera movement.",
        "حمزہ: میں تمہیں پریشان نہیں کرنا چاہتا تھا۔",
        "ur-PK-AsadNeural",
    ),
    (
        CHARACTERS
        + " Same living room, same two characters and same clothing. Ayesha takes one "
        "small step back, visibly disappointed but composed. Hamza remains still. "
        "They look at each other in a tense quiet moment. Camera slowly pulls back.",
        "عائشہ: لیکن سچ جاننا میرا حق تھا۔",
        "ur-PK-UzmaNeural",
    ),
]


def run(args):
    subprocess.run(args, check=True)


async def make_voice(text, voice, path):
    proc = await asyncio.create_subprocess_exec(
        "edge-tts",
        "--voice", voice,
        "--text", text,
        "--write-media", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(err.decode("utf-8", "replace"))


def get_downloaded_video(response):
    paths = getattr(response, "downloaded_paths", None)
    if paths:
        candidate = Path(str(paths[0]))
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "Magic Hour returned successfully but the SDK did not provide a local "
        "downloaded video path. Check the project in Magic Hour and inspect SDK output."
    )


def main():
    client = Client(token=API_KEY)

    with tempfile.TemporaryDirectory() as temp_dir:
        tmp = Path(temp_dir)
        clips = []
        voices = []

        for index, (prompt, dialogue, voice) in enumerate(SCENES):
            print(f"Submitting Magic Hour realistic scene {index + 1}/3...")
            response = client.v1.text_to_video.generate(
                end_seconds=DURATION_SECONDS,
                style={"prompt": prompt},
                aspect_ratio="9:16",
                audio=False,
                model=MODEL,
                name=f"Drama-shorts realistic scene {index + 1}",
                resolution=RESOLUTION,
                wait_for_completion=True,
                download_outputs=True,
                download_directory=str(tmp),
            )

            source_video = get_downloaded_video(response)
            clip = tmp / f"scene_{index}.mp4"
            shutil.copy2(source_video, clip)
            clips.append(clip)
            print(f"Scene {index + 1} completed. Project ID: {getattr(response, 'id', 'not returned')}")

            voice_path = tmp / f"voice_{index}.mp3"
            asyncio.run(make_voice(dialogue, voice, voice_path))
            voices.append(voice_path)

        normalized = []
        for index, clip in enumerate(clips):
            normalized_clip = tmp / f"normalized_{index}.mp4"
            run([
                FFMPEG, "-y", "-i", str(clip),
                "-vf",
                "scale=720:1280:force_original_aspect_ratio=increase,"
                "crop=720:1280,fps=24,setsar=1",
                "-an", "-c:v", "libx264", "-preset", "veryfast",
                "-pix_fmt", "yuv420p", str(normalized_clip),
            ])
            normalized.append(normalized_clip)

        concat_file = tmp / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{clip.as_posix()}'\n" for clip in normalized),
            encoding="utf-8",
        )
        silent_video = tmp / "silent_video.mp4"
        run([
            FFMPEG, "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file), "-c", "copy", str(silent_video),
        ])

        voice_inputs = []
        for index, voice_path in enumerate(voices):
            delayed = tmp / f"delayed_{index}.wav"
            delay_ms = index * int(DURATION_SECONDS * 1000)
            run([
                FFMPEG, "-y", "-i", str(voice_path),
                "-af", f"adelay={delay_ms}|{delay_ms}",
                "-ac", "2", "-ar", "44100", str(delayed),
            ])
            voice_inputs.append(delayed)

        command = [FFMPEG, "-y", "-i", str(silent_video)]
        for voice_path in voice_inputs:
            command.extend(["-i", str(voice_path)])

        voice_labels = "".join(
            f"[{index + 1}:a]" for index in range(len(voice_inputs))
        )
        filter_graph = (
            voice_labels
            + f"amix=inputs={len(voice_inputs)}:duration=longest:"
              "dropout_transition=0,volume=1.25[aout]"
        )
        command.extend([
            "-filter_complex", filter_graph,
            "-map", "0:v:0", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", str(len(SCENES) * DURATION_SECONDS),
            str(OUT),
        ])
        run(command)

    print(f"Magic Hour realistic drama demo created: {OUT}")
    print("Includes: 3 AI-generated live-action scenes and Urdu dialogue voices.")
    print("Publishing integrations: disabled.")


if __name__ == "__main__":
    main()
