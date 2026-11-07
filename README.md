# AI Animal Stories — Facebook Reels Production

This repository now produces original AI-generated 3D animal story videos. The former Movie Reels discovery/clipping workflow is retired from the main entry point.

## Pilot format
- Original story: **Timo & Bunny: A Little Bridge of Friendship**
- Seven cinematic scenes, 10 seconds each (target ~70 seconds).
- Vertical 9:16, final render 1080×1920 at 30 fps.
- Original recurring characters with saved reference images.
- English + Pakistani Urdu narration.
- Generated scenes are assembled locally with FFmpeg.
- Output is review-only. **Nothing is published automatically.**

## AI providers and cost
The first implementation uses fal.ai:
- FLUX Kontext Max for character/reference and scene imagery.
- Kling Video v3 Standard image-to-video for motion.
- Edge TTS for English and Urdu narration.
AI generation is paid and can incur provider charges. The workflow requires the `FAL_KEY` secret. Model availability, pricing, regional access and terms can change; check the provider account before running. The selected models' official API documentation is linked below.

## Required setup
1. Add GitHub Actions secret `FAL_KEY`.
2. Optional repository variables:
   - `FAL_IMAGE_MODEL` (default `fal-ai/flux-pro/kontext/max/text-to-image`)
   - `FAL_EDIT_MODEL` (default `fal-ai/flux-pro/kontext/max/multi`)
   - `FAL_VIDEO_MODEL` (default `fal-ai/kling-video/v3/standard/image-to-video`)
   - `TTS_EN_VOICE` (default `en-US-GuyNeural`)
   - `TTS_UR_VOICE` (default `ur-PK-AsadNeural`)
3. Run **AI Animal Pilot — Manual Review** from GitHub Actions > Run workflow.
4. Download the workflow artifact and watch the complete MP4. Reject it if character identity, motion, voice, story, or image quality is poor.

## Manual publishing safety
- The generation workflow does not call Buffer.
- The generated file is named `REVIEW_ONLY` and is never automatically queued.
- Only after watching and approving the MP4, run locally:
  `PUBLISH_APPROVED=true python main.py --publish-approved output/animal_pilot/PILOT_Timo_and_Bunny_REVIEW_ONLY.mp4 --caption "Your approved caption"`
- Manual publishing requires the existing Buffer and Cloudinary secrets/environment variables. This queues the approved Reel; it does not prove Facebook has published it.
- Never put API keys in source files or commit them.

## Quality limitations
AI video models can still change details between shots, create visual artifacts, or animate anatomy incorrectly. Character reference images reduce but do not eliminate drift. Review every generated scene and regenerate failures before approval. This pipeline does not claim guaranteed studio-grade output or guaranteed Facebook monetization.

## References
- [FLUX Kontext Max image generation and editing API](https://fal.ai/models/fal-ai/flux-pro/kontext/max/api)
- [Kling Video v3 Standard image-to-video API](https://fal.ai/models/fal-ai/kling-video/v3/standard/image-to-video/api)
