# Movie Reels — Facebook Buffer Publisher

This repository now runs Movie Reels Publisher instead of the former animal/cartoon automation.

## Daily schedule
GitHub Actions starts five times daily at 08:00, 11:00, 14:00, 17:00 and 20:00 Pakistan Standard Time (UTC+5). Each run processes at most one video and adds it to the connected Facebook channel's Buffer queue. Buffer publishes according to the posting slots configured in the Buffer channel, so configure 4–5 daily queue slots there as well. These are five attempts, not a guarantee of five posts: there may not be five eligible, unused, licensed film sources each day.

## Video format
- Live-action film sources only; obvious animation/cartoon/anime and common non-film records are filtered.
- Continuous scene length: 60–90 seconds, within Buffer's documented Facebook Reels duration limit.
- Release year 2008 or newer; unknown/older years are rejected.
- Native Full HD source and at least 2 Mbps bitrate required.
- Vertical 1080×1920 (9:16). The complete movie frame is fitted over a blurred vertical background to avoid excessive zoom/cropping.
- Original movie audio/dialogue is retained.
- Fast-cut action-like scenes receive an original synthesized fight instrumental underneath. Other scenes retain original audio only. Scene detection is a cut-rate heuristic, not semantic AI.

## Existing connections
The existing GitHub Actions connection names are preserved:
- Secrets: `BUFFER_API_KEY`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`
- Variables: `BUFFER_CHANNEL_ID`, optional `BUFFER_EXPECTED_CHANNEL_NAME`
- Set repository variable `ENABLE_AUTO_PUBLISH=true` to enable the five scheduled attempts.

Each output uploads to Cloudinary and is added to the Facebook channel's Buffer queue as a Reel. The workflow checks that the Buffer destination is a connected Facebook channel before processing. Buffer queue acceptance is not proof that Facebook later published it.

## Source rights and availability
The finder searches Internet Archive records declaring Public Domain Mark 1.0, CC0 1.0 or CC BY 4.0. Metadata filters do not independently prove that every video is a live-action film or that all elements are cleared for commercial reuse. Confirm the exact film, music, performers and rights before public posting. Do not use unofficial commercial movie or TV-drama copies without permission. Short duration, edits, credits or music overlays do not make copyrighted footage free to reuse.

The openly licensed Archive catalogue is not a dependable source of current blockbuster films or Pakistani television dramas. The system does not download or publish ordinary copyrighted drama episodes. Some runs may find no eligible source and queue nothing. The system will retry at the next slot rather than fill the queue with unlicensed or unsuitable content.

## Run
Python 3.11+, FFmpeg and FFprobe. Install dependencies with `pip install -r requirements.txt`. In Actions, run **Movie Reels - Facebook Buffer Publisher** with `publish=true` for a one-time manual attempt.
