import subprocess
from pathlib import Path
from config import MUSIC_DIR, CLIP_MIN_SECONDS, CLIP_MAX_SECONDS
from editor.audio_mixer import choose_fighting_music


def _run(command):
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)


def _has_audio(source: Path) -> bool:
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(source)
        ],
        check=True, capture_output=True, text=True, timeout=30
    )
    return bool(probe.stdout.strip())


def make_vertical_clip(source: Path, start: float, duration: float, output: Path, fighting_scene=False):
    if not CLIP_MIN_SECONDS <= float(duration) <= CLIP_MAX_SECONDS:
        raise ValueError("Facebook Reel duration must be between 60 and 90 seconds.")
    if not _has_audio(source):
        raise RuntimeError(
            "Source video has no original audio/dialogue track; skipped to protect the requested format."
        )

    # Preserve the complete movie frame instead of aggressively zooming/cropping it.
    # A softly blurred, darkened copy fills the vertical canvas behind the fitted video.
    video_filter = (
        "[0:v]split=2[background][foreground];"
        "[background]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=28:12,eq=brightness=-0.18[bg];"
        "[foreground]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
    )
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(start), "-i", str(source), "-t", str(duration),
            "-filter_complex", video_filter, "-map", "[v]"]

    if fighting_scene:
        music_path, music_meta = choose_fighting_music(MUSIC_DIR)
        command = base + [
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex",
            "[0:a:0]volume=1.0[original];"
            "[1:a:0]volume=0.36[music];"
            "[original][music]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
            "alimiter=limit=0.95[audio]",
            "-map", "[audio]",
        ]
    else:
        # No action score: preserve only the movie's own dialogue and soundtrack.
        music_meta = {
            "title": "Not added (non-fighting scene)",
            "creator": "Movie Reels Publisher",
            "source_url": "No background music used for non-fighting scenes",
            "license_url": "Not applicable",
        }
        command = base + ["-map", "0:a:0"]

    command += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(output),
    ]
    _run(command)
    return music_meta
