"""Three-style professional short-video editor for user-owned or licensed footage."""
import math
import subprocess
import tempfile
import wave
import json
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ColorClip,
    concatenate_videoclips,
    concatenate_audioclips,
    vfx,
)

PROJECT_ROOT = Path(__file__).resolve().parent
MUSIC_ROOTS = [PROJECT_ROOT / "dramas", PROJECT_ROOT / "music", PROJECT_ROOT / "songs", PROJECT_ROOT / "assets" / "music", PROJECT_ROOT / "assets" / "songs"]
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac"}


def log(message):
    print(f"[EditingEngine] {message}", flush=True)


def choose_style(category):
    """Map the AI scene mood to one of the three editing treatments."""
    category = str(category or "interesting").lower()
    if category in {"comedy", "romantic"}:
        return "dialogue_to_song"
    if category in {"action", "suspense", "emotional"}:
        return "cinematic"
    return "clean_story"


def detect_scene_cuts(video_path, start, duration, max_cuts=14):
    """Detect visible shot changes in the selected window using sampled histograms."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log("Scene detector could not open the video; using a clean single segment.")
        return [0.0, float(duration)]
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    if total_frames <= 0:
        cap.release()
        return [0.0, float(duration)]

    sample_step = max(1, int(round(fps * 0.5)))
    first = max(0, int(start * fps))
    last = min(int((start + duration) * fps), int(total_frames) - 1)
    previous = None
    cuts = [0.0]
    frame_no = first
    while frame_no <= last:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok:
            frame_no += sample_step
            continue
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        current_time = max(0.0, frame_no / fps - start)
        if previous is not None and current_time - cuts[-1] >= 1.6:
            similarity = cv2.compareHist(previous, hist, cv2.HISTCMP_CORREL)
            if similarity < 0.42 and current_time < duration - 0.8:
                cuts.append(round(current_time, 2))
        previous = hist
        frame_no += sample_step
    cap.release()
    cuts.append(float(duration))
    cuts = sorted(set(max(0.0, min(float(duration), x)) for x in cuts))
    if len(cuts) > max_cuts + 1:
        # Keep cuts spread across the clip rather than clustering in one moment.
        inner = cuts[1:-1]
        picks = [inner[round(i * (len(inner) - 1) / max(1, max_cuts - 1))] for i in range(min(max_cuts, len(inner)))]
        cuts = [0.0] + picks + [float(duration)]
    return cuts


def _music_profile(track):
    """Measure rough energy and spectral brightness from the audio itself."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", str(track), "-t", "25", "-vn",
        "-ac", "1", "-ar", "22050", "-f", "f32le", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, timeout=75)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("FFmpeg could not decode this music file.")
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    if samples.size < 22050:
        raise RuntimeError("Music file is too short to analyse.")
    samples = np.nan_to_num(samples)
    frame_size, hop = 2048, 1024
    rms_values, centroids = [], []
    window = np.hanning(frame_size).astype(np.float32)
    frequencies = np.fft.rfftfreq(frame_size, d=1 / 22050)
    for offset in range(0, len(samples) - frame_size, hop):
        frame = samples[offset:offset + frame_size]
        rms_values.append(float(np.sqrt(np.mean(frame * frame))))
        spectrum = np.abs(np.fft.rfft(frame * window))
        total = float(np.sum(spectrum))
        if total > 1e-8:
            centroids.append(float(np.sum(frequencies * spectrum) / total))
    if not rms_values or not centroids:
        raise RuntimeError("Could not calculate audio features.")
    energy = min(1.0, float(np.percentile(rms_values, 75)) * 4.0)
    brightness = min(1.0, float(np.median(centroids)) / 11025.0)
    return {"energy": energy, "brightness": brightness}


