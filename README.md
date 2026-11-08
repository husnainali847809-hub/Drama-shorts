# Pakistani Drama Clips Automation

This repository is prepared to create **one vertical Pakistani drama clip per scheduled run** and add it to the configured Facebook Reel queue in Buffer. The schedule runs five times daily (Pakistan time: 09:00, 12:00, 15:00, 18:00, 21:00), for a target of five queued clips per day when all inputs and services are available.

## 1. Add authorized drama sources

Open `resources/drama_sources.txt` and paste one YouTube channel URL or Facebook Page URL per line. The file is intentionally blank until you have permission from each rights holder.

The system checks configured sources for recent uploads. YouTube channel feeds are supported through yt-dlp's normal public access. Facebook links may work only when the page/video is publicly accessible through yt-dlp. The system does not use cookies, bypass sign-in, DRM, private content, or platform restrictions.

## 2. Confirm reuse rights

Open `resources/rights.json`. Keep `reuse_permission_confirmed` as `false` until you have permission to download, edit, and repost clips from every listed source. After you receive permission, set it to `true` and add a short reference to the written permission in `permission_note`.

**A public channel link is not permission to reuse its episodes.** Do not enable this workflow without rights.

## 3. Add mood-matched music

Follow `assets/music/README.md`. Add authorized tracks to the matching mood folder and add the required licence sidecar JSON. The pipeline supports action, emotional, comedy, romantic, suspense, and interesting scenes. If the selected mood has no valid music track, the run stops instead of using unlicensed music.

## 4. Configure GitHub Actions secrets

In GitHub: repository **Settings → Secrets and variables → Actions → New repository secret**.

Required secrets:
- `OPENROUTER_API_KEY`
- `BUFFER_API_KEY`
- `BUFFER_CHANNEL_ID`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

Optional repository variable:
- `OPENROUTER_MODEL` (default: `openrouter/free`)
- `BUFFER_EXPECTED_CHANNEL_NAME` (if set, Buffer destination name is checked)

Keep all secret values private. Existing Buffer and Cloudinary credentials can be reused if they are still valid.

## 5. Enable scheduled runs

The workflow is deliberately disabled for scheduled publishing until you set repository variable:
`ENABLE_AUTO_PUBLISH=true`

Go to **Settings → Secrets and variables → Actions → Variables** and add it only after source permission, music, and credentials are ready. A manual run is available from **Actions → Pakistani Drama Clips Automation → Run workflow**.

Each successful run:
1. Finds a new episode from configured sources.
2. Detects scene windows and asks the configured OpenRouter model to classify/select a scene.
3. Selects an authorized track matching the scene mood.
4. Creates an 85-second 1080×1920 vertical clip, preserving the original dialogue and mixing music quietly underneath.
5. Uploads the clip to Cloudinary and queues a Facebook Reel in Buffer.
6. Saves the episode ID to the run-history cache to avoid processing it again.

## Notes

- A scheduled run can fail if no new episode exists, a platform blocks public extraction, AI classification fails, a licensed music track is missing, or a connected service rejects the request.
- yt-dlp uses ordinary public access only; no authentication or restriction bypass is implemented.
- The pipeline queues one clip per run; it does not directly publish to Facebook.
- GitHub Actions and third-party free-tier quotas/limits still apply.
