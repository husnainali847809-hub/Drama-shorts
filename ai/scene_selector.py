import subprocess
from pathlib import Path

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector


def _probe_duration(video_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
        ],
        capture_output=True, text=True, timeout=30, check=True
    )
    return float(result.stdout.strip())


def _make_detection_proxy(video_path, proxy_path):
    # A tiny 0.5-fps proxy makes scene detection much faster than decoding
    # the full-resolution source frame-by-frame. Timestamps remain in seconds.
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path), "-vf", "fps=1/2,scale=320:-2",
            "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "35", str(proxy_path)
        ],
        capture_output=True, text=True, timeout=300, check=True
    )


def find_candidate_scenes(video_path, min_seconds=60, max_seconds=90):
    """Choose a 60–90 second window using a low-resolution scene proxy."""
    if min_seconds < 60 or max_seconds > 90 or min_seconds > max_seconds:
        raise ValueError("Facebook Reel length must be between 60 and 90 seconds.")

    video_path = Path(video_path)
    total = _probe_duration(video_path)
    if total < min_seconds:
        return []

    proxy_path = video_path.with_name(video_path.stem + "_scene_proxy.mp4")
    try:
        _make_detection_proxy(video_path, proxy_path)
        video = open_video(str(proxy_path))
        manager = SceneManager()
        manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=3))
        manager.detect_scenes(video, show_progress=False)
        scenes = manager.get_scene_list()
        boundaries = [start.get_seconds() for start, _end in scenes]
    finally:
        proxy_path.unlink(missing_ok=True)

    starts = {0.0, max(0.0, (total - min_seconds) / 2)}
    for value in boundaries:
        if 0 <= value <= total - min_seconds:
            starts.add(value)

    durations = sorted({min_seconds, max_seconds, (min_seconds + max_seconds) // 2})
    candidates = []
    for start in starts:
        for duration in durations:
            if duration > total or start + duration > total:
                continue
            cut_count = sum(1 for cut in boundaries if start < cut < start + duration)
            length_score = 1.0 - abs(duration - 75.0) / 30.0
            score = (cut_count * 0.15) + length_score
            candidates.append({
                "start": round(start, 2),
                "duration": float(duration),
                "score": score,
                "detected_cuts": cut_count,
                # A conservative editing-pace heuristic, not true visual AI.
                # Only fast-cut sequences receive the action soundtrack.
                "is_fighting": cut_count >= 12,
            })

    if not candidates:
        return []
    return sorted(candidates, key=lambda item: item["score"], reverse=True)
