# Funny Animals Comedy — Private Automation

Independent GitHub Actions project for original family-friendly animal comedy videos and Facebook Reels queued through Buffer.

This repository is intentionally separate from Unique News. It has its own secrets, Buffer channel ID, Cloudinary folder, workflow names and state file. Never copy credentials or IDs from another project.

## Pipeline

1. OpenRouter's free-model router generates an original English comedy story with two consistent animal characters and six scenes.
2. Pillow draws original 2D cartoon scenes.
3. Edge TTS generates narration.
4. FFmpeg renders a vertical MP4 (1080×1920, 30 fps).
5. Cloudinary hosts the video in the dedicated `funny-animals-comedy` folder.
6. The script checks the exact Buffer channel name, Facebook service and connection/lock/queue status.
7. Buffer receives a Facebook Reel post using Facebook Reel metadata.
8. A UTC date lock helps prevent duplicate daily queueing.

A Buffer accepted/queued response is not proof that Facebook has published the post.

## Current creative scope

The first version uses procedural 2D cartoon drawings, not AI-painted or photorealistic scenes. Narration is generated with Edge TTS. It does not add third-party music, avoiding music licensing problems. Video length is flexible within a 12–180 second validation range.

## GitHub setup

Open **Settings → Secrets and variables → Actions**.

### Repository secrets

Add:
- `OPENROUTER_API_KEY`
- `BUFFER_API_KEY`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

### Repository variables

Add:
- `BUFFER_CHANNEL_ID` — the ID of the Animated Jungle Facebook channel in Buffer. Never use the Unique News channel ID.
- `BUFFER_EXPECTED_CHANNEL_NAME` — exactly `Animated Jungle`; the Buffer channel name or display name must match.
- 
Keep the Cloudinary folder as `funny-animals-comedy`.

Never put secret values in code, README files, workflow YAML or screenshots.

## Safe test sequence

1. Add the secrets and variables above.
2. Open **Actions → Validate Funny Animals Setup → Run workflow**.
3. Confirm the run says `Validation passed`. This checks configuration and destination only; it does not generate, upload or queue a video.
4. To generate and queue one video manually, open **Actions → Funny Animals Daily Publisher → Run workflow**, set `publish` to `true`, and run it.
5. Inspect the queued post in Buffer before relying on automatic posting.

Automatic daily queueing is disabled by default. Only after checking a successful manual test, add repository variable:
- `ENABLE_AUTO_PUBLISH` = `true`

The schedule is 13:00 UTC (18:00 Pakistan Standard Time). GitHub scheduled jobs may start later than the exact cron time.

## Project files

- `main.py` — story generation, cartoon scenes, narration, video rendering, Cloudinary upload, Buffer queueing and duplicate guard.
- `.github/workflows/publish.yml` — daily schedule and manual publishing workflow.
- `.github/workflows/validate.yml` — non-publishing setup validation.
- `requirements.txt` — Python dependencies.
- `state/last_queued_date.txt` — daily duplicate guard.
- `.env.example` — variable names only; no credentials.

## Safety / privacy

- Keep this repository **Private**.
- Do not reuse the Unique News Buffer channel ID, secrets, Cloudinary folder, or repository.
- The workflow's GitHub token can write only to this repository under its workflow permissions.
- The script stops if the Buffer destination does not match the expected Facebook page.
- Cloudinary delivery URLs are public; anyone with the URL may be able to view the video.
- Do not enable automatic publishing until the manual test has been reviewed.

## Troubleshooting

- **SAFETY STOP:** check the configured Buffer channel ID and exact page name.
- **Missing secret/variable:** add it under repository Settings → Secrets and variables → Actions.
- **OpenRouter error:** check the API key and free-model rate limits; the built-in story fallback is used for temporary API outages.
- **Buffer error:** check the page connection and posting permissions.
- **Queued/scheduled:** Buffer accepted the post; Facebook publication is a separate later status.
