# Movie Reels — Facebook Buffer Publisher

This repository now runs Movie Reels Publisher instead of the former animal/cartoon automation.

## Daily schedule
GitHub Actions starts five times daily at 08:00, 11:00, 14:00, 17:00 and 20:00 Pakistan Standard Time (UTC+5). Each run processes at most one video and adds it to the same Facebook channel already connected through this repository's Buffer channel ID. Buffer publishes according to the posting slots configured in that channel, so configure 4–5 daily queue slots there as well. These are five attempts, not a guarantee of five posts.

## Video format
- Live-action feature-film candidates only; animation, anime, cartoons, gaming footage, TV episodes, events and meeting recordings are filtered out.
- Scene length: 85–89 seconds (configured for the current Facebook Reel workflow).
- Release year must be known; films from 1890 onward are eligible by default (configurable with `MIN_RELEASE_YEAR`). Older films are not rejected just for age.
- Native Full HD source (at least 1920×1080 landscape or 1080×1920 portrait) and at least 2 Mbps source bitrate are mandatory for every film, regardless of age. Low-resolution sources are rejected, not falsely labelled Full HD after upscaling.
- Vertical 1080×1920 (9:16). The complete movie frame is fitted over a blurred vertical background to avoid excessive zoom/cropping.
- Original movie audio/dialogue is retained.
- Fast-cut action-like scenes receive an original synthesized fight instrumental underneath. Other scenes retain original audio only. Scene detection is a cut-rate heuristic, not semantic AI.

## Existing connections
The existing GitHub Actions secrets and variables are preserved:
- Secrets: `BUFFER_API_KEY`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`
- Variables: `BUFFER_CHANNEL_ID`, optional `BUFFER_EXPECTED_CHANNEL_NAME`
- Set repository variable `ENABLE_AUTO_PUBLISH=true` to enable the five scheduled attempts.

The publisher searches Internet Archive and Wikimedia Commons; it does not assume that a file is reusable merely because it is hosted on Commons. Its explicit machine-readable license URL must pass the configured commercial-reuse allowlist. The publisher does not change the configured Buffer channel ID: it verifies and queues to that same connected Facebook destination. Each output uploads to Cloudinary and is added to that channel's Buffer queue. Queue acceptance is not proof that Facebook later published it.

## Source rights and availability
The finder searches Internet Archive records and Wikimedia Commons video files. It accepts only machine-readable Public Domain Mark 1.0, CC0 1.0 or CC BY 4.0 declarations, and Commons candidates must be live-action film-like video files with a recorded year and native Full HD dimensions. The stricter metadata filter may return fewer candidates, and metadata alone cannot prove that every video, soundtrack, performer and commercial-use right is cleared. Confirm rights before public posting. Do not use unofficial commercial movie or TV-drama copies without permission. Short duration, edits, credits or music overlays do not make copyrighted footage free to reuse.

Wikimedia Commons is primarily a free-media repository, not a dependable catalogue of complete feature films. The openly licensed Archive catalogue is not a dependable source of current blockbuster films or Pakistani television dramas. Some runs may find no eligible source and queue nothing; the system skips unsuitable material rather than selecting cartoons, gameplay or event recordings to fill the schedule.

## Run
Python 3.11+, FFmpeg and FFprobe. Install dependencies with `pip install -r requirements.txt`. In Actions, run **Movie Reels - Facebook Buffer Publisher** with `publish=true` for a one-time manual attempt.
