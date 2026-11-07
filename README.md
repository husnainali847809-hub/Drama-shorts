# Internet Cartoon & Story Discovery — Facebook Automation

Private GitHub Actions project for discovering existing cartoon videos and popular classic-story sources, reviewing their reuse rights, and queueing only approved licensed videos as Facebook Page posts through Buffer.

## New content workflow

1. **Cartoon discovery:** \`discover_content.py\` searches Wikimedia Commons for video files whose metadata declares CC0, CC BY 4.0, CC BY-SA 4.0 or Public Domain Mark 1.0.
2. **Story discovery:** the same report searches Project Gutenberg for popular classic story texts and ranks candidates by catalog download counts.
3. **Review report:** GitHub Actions saves JSON and Markdown reports as a downloadable workflow artifact. Discovery does not download videos, approve rights, or publish anything.
4. **Human rights review:** a person checks the exact source file, creator, license, music, voices, characters, translations, worldwide rights and duration.
5. **Licensed publishing:** only entries manually approved in \`licensed_assets.json\` can be downloaded, branded with attribution, uploaded to Cloudinary and queued through the existing Buffer Facebook channel.

Motu Patlu and Chhota Bheem are included as reference-only names. The system does not download or re-upload their episodes unless the rights holder provides permission or a valid license for the exact work.

## Run internet discovery

Open **Actions → Internet Cartoon & Story Discovery → Run workflow**. The workflow also refreshes the discovery report weekly. It uses public catalog APIs and does not need Facebook, Buffer, Cloudinary or AI-model secrets.

The report contains:
- Existing cartoon video candidates from Wikimedia Commons with recognized license metadata.
- Popular classic story sources from Project Gutenberg, ranked by catalog downloads.
- Source links, creator/license metadata when supplied, and warnings where global rights are not established.

**Important:** a discovery result is not legal clearance. Wikimedia metadata can be incomplete and a video can contain separately copyrighted music, voices, characters or footage. Project Gutenberg catalog status is not a worldwide commercial-use guarantee. Nothing is automatically added to the publishing manifest.

## Publishing mode

AI-generated cartoon publishing is disabled. The publisher defaults to \`CARTOON_SOURCE_MODE=licensed\` and only accepts the licensed source mode.

The manual publisher supports 5, 7 or 10 minute videos. A selected source must match the duration range and pass the video validation checks. If \`licensed_assets.json\` is empty or a rights declaration is missing, publishing stops safely before upload.

Each manifest entry must include:
- Exact work title and creator/rightsholder.
- Original source page and direct HTTPS video URL.
- License identifier and license URL.
- Attribution wording.
- Human-reviewed true declarations for rights, commercial use, modifications and worldwide rights.

Supported license declarations are CC0-1.0, CC-BY-4.0, CC-BY-SA-4.0 and PDM-1.0. These declarations are a workflow gate, not an automated legal opinion. Do not mark a work approved unless the exact video and every embedded element have been checked.

See [docs/CONTENT_DISCOVERY.md](docs/CONTENT_DISCOVERY.md) and [docs/LICENSED_VIDEO_SOURCING.md](docs/LICENSED_VIDEO_SOURCING.md).

## Existing Facebook publishing pipeline

The existing publishing integration remains in place:
1. Validate the exact Buffer channel and Facebook service.
2. Download only a manually approved licensed video.
3. Add the configured Facebook Page name and source credit overlay.
4. Re-encode to 1280×720 landscape MP4.
5. Upload to the configured Cloudinary folder.
6. Queue as a Facebook **video post** (not a Reel) through Buffer.
7. Preserve the daily duplicate guard.

A Buffer accepted/queued response is not proof that Facebook has published the post.

## GitHub setup

Open **Settings → Secrets and variables → Actions**.

### Repository secrets
- \`BUFFER_API_KEY\`
- \`CLOUDINARY_CLOUD_NAME\`
- \`CLOUDINARY_API_KEY\`
- \`CLOUDINARY_API_SECRET\`

### Repository variables
- \`BUFFER_CHANNEL_ID\` — exact intended Facebook Page channel ID in Buffer.
- \`BUFFER_EXPECTED_CHANNEL_NAME\` — exact Buffer channel name used for safety validation and video branding.
- \`ENABLE_AUTO_PUBLISH\` — keep unset/false until a manual licensed-video test has been reviewed.

The discovery workflow does not use these secrets. Never place secret values in source code, README files, workflow YAML or reports.

## Safe test sequence

1. Run the **Internet Cartoon & Story Discovery** workflow and download its report artifact.
2. Review one exact cartoon video and all rights evidence.
3. Add it to \`licensed_assets.json\` only after confirming the required commercial and worldwide rights.
4. Open **Actions → Long-Form Cartoon Daily Publisher → Run workflow**.
5. Set \`publish=true\`, select \`licensed\`, and choose 5, 7 or 10 minutes.
6. Inspect the Buffer queue entry before enabling daily automatic queueing.

Automatic daily queueing remains disabled unless \`ENABLE_AUTO_PUBLISH=true\`. The existing schedule is 13:00 UTC (18:00 Pakistan Standard Time); GitHub may start scheduled jobs later than the exact cron time.

## Project files

- \`main.py\` — existing diagnostics, Cloudinary upload, Buffer channel verification and Facebook post queueing.
- \`longform.py\` — licensed video upload orchestration; AI-generated publishing is blocked.
- \`licensed_source.py\` — rights-gated download, attribution overlay and licensed-source upload.
- \`licensed_assets.json\` — manually reviewed licensed video manifest (empty by default).
- \`discover_content.py\` — Wikimedia Commons cartoon video and Project Gutenberg story discovery.
- \`docs/CONTENT_DISCOVERY.md\` — discovery report and review guide.
- \`docs/LICENSED_VIDEO_SOURCING.md\` — license and manifest instructions.
- \`.github/workflows/discover-content.yml\` — weekly/manual non-publishing discovery.
- \`.github/workflows/publish.yml\` — daily/manual licensed video publisher.
- \`.github/workflows/check-longform.yml\` — syntax, import and manifest validation.
- \`.env.example\` — variable names only; no credentials.

## Privacy and cost

- Keep this repository **Private**.
- Discovery uses public catalog APIs and makes no paid API calls.
- Rendering uses FFmpeg on the GitHub Actions runner.
- Cloudinary video delivery URLs are public to anyone who has the URL.
- Do not enable automatic publishing until a manual video has been reviewed.
