# Pakistani Drama Clips Automation

This repository is prepared to create **one vertical Pakistani drama clip per scheduled run** and add it to the configured Facebook Reel queue in Buffer. The schedule runs five times daily (Pakistan time: 09:00, 12:00, 15:00, 18:00, 21:00), for a target of five queued clips per day when all inputs and services are available.

## 1. Add authorized drama sources

Open `resources/drama_sources.txt` and paste one YouTube channel URL or Facebook Page URL per line. The file is intentionally blank until you have permission from each rights holder.

The system checks configured sources for recent uploads. YouTube channel feeds are supported through yt-dlp's normal public access. Facebook links may work only when the page/video is publicly accessible through yt-dlp. The system does not use cookies, bypass sign-in, DRM, private content, or platform restrictions.

## 1A. Discover local Pakistani drama upload channels

The scheduled workflow also runs `discover_local_sources.py` against `resources/discovery_sources.txt`. This list contains candidate Urdu/Pakistani drama upload channels beyond the major broadcasters. The scanner reads public YouTube channel feeds and writes recent uploads (last 30 days) to `output/local_channel_discoveries.csv`, which is included in the workflow artifact.

This is discovery only: it does not download those videos or add them to the reposting queue. Channel handles and upload availability can change; inspect the CSV and verify the uploader/source before using any footage.


## 1B. Automatic openly licensed archive fallback

If the configured broadcaster/channel sources cannot provide a public stream, the main pipeline now searches Internet Archive automatically for Pakistani/Urdu drama video items. It accepts only items whose uploader metadata declares **CC0** or **Public Domain Mark**, checks for a directly downloadable original video file, probes its duration, and passes the remote file to the same scene-selection and rendering pipeline. Only the selected 85-second segment is fetched.

Important limitations:
- This is a fallback source, not a guarantee of finding a current or latest drama episode. Internet Archive may have no matching item.
- Internet Archive says uploaded video rights must belong to the uploader or be public domain; its license metadata is uploader-supplied and is not an independent legal verification. Review the item page and rights before enabling reuse.
- The fallback does not access private files, DRM streams, account sessions, or bypass YouTube/Facebook restrictions.
- The runner requires `ffprobe`, which is installed with FFmpeg in the GitHub Actions workflow.

Internet Archive supports metadata search by license URL and provides item metadata/file listings; see [its search help](https://archivesupport.zendesk.com/hc/en-us/articles/360018359991-Search-A-Basic-Guide) and [video rights guidance](https://archivesupport.zendesk.com/hc/en-us/articles/360017808151-Movies-and-Videos-A-Basic-Guide).

## 2. Confirm reuse rights

Open `resources/rights.json`. Keep `reuse_permission_confirmed` as `false` until you have permission to download, edit, and repost clips from every listed source. After you receive permission, set it to `true` and add a short reference to the written permission in `permission_note`.

**A public channel link is not permission to reuse its episodes.** Do not enable this workflow without rights.

## 3. Add mood-matched music

Follow `assets/music/README.md`. Add authorized tracks to the matching mood folder and add the required licence sidecar JSON. The pipeline supports action, emotional, comedy, romantic, suspense, and interesting scenes. If the selected mood has no valid music track, the run stops instead of using unlicensed music.

## 4. Configure GitHub Actions

In GitHub: repository **Settings → Secrets and variables → Actions**.

Add these as **Secrets**:
- `OPENROUTER_API_KEY`
- `BUFFER_API_KEY`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

Add these as **Variables**:
- `BUFFER_CHANNEL_ID` (your intended Facebook channel ID in Buffer)
- `BUFFER_EXPECTED_CHANNEL_NAME` (optional; if set, Buffer destination name is checked)
- `OPENROUTER_MODEL` (optional; default: `openrouter/free`)

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
