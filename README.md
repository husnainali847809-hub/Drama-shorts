# Original Long-Form Cartoons — Facebook Automation

Private GitHub Actions project for creating original narrated cartoon stories and queueing them as long-form Facebook Page video posts through Buffer.

## Current publishing pipeline

1. OpenRouter's free-model router writes an original English story in the selected genre.
2. Pillow creates original 2D cartoon scene artwork with consistent animal characters, story cues and subtitles.
3. Edge TTS generates English narration.
4. FFmpeg assembles a 16:9 landscape MP4 at 1280×720 and 24 fps, with gentle camera movement.
5. Cloudinary hosts the video in the private project's configured folder.
6. The script verifies the exact Buffer channel name, Facebook service, connection, lock and queue status.
7. Buffer receives a Facebook **video post** (not a Reel), so 5–10 minute long-form videos can be scheduled.
8. The UTC date lock prevents duplicate daily queueing.

A Buffer accepted/queued response is not proof that Facebook has published the post.

## Story genres and duration

Manual workflow options:
- variety (randomly selects a genre)
- comedy
- kids-adventure
- moral-story
- fantasy
- mystery
- horror (mild suspense only; no gore or graphic violence)
- adventure

Duration options: 5, 7 or 10 minutes. The daily schedule defaults to a 7-minute story and randomly rotates its genre. The manual workflow defaults to 7 minutes and variety; you can choose a specific genre.

Stories are newly generated, with two original animal characters, multiple scenes, narration and subtitles. The pipeline does **not** download other creators' cartoons or remove/replace their branding. Only original content or content with explicit reuse rights should be published.

## Rendering and cost

- Story writing uses OpenRouter's `openrouter/free` model route; free availability/rate limits are not guaranteed.
- Narration uses Edge TTS.
- Scene art is generated locally with Pillow.
- FFmpeg renders locally on the GitHub Actions CPU runner.
- No paid image/video generation API is called by this pipeline.
- This is a stylized **2D** cartoon pipeline, not a finished 3D character-animation engine. The separate Blender experiment remains a preview and is not used for long-form rendering.
- Rendering 5–10 minutes can take a while on a CPU runner. Workflow timeout is 120 minutes.

## Facebook format

The long-form output is 1280×720 (16:9) and uses Facebook post metadata `type: post`, not Reel metadata. Buffer's current Facebook guidance lists video posts up to 4 hours and 1 GB, while Reels are 3–90 seconds. Vertical 9:16 uploads may be treated as Reels, so this pipeline intentionally renders landscape video.

## GitHub setup

Open **Settings → Secrets and variables → Actions**.

### Repository secrets

- `OPENROUTER_API_KEY`
- `BUFFER_API_KEY`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

### Repository variables

- `BUFFER_CHANNEL_ID` — the ID of the intended Facebook Page channel in Buffer.
- `BUFFER_EXPECTED_CHANNEL_NAME` — exact Buffer channel name/display name used as a safety check and on-video branding.
- `ENABLE_AUTO_PUBLISH` — set to `true` only after a successful manual test and review.

Never put secret values in code, README files, workflow YAML or screenshots.

## Safe test sequence

1. Confirm the secrets and variables above are already configured.
2. Open **Actions → Long-Form Cartoon Daily Publisher → Run workflow**.
3. Set `publish` to `true`, select a genre and duration, then run it.
4. Inspect the queued Facebook video post in Buffer before enabling the daily schedule.
5. Automatic daily queueing remains disabled unless `ENABLE_AUTO_PUBLISH=true`.

The daily schedule is 13:00 UTC (18:00 Pakistan Standard Time). GitHub scheduled jobs may start later than the exact cron time.

## Project files

- `main.py` — existing diagnostics, Cloudinary upload, Buffer channel verification and Facebook post queueing.
- `longform.py` — original story generation, artwork, narration, long-form rendering and upload orchestration.
- `.github/workflows/publish.yml` — daily schedule and manual genre/duration controls.
- `.github/workflows/validate.yml` — non-publishing setup validation.
- `requirements.txt` — Python dependencies.
- `state/last_queued_date.txt` — daily duplicate guard.
- `.env.example` — variable names only; no credentials.

## Safety / privacy

- Keep this repository **Private**.
- Do not reuse credentials, channel IDs or Cloudinary folders from another project.
- The workflow checks the exact Facebook destination before queueing.
- Cloudinary delivery URLs are public; anyone with the URL may be able to view the video.
- Do not enable automatic publishing until a manual long-form post has been reviewed.
