"""Publish only manually rights-reviewed internet cartoon videos.

AI-generated cartoon creation is intentionally disabled in this project. This module
selects a reviewed item from licensed_assets.json and uses the existing Buffer pipeline.
"""
import logging
import os
from datetime import datetime, timezone

import main as core

log = logging.getLogger("longform_cartoon")


def run():
    source_mode = os.getenv("CARTOON_SOURCE_MODE", "licensed").strip().lower()
    if source_mode != "licensed":
        raise RuntimeError(
            "Only licensed internet cartoon sources are enabled. "
            "AI-generated cartoon creation is disabled."
        )

    today = datetime.now(timezone.utc).date().isoformat()
    previous, sha = core.read_state()
    if previous == today:
        log.info("Already queued one licensed cartoon for %s; skipping duplicate.", today)
        return

    core.verify_channel()
    from licensed_source import build_licensed_video

    video, title, caption = build_licensed_video()
    log.info("Preparing complete rights-reviewed cartoon video: %s", title)
    public_url = core.upload_video(video)
    post = core.queue_reel(public_url, caption, post_type="post")
    core.write_state(today, sha)
    log.info(
        "COMPLETE: Buffer accepted Facebook video post %s. Facebook publication still needs confirmation.",
        post["id"],
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    run()
