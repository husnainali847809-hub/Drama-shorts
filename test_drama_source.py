"""Check whether a configured test source exposes a readable stream.

This performs metadata/format inspection only: it does not download video,
render clips, upload to Cloudinary, or publish to Buffer.
"""
import sys
from pathlib import Path

from main import discover_episode, get_stream_source

ROOT = Path(__file__).resolve().parent
TEST_SOURCES = ROOT / "resources" / "drama_test_sources.txt"


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
            episode = discover_episode(source, set())
            if not episode:
                print("[StreamTest] No recent video found on this channel.", flush=True)
                continue

            print(f"[StreamTest] Latest video: {episode.get('title')}", flush=True)
            print(f"[StreamTest] Video URL: {episode.get('url')}", flush=True)
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
        "[StreamTest] No configured test source exposed a readable combined stream. "
        "No download or publishing was attempted.",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
