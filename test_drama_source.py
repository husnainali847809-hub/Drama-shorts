"""Diagnose whether a configured test source exposes a readable stream.

This test reads the channel's latest RSS-listed upload and prints yt-dlp's
extractor diagnostics. It never downloads video, renders clips, uploads, or
publishes. It does not use cookies or attempt to bypass YouTube restrictions.
"""
import os
import sys
from pathlib import Path

# Widen the age window for this test only. Production keeps its normal setting.
os.environ["DRAMA_MAX_AGE_DAYS"] = "3650"

from yt_dlp import YoutubeDL
from main import discover_episode, get_stream_source

ROOT = Path(__file__).resolve().parent
TEST_SOURCES = ROOT / "resources" / "drama_test_sources.txt"


def diagnose_video(video_url):
    """Print useful extractor metadata without exposing signed media URLs."""
    print("[StreamTest] Starting verbose yt-dlp extraction diagnostics.", flush=True)
    options = {
        "verbose": True,
        "quiet": False,
        "no_warnings": False,
        "noplaylist": True,
        "skip_download": True,
        "ignore_no_formats_error": True,
        "socket_timeout": 30,
        "extractor_retries": 2,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(video_url, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp returned no video metadata.")

    formats = info.get("formats") or []
    video_only = [
        item for item in formats
        if item.get("url")
        and item.get("vcodec") not in (None, "none")
        and item.get("acodec") in (None, "none")
    ]
    audio_only = [
        item for item in formats
        if item.get("url")
        and item.get("acodec") not in (None, "none")
        and item.get("vcodec") in (None, "none")
    ]
    combined = [
        item for item in formats
        if item.get("url")
        and item.get("vcodec") not in (None, "none")
        and item.get("acodec") not in (None, "none")
    ]

    print("[StreamTest] Extractor metadata:", flush=True)
    for key in (
        "extractor_key", "availability", "live_status",
        "playability_status", "age_limit", "duration",
    ):
        if info.get(key) is not None:
            print(f"[StreamTest]   {key}: {info[key]}", flush=True)
    print(
        "[StreamTest] Format counts: "
        f"total={len(formats)}, video_only={len(video_only)}, "
        f"audio_only={len(audio_only)}, combined={len(combined)}",
        flush=True,
    )
    if not formats:
        print(
            "[StreamTest] No formats were exposed. Review the verbose extractor "
            "messages above for sign-in, bot-check, player, or PO Token warnings.",
            flush=True,
        )
    return info


def main():
    if not TEST_SOURCES.exists():
        raise SystemExit("Missing resources/drama_test_sources.txt")

    sources = [
        line.strip()
        for line in TEST_SOURCES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not sources:
        raise SystemExit("No test sources configured.")

    for index, source in enumerate(sources, start=1):
        print(f"[StreamTest] Checking source {index}: {source}", flush=True)
        try:
            # Empty seen-ID set lets the latest RSS-listed upload be inspected.
            episode = discover_episode(source, set())
            if not episode:
                print("[StreamTest] No video was listed in the channel's RSS feed.", flush=True)
                continue

            print(f"[StreamTest] Latest RSS video: {episode.get('title')}", flush=True)
            print(f"[StreamTest] Video URL: {episode.get('url')}", flush=True)
            diagnose_video(episode["url"])

            # Keep the production stream-selection path under test as well.
            stream = get_stream_source(episode["url"])
            print(
                "[StreamTest] PASS: readable combined A/V stream metadata found. "
                f"Duration={stream['duration']:.1f}s. "
                "No video file was downloaded.",
                flush=True,
            )
            return 0
        except Exception as exc:
            print(f"[StreamTest] FAIL: {type(exc).__name__}: {exc}", flush=True)

    print(
        "[StreamTest] No configured source exposed a readable combined stream. "
        "No download or publishing was attempted.",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