_MOOD_TARGETS = {
    "comedy": (0.72, 0.58),
    "romantic": (0.32, 0.42),
    "emotional": (0.22, 0.28),
    "suspense": (0.38, 0.24),
    "action": (0.82, 0.72),
    "interesting": (0.55, 0.52),
}
_MOOD_WORDS = {
    "comedy": ("comedy", "funny", "comic", "playful", "happy", "fun"),
    "romantic": ("romantic", "love", "soft", "sweet", "warm", "romance"),
    "emotional": ("emotional", "sad", "piano", "heart", "slow", "emotive"),
    "suspense": ("suspense", "tension", "thriller", "mystery", "dark"),
    "action": ("action", "epic", "power", "battle", "intense", "energetic"),
    "interesting": ("interesting", "upbeat", "curious", "light", "neutral"),
}


def _declared_track_mood(track):
    """Read mood hints from both filename and any nested folder names."""
    labels = set()
    searchable = str(track.relative_to(PROJECT_ROOT)).lower().replace("-", "_").replace(" ", "_")
    for mood, words in _MOOD_WORDS.items():
        if any(word in searchable for word in words):
            labels.add(mood)
    return labels


def find_music(category):
    """Rank plausible tracks using mood labels plus measured audio features.

    Audio analysis estimates energy and brightness; it does not understand lyrics
    or story meaning, so clear mood labels remain important.
    """
    category = str(category or "interesting").lower()
    if category not in _MOOD_TARGETS:
        return None

    # Only use user-provided tracks when a neighbouring .license.json
    # explicitly confirms permission to reuse the audio.
    tracks = []
    for root in MUSIC_ROOTS:
        if not root.exists():
            continue
        for track in root.rglob("*"):
            if not track.is_file() or track.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            licence_file = track.with_suffix(".license.json")
            try:
                licence = json.loads(licence_file.read_text(encoding="utf-8"))
                if licence.get("reuse_permission_confirmed") is True:
                    tracks.append(track)
            except (OSError, ValueError, AttributeError):
                continue
    tracks = sorted(tracks)
    if not tracks:
        searched = ", ".join(str(root.relative_to(PROJECT_ROOT)) for root in MUSIC_ROOTS)
        log(f"No MP3/audio tracks found. Checked folders: {searched}.")
        return None
    log(f"Music matcher found {len(tracks)} audio file(s); evaluating mood labels and audio features for '{category}'.")

    target_energy, target_brightness = _MOOD_TARGETS[category]
    ranked = []
    for track in tracks:
        declared = _declared_track_mood(track)
        if declared and category not in declared:
            continue
        try:
            profile = _music_profile(track)
        except Exception as exc:
            log(f"Skipped unreadable music '{track.name}': {exc}")
            continue
        distance = (
            abs(profile["energy"] - target_energy) * 0.65
            + abs(profile["brightness"] - target_brightness) * 0.35
        )
        if category in declared:
            distance = max(0.0, distance - 0.18)
        ranked.append((distance, track, profile, bool(declared)))

    if not ranked:
        log(f"No analysable track matches '{category}'; keeping original audio.")
        return None

    ranked.sort(key=lambda item: (item[0], item[1].name.lower()))
    distance, chosen, profile, labelled = ranked[0]
    confidence_limit = 0.24 if not labelled else 0.40
    if distance > confidence_limit:
        log(
            f"No confident '{category}' match (best acoustic score {distance:.2f}, "
            f"limit={confidence_limit:.2f}); keeping original audio instead of choosing randomly."
        )
        return None

    log(
        f"Selected '{chosen.name}' for '{category}' scene "
        f"(match={distance:.2f}, energy={profile['energy']:.2f}, "
        f"brightness={profile['brightness']:.2f}, mood_label={labelled})."
    )
    return chosen

