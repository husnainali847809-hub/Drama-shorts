"""Check whether a configured test source exposes a readable stream.

This test inspects the channel's latest RSS-listed upload even if it is older
than the production 30-day discovery window. It does not download video,
render clips, upload to Cloudinary, or publish to Buffer.
"""
import os
import sys
from pathlib import Path

# Widen the age window for this test only. The production workflow keeps its
# normal DRAMA_MAX_AGE_DAYS setting because this is a separate process.
os.environ["DRAMA_MAX_AGE_DAYS"] = "3650"

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
            # Empty seen-ID set means the channel's latest RSS-listed upload
            # can be inspected regardless of production processing history.
            episode = discover_episode(source, set())
            if not episode:
                print(
                    "[StreamTest] No video was listed in the channel's RSS feed.",
                    flush=True,
                )
                continue

            print(f"[StreamTest] Latest RSS video: {episode.get('title')}", flush=True)
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
        "[StreamTest] No configured source exposed a readable combined stream. "
        "No download or publishing was attempted.",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
