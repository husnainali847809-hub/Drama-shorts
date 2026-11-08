# Free Animal Stories — Facebook Reels

This branch replaces paid fal.ai generation with a free, local procedural 3D animation workflow. Blender creates original stylized animal characters and jungle scenes; Edge TTS creates Pakistani Urdu + English narration; FFmpeg assembles the final video.

## Pilot format
- Original story: Timo & Bunny: A Little Bridge of Friendship
- Seven scenes, approximately 10 seconds each (about 70 seconds).
- Vertical 9:16, 720×1280 at 24 fps, configured for an 8 GB RAM computer.
- Original tiger cub and rabbit models built from Blender meshes.
- Urdu + English narration.
- Review-only output. Nothing is automatically published.

## Free tools
- Blender: https://www.blender.org/download/
- Python 3.10+ (3.11 recommended): https://www.python.org/downloads/
- FFmpeg: https://ffmpeg.org/download.html
- Edge TTS: free-to-use command-line library; internet is required and Microsoft service availability/terms may change.

No fal.ai account, API key, paid image/video model, or paid generation credits are required. Rendering uses your PC resources and electricity. This produces stylized low-poly 3D animation, not photorealistic AI video.

## Windows setup
1. Install Blender.
2. Install Python 3.11 and enable Add Python to PATH.
3. Install FFmpeg and add its bin folder to PATH.
4. Download this repository and open Command Prompt in its folder.
5. Run:
   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
6. Generate:
   ```powershell
   python main.py --generate --pilot
   ```
If Blender is not on PATH, set BLENDER_EXE to its full blender.exe path, for example:
   ```powershell
   $env:BLENDER_EXE="C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
   ```

## Output and manual approval
Output: output/animal_pilot/PILOT_Timo_and_Bunny_REVIEW_ONLY.mp4. Watch the complete MP4 before publishing. Generation never calls Buffer.

Only after watching and approving the video, publishing can be explicitly invoked using existing Buffer/Cloudinary configuration:
   ```powershell
   $env:PUBLISH_APPROVED="true"
   python main.py --publish-approved output/animal_pilot/PILOT_Timo_and_Bunny_REVIEW_ONLY.mp4 --caption "A little kindness creates a big friendship!"
   ```
This queues the approved video; it does not guarantee Facebook has published it.

## Limitations
This free version creates stylized procedural 3D characters from Blender primitives. It is lightweight and dependable, but simpler than studio animation. Rendering may take a long time on 8 GB RAM. Keep other heavy apps closed. Edge TTS requires internet. No copyrighted cartoon, film, or TV footage is used.


## Hindi mixed-content Facebook Reels (Animated Jungle)

The scheduled publisher can create one Hindi Reel at each existing Pakistan-time slot:
- 08:00 — movie explanation (original commentary based on a sourced article; no movie footage is downloaded)
- 11:00 — anime/comic-inspired visual explainer (licensed still images with a stylized filter; this is not full AI video-to-anime conversion)
- 14:00 — mini documentary
- 17:00 — true-story explainer
- 20:00 — original fictional Hindi story

Each run researches a topic, creates an original five-part Hindi script with an OpenRouter free model, generates Hindi narration with Edge TTS, downloads only reusable Wikimedia Commons images (Public Domain, CC0 or CC BY 4.0), adds Hindi subtitles and locally synthesized background music, renders a vertical 1080x1920 / 30 fps / 87-second Reel, checks the output, uploads it to the existing Cloudinary account and adds it to the verified Animated Jungle Buffer queue.

### GitHub Actions configuration
Required GitHub secret:
- **OPENROUTER_API_KEY** — an OpenRouter key; the workflow defaults to openrouter/free and tries free fallbacks.

Existing connection settings must remain configured:
- Secrets: **BUFFER_API_KEY**, **CLOUDINARY_CLOUD_NAME**, **CLOUDINARY_API_KEY**, **CLOUDINARY_API_SECRET**
- Variables: **BUFFER_CHANNEL_ID**, **ENABLE_AUTO_PUBLISH=true**

The workflow checks the Buffer destination name and stops if it is not Animated Jungle. It queues through Buffer; queue acceptance is not proof that Facebook has published the Reel. Set ENABLE_AUTO_PUBLISH to true only when automatic queueing is intended.

### Rights and format notes
- No copyrighted Hollywood/Bollywood/Punjabi movie footage or commercial soundtrack is downloaded or republished by this mixed-content engine.
- Movie explainers use original narration and properly attributed source material; Wikipedia-derived adaptations are attributed and shared under CC BY-SA 4.0.
- Wikimedia visuals are restricted to the existing commercial-reuse allowlist (Public Domain Mark, CC0 and CC BY 4.0), with credits included in the Buffer caption. If full attribution does not fit, the run stops rather than truncating credits.
- The anime/comic slot currently applies a stylized visual treatment to licensed stills. Full generative video-to-anime transformation is not included because an unlimited free cloud model is not available.
- OpenRouter free-model availability and Edge TTS service availability are not guaranteed. If a model, source, license, image or quality check fails, the workflow skips publishing rather than posting an incomplete Reel.
- The existing Animal AI pilot workflow remains separate and review-only.
