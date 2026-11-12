# Pakistani Drama Clips Automation

This repository is prepared to create **one vertical Pakistani drama clip per scheduled run** and add it to the configured Facebook Reel queue in Buffer. The schedule runs five times daily (Pakistan time: 09:00, 12:00, 15:00, 18:00, 21:00), for a target of five queued clips per day when all inputs and services are available.

## Google Drive video input (primary source)

The publishing workflow now reads the newest unprocessed video from one Google Drive folder using the Drive API. It downloads that file to the temporary GitHub Actions runner, analyzes candidate scenes, renders one vertical clip, uploads it to Cloudinary, and queues it in Buffer. The original full video is not committed to this repository.

### Configure Google OAuth securely

1. In Google Cloud Console, enable the **Google Drive API** for the project used by your OAuth client.
2. Use the OAuth client JSON you downloaded to obtain a refresh token with the `https://www.googleapis.com/auth/drive.readonly` scope. The OAuth consent/account must be the same Google account that can access the video folder.
3. In GitHub **Settings → Secrets and variables → Actions → Secrets**, add:
   - `DRIVE_CLIENT_ID` — OAuth client ID from the downloaded client JSON.
   - `DRIVE_CLIENT_SECRET` — OAuth client secret from that JSON.
   - `DRIVE_REFRESH_TOKEN` — refresh token (keep it secret; never commit or paste it into chat).
4. In **Settings → Secrets and variables → Actions → Variables**, add:
   - `DRIVE_FOLDER_ID` — the folder ID from the Google Drive folder URL (the part after `/folders/`).
5. Put your authorized video file inside that folder. Supported inputs are regular video files such as MP4, MOV, MKV, or WEBM; Google Docs/Slides/Photos links are not video files.

The Drive OAuth token needs read-only access. The workflow does not need permission to edit or delete Drive files. Only upload videos you own or have permission to edit and repost. A successful run queues a clip in Buffer; it does not publish immediately.

## 1. Add authorized drama sources

Open `resources/drama_sources.txt` and paste one YouTube channel URL or Facebook Page URL per line. The file is intentionally blank until you have permission from each rights holder.

The system checks configured sources for recent uploads. YouTube channel feeds are supported through yt-dlp's normal public access. Facebook links may work only when the page/video is publicly accessible through yt-dlp. The system does not use cookies, bypass sign-in, DRM, private content, or platform restrictions.

## 1A. Discover local Pakistani drama upload channels

The scheduled workflow also runs `discover_local_sources.py` against `resources/discovery_sources.txt`. This list contains candidate Urdu/Pakistani drama upload channels beyond the major broadcasters. The scanner reads public YouTube channel feeds and writes recent uploads (last 30 days) to `output/local_channel_discoveries.csv`, which is included in the workflow artifact.

This is discovery only: it does not download those videos or add them to the reposting queue. Channel handles and upload availability can change; inspect the CSV and verify the uploader/source before using any footage.

## 2. Confirm reuse rights

Open `resources/rights.json`. Keep `reuse_permission_confirmed` as `false` until you have permission to download, edit, and repost clips from every listed source. After you receive permission, set it to `true` and add a short reference to the written permission in `permission_note`.

**A public channel link is not permission to reuse its episodes.** Do not enable this workflow without rights.

## 3. Add scene-matched music

Upload your own or properly licensed music files under the repository root folder: `dramas/`. The editor searches this folder and all subfolders recursively. Supported formats: MP3, WAV, M4A and AAC.

For reliable mood matching, use clear names or mood folders, for example:
- `dramas/comedy/funny_upbeat.mp3`
- `dramas/romantic/soft_love.mp3`
- `dramas/emotional/sad_piano.mp3`
- `dramas/suspense/dark_tension.mp3`
- `dramas/action/epic_energy.mp3`

The editor checks the scene category, mood words in the file/folder name, and measured audio characteristics (approximate energy and spectral brightness). It ranks plausible tracks and does **not** fall back to a random unrelated song. If it cannot find a confident match, it keeps the original drama audio.

Important limitation: acoustic analysis cannot understand song lyrics or guarantee the song's story meaning. Clear mood labels in the filename/folder are still needed for dependable matching. Use only music you own or are licensed to use.

## 3A. AI scene selection and professional editing

The AI compares candidate windows using four ordered frames per candidate, then selects the most coherent visible story moment and assigns one category: action, emotional, comedy, romantic, suspense, or interesting. You can optionally set the repository variable `SCENE_PREFERENCE` to describe the kind of moment to prioritize. The AI only judges what is visible in the sampled frames; it does not claim to understand dialogue it has not analysed.

The editing engine detects shot changes and applies one of three treatments:
- **Clean story:** preserves natural pacing and the original scene order.
- **Dialogue-to-song:** for comedy/romantic scenes, estimates an opening dialogue pause before introducing matching background music; original dialogue remains audible.
- **Cinematic:** for action, suspense and emotional scenes, uses detected cuts with subtle opening/closing fades.

## 3B. Clip length

For a manual workflow run, choose one of these durations:
- **30 seconds**
- **45 seconds**
- **60 seconds**
- **180 seconds (maximum 3 minutes)**

Scheduled runs default to 60 seconds. The code rejects any other duration, and the selected clip cannot exceed 180 seconds.

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
- `SCENE_PREFERENCE` (optional; a short instruction for the kind of coherent scene to prioritize)

Keep all secret values private. Existing Buffer and Cloudinary credentials can be reused if they are still valid.

## 5. Enable scheduled runs

The workflow is deliberately disabled for scheduled publishing until you set repository variable:
`ENABLE_AUTO_PUBLISH=true`

Go to **Settings → Secrets and variables → Actions → Variables** and add it only after source permission, music, and credentials are ready. A manual run is available from **Actions → Pakistani Drama Clips Automation → Run workflow**.

Each successful run:
1. Finds a new episode from configured sources.
2. Detects scene windows and asks the configured OpenRouter model to classify/select a scene.
3. Selects an authorized track matching the scene mood.
4. Creates a 30-, 45-, 60-, or 180-second 1080×1920 vertical clip (scheduled runs default to 60 seconds), preserving dialogue and adding a confidently matched track when available.
5. Uploads the clip to Cloudinary and queues a Facebook Reel in Buffer.
6. Saves the episode ID to the run-history cache to avoid processing it again.

## Notes

- A scheduled run can fail if no new episode exists, a platform blocks public extraction, AI classification fails, a licensed music track is missing, or a connected service rejects the request.
- yt-dlp uses ordinary public access only; no authentication or restriction bypass is implemented.
- The pipeline queues one clip per run; it does not directly publish to Facebook.
- GitHub Actions and third-party free-tier quotas/limits still apply.