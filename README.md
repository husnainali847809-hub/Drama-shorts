# TikTok Creator Clips → AI Editing → Buffer Queue

This repository checks **only the six authorized TikTok creator profiles** listed in `resources/drama_sources.txt`. On each scheduled run it looks for a new public video, selects a scene with AI, renders a vertical clip, uploads it to Cloudinary, and queues a Facebook Reel in Buffer.

## TikTok sources

The source list contains only these profiles:

- https://www.tiktok.com/@drama.edits272
- https://www.tiktok.com/@korai_editors
- https://www.tiktok.com/@md.editx6
- https://www.tiktok.com/@mwrites151
- https://www.tiktok.com/@kazmieditx00
- https://www.tiktok.com/@rm_edit17

The workflow uses yt-dlp's normal public TikTok extractor. It does not use browser cookies, login credentials, private endpoints, DRM removal, or access-control workarounds. TikTok may change or restrict public profile extraction; if a profile cannot be accessed normally, that profile is skipped and the next configured profile is checked.

**Only use videos for which the creator has explicitly authorized downloading, editing, and reposting.** A public profile or public video is not itself permission. Keep `resources/rights.json` accurate and do not enable reuse for any source without permission.

## Daily schedule

Four scheduled runs are retained at Pakistan time:

- 09:00 PKT
- 13:00 PKT
- 17:00 PKT
- 21:00 PKT

Each successful run queues one Facebook Reel in Buffer. A scheduled run may queue fewer than four clips if none of the six profiles has an eligible, publicly accessible, unseen video.

## Editing and publishing pipeline

1. Checks the six TikTok profiles in the configured order.
2. Selects the latest unseen video returned by the public extractor.
3. Analyses candidate scene windows and asks the configured OpenRouter vision model to select a coherent moment.
4. Applies the existing professional vertical editing engine and mood-aware music selection.
5. Keeps the final Facebook Reel at or below 90 seconds.
6. Uploads the rendered video to Cloudinary.
7. Queues the Facebook Reel in Buffer.
8. Saves the source video ID and selected clip start to the processed-history cache to avoid duplicate clips.

The pipeline does not publish directly to Facebook; Buffer receives the queued post.

## GitHub Actions configuration

In **Settings → Secrets and variables → Actions**, configure these Secrets:

- `OPENROUTER_API_KEY`
- `BUFFER_API_KEY`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

Configure these Variables:

- `BUFFER_CHANNEL_ID` (or keep the existing secret named `BUFFER_CHANNEL_ID` if that is how the repository is currently configured)
- `BUFFER_EXPECTED_CHANNEL_NAME` (optional)
- `OPENROUTER_MODEL` (optional; the vision classifier currently pins its supported model)
- `SCENE_PREFERENCE` (optional)

The Google Drive OAuth credentials and `DRIVE_FOLDER_ID` are no longer used by the scheduled publishing workflow. YouTube/Facebook source lists and the local YouTube discovery script are not used by this TikTok-only pipeline.

## Important limitations

- TikTok public profile extraction depends on TikTok and yt-dlp compatibility and is not guaranteed for every profile or run.
- No sign-in, cookies, private account access, or platform restriction bypass is attempted.
- If a creator deletes a video, changes privacy, or TikTok blocks public extraction, that source may be skipped.
- GitHub Actions, Cloudinary, OpenRouter, and Buffer quotas and service limits still apply.
