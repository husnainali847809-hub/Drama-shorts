"""Original AI animal video production entry point. Publishing is manual only."""
import argparse
import os
from pathlib import Path

from animal_ai.pipeline import generate_pilot


def main():
    parser = argparse.ArgumentParser(description="AI Animal Video Production System")
    parser.add_argument("--generate", action="store_true", help="Generate the pilot video (paid AI API usage).")
    parser.add_argument("--pilot", action="store_true", help="Generate the first Timo & Bunny pilot.")
    parser.add_argument("--publish-approved", type=Path, help="Explicitly queue a manually approved MP4 to Buffer.")
    parser.add_argument("--caption", default="Original AI animal story")
    args = parser.parse_args()

    if args.generate and args.pilot:
        generate_pilot()
        return
    if args.publish_approved:
        if not args.publish_approved.is_file():
            raise SystemExit("Approved MP4 path does not exist.")
        if os.getenv("PUBLISH_APPROVED") != "true":
            raise SystemExit("Safety stop: set PUBLISH_APPROVED=true only after you have watched and approved this video.")
        from main_publisher import publish_approved
        publish_approved(args.publish_approved, args.caption)
        return
    print("No action taken. Scheduled legacy invocations are disabled. Use --generate --pilot manually.")


if __name__ == "__main__":
    main()
