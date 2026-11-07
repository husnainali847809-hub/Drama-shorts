"""Manual-only Buffer publisher for a video the user has reviewed and approved."""
from datetime import datetime, timezone
from pathlib import Path
import cloudinary
import cloudinary.uploader
import os

from publisher.buffer import queue_facebook_reel, verify_channel


def need(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing GitHub secret: {name}")
    return value


def publish_approved(path: Path, caption: str):
    channel = verify_channel()
    cloudinary.config(
        cloud_name=need("CLOUDINARY_CLOUD_NAME"),
        api_key=need("CLOUDINARY_API_KEY"),
        api_secret=need("CLOUDINARY_API_SECRET"),
        secure=True,
    )
    result = cloudinary.uploader.upload(
        str(path), resource_type="video", folder="ai-animal-approved",
        public_id=f"animal-reel-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}",
        overwrite=False, unique_filename=False,
    )
    url = result.get("secure_url", "")
    if not url.startswith("https://res.cloudinary.com/"):
        raise RuntimeError("Cloudinary did not return a valid video URL.")
    post = queue_facebook_reel(url, caption)
    print(f"Buffer accepted manually approved video for {channel.get('displayName')}: {post.get('id')}")
    return post
