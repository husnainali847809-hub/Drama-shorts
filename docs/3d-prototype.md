# 3D Prototype Preview

This preview is an isolated, manual-only experiment for the Animals AI Automation project.

## What it does

- Uses Blender's Python API to create a simple stylized 3D cartoon monkey scene.
- Animates a gentle character bounce and repeated arm wave.
- Renders 5 seconds at 540x960 and 24 FPS.
- Uses FFmpeg to encode an H.264 MP4.
- Uploads the MP4 as a GitHub Actions artifact.

## Run locally

Install Blender and FFmpeg, then run from the repository root:

```bash
blender --background --python scripts/3d_prototype.py -- --output output/animals-3d-prototype.mp4
```

## Run on GitHub

Open **Actions → 3D Cartoon Prototype Preview → Run workflow**. This workflow is manual only. It does not call OpenRouter, Cloudinary, Buffer, Facebook, or the existing publishing workflow.

Download the `animals-3d-prototype-preview` artifact from the completed workflow run.

## Scope and limitations

This is a first technical render test, not the final 30–45 second story pipeline. It uses procedural geometry rather than an AI-generated character model. The purpose is to verify that the repository's GitHub Actions runner can install Blender, render a short 3D scene, encode it, and return a reviewable preview without paid APIs.

The render resolution is intentionally modest for the first benchmark. Character modelling, scene variety, animation rigging, narration integration, 9:16 final export settings, and production-quality lighting will be improved after the first render is reviewed.

No existing publishing code or publishing workflow is changed by this prototype.