def fit_vertical(clip):
    """Fit the entire source inside a 9:16 canvas without cutting off the scene."""
    scale = min(1080.0 / float(clip.w), 1920.0 / float(clip.h))
    target_width = max(1, int(round(float(clip.w) * scale)))
    target_height = max(1, int(round(float(clip.h) * scale)))
    foreground = clip.resized(new_size=(target_width, target_height))
    background = ColorClip(
        size=(1080, 1920),
        color=(10, 10, 10),
        duration=float(clip.duration),
    )
    # Letterbox/pillarbox with a dark neutral canvas instead of zoom-cropping.
    return CompositeVideoClip(
        [background, foreground.with_position(("center", "center"))],
        size=(1080, 1920),
    ).with_duration(float(clip.duration))


def generate_original_music(category, duration, destination):
    """Create a simple, original instrumental bed when no licensed track is available."""
    sample_rate = 22050
    total_samples = max(sample_rate, int(float(duration) * sample_rate))
    presets = {
        "romantic": [
            (220.00, 261.63, 329.63), (196.00, 246.94, 293.66),
            (174.61, 220.00, 261.63), (196.00, 246.94, 293.66),
        ],
        "emotional": [
            (174.61, 220.00, 261.63), (146.83, 196.00, 233.08),
            (164.81, 196.00, 246.94), (146.83, 174.61, 220.00),
        ],
        "comedy": [
            (261.63, 329.63, 392.00), (293.66, 369.99, 440.00),
            (329.63, 392.00, 493.88), (293.66, 369.99, 440.00),
        ],
        "suspense": [
            (110.00, 130.81, 164.81), (98.00, 123.47, 146.83),
            (103.83, 130.81, 155.56), (98.00, 116.54, 146.83),
        ],
        "action": [
            (130.81, 164.81, 196.00), (146.83, 185.00, 220.00),
            (164.81, 207.65, 246.94), (146.83, 185.00, 220.00),
        ],
        "interesting": [
            (220.00, 277.18, 329.63), (196.00, 246.94, 293.66),
            (246.94, 311.13, 369.99), (196.00, 246.94, 293.66),
        ],
    }
    chords = presets.get(str(category or "interesting").lower(), presets["interesting"])
    times = np.arange(total_samples, dtype=np.float32) / float(sample_rate)
    signal = np.zeros(total_samples, dtype=np.float32)
    chord_indices = (times // 4.0).astype(np.int32) % len(chords)
    for chord_index, notes in enumerate(chords):
        mask = chord_indices == chord_index
        local_times = times[mask]
        if local_times.size == 0:
            continue
        chord_signal = np.zeros(local_times.size, dtype=np.float32)
        for note in notes:
            chord_signal += (
                np.sin(2.0 * np.pi * note * local_times)
                + 0.16 * np.sin(2.0 * np.pi * note * 2.0 * local_times)
            ) / 3.0
        signal[mask] = chord_signal
    # Gentle pulsing and clean fades keep the bed underneath spoken dialogue.
    signal *= (0.78 + 0.22 * np.sin(2.0 * np.pi * 0.16 * times))
    fade_samples = min(sample_rate, total_samples // 2)
    if fade_samples:
        signal[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        signal[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak > 0:
        signal *= 0.22 / peak
    pcm = np.clip(signal * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
    return Path(destination)


def find_first_dialogue_pause(audio, duration, fallback=3.5):
    """Estimate the first short dialogue break; use a safe fallback if unclear."""
    if audio is None:
        return fallback
    try:
        samples = audio.to_soundarray(fps=8000)
        if samples.ndim == 2:
            samples = np.mean(samples, axis=1)
        window = 2000  # 0.25 seconds at 8 kHz
        levels = []
        for offset in range(0, len(samples) - window, window):
            chunk = samples[offset:offset + window]
            levels.append(float(np.sqrt(np.mean(np.square(chunk)))))
        # Require two consecutive quiet windows after the opening line.
        for index in range(max(6, int(1.5 * 8000 / window)), len(levels) - 1):
            if levels[index] < 0.012 and levels[index + 1] < 0.012:
                pause_at = index * 0.25 + 0.15
                if 1.5 <= pause_at < min(float(duration) - 1.0, 12.0):
                    return round(pause_at, 2)
    except Exception as exc:
        log(f"Dialogue pause detection unavailable; using {fallback:.1f}s fallback ({exc}).")
    return fallback


def make_music_layer(path, duration, start_at, volume):
    track = AudioFileClip(str(path))
    needed = max(0.1, duration - start_at)
    if track.duration < needed:
        repeats = int(math.ceil(needed / max(track.duration, 0.1)))
        looped = concatenate_audioclips([track] * repeats)
        track = looped
    track = track.subclipped(0, needed).with_start(start_at).with_volume_scaled(volume)
    return track


def render_professional_clip(source_path, start, category, output_path, clip_seconds=85):
    source = VideoFileClip(str(source_path))
    selected = None
    vertical = None
    music = None
    mixed_audio = None
    rendered = None
    generated_music_dir = None
    music_meta = {"title": "Original mood-matched instrumental", "style": choose_style(category)}
    try:
        end = min(float(start) + float(clip_seconds), source.duration)
        selected = source.subclipped(float(start), end)
        if selected.duration < min(float(clip_seconds) - 1, 10):
            raise RuntimeError("Selected source segment is too short to edit.")
        style = choose_style(category)
        cuts = detect_scene_cuts(source_path, float(start), selected.duration)
        log(f"Auto scene detection found {max(0, len(cuts) - 2)} cut(s); style={style}.")

        pieces = []
        for left, right in zip(cuts[:-1], cuts[1:]):
            if right - left < 0.12:
                continue
            part = selected.subclipped(left, right)
            pieces.append(part)

        if not pieces:
            pieces = [selected]
        assembled = concatenate_videoclips(pieces, method="compose")
        vertical = fit_vertical(assembled)

        if style == "cinematic":
            # A subtle opening/closing fade avoids abrupt starts without hiding dialogue.
            vertical = vertical.with_effects([vfx.FadeIn(0.25), vfx.FadeOut(0.35)])

        music_path = find_music(category)
        if music_path is None:
            generated_music_dir = tempfile.TemporaryDirectory(prefix="drama-original-music-")
            music_path = generate_original_music(
                category,
                vertical.duration,
                Path(generated_music_dir.name) / f"{category}_original_instrumental.wav",
            )
            log(f"No verified licensed track for '{category}'; generated an original mood-matched instrumental.")
            music_meta = {
                "title": f"Original {category} instrumental",
                "style": style,
                "generated": True,
            }

        audio_layers = []
        if vertical.audio is not None:
            audio_layers.append(vertical.audio.with_volume_scaled(1.0))

        # Keep opening dialogue audible for dialogue-led scenes; use a quiet
        # instrumental bed for every category rather than leaving music absent.
        music_start = find_first_dialogue_pause(vertical.audio, vertical.duration) if style == "dialogue_to_song" else 0.0
        music_volume = 0.18 if style == "dialogue_to_song" else 0.12
        music = make_music_layer(music_path, vertical.duration, music_start, music_volume)
        audio_layers.append(music)
        if not music_meta.get("generated"):
            music_meta = {
                "title": music_path.stem,
                "style": style,
                "music_start_seconds": music_start,
            }

        rendered = vertical
        if audio_layers:
            mixed_audio = CompositeAudioClip(audio_layers)
            rendered = vertical.with_audio(mixed_audio)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        rendered.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            fps=30,
            preset="medium",
            bitrate="4500k",
            audio_bitrate="192k",
            threads=2,
            logger=None,
        )
        log(f"Rendered 1080x1920 video using '{style}' editing.")
        return music_meta
    finally:
        if rendered is not None and rendered is not vertical:
            rendered.close()
        if mixed_audio is not None:
            mixed_audio.close()
        if music is not None:
            music.close()
        if generated_music_dir is not None:
            generated_music_dir.cleanup()
        if vertical is not None:
            vertical.close()
        if selected is not None:
            selected.close()
        source.close()