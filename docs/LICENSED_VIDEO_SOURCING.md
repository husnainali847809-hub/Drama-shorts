# Adding public-domain or licensed cartoon videos safely

The licensed source option is intentionally opt-in. The repository's `licensed_assets.json` starts with an empty list; no source is presumed reusable. Use the **Internet Cartoon & Story Discovery** workflow to find candidate Commons videos and popular classic-story records. Discovery produces a report only; it does not approve, download or publish any candidate. Read [CONTENT_DISCOVERY.md](CONTENT_DISCOVERY.md) first.

## Where to discover candidate works

You may investigate individual items in:
- Wikimedia Commons (check the file page and the exact license for that file).
- Openverse (use it to discover works, then verify the original source page and license).
- Internet Archive (check the item's rights statement and any linked rights evidence; an upload to the Archive does not itself prove public-domain status).

A site or search filter is not a guarantee that a particular video is safe for commercial reuse. Check the video, music, voices, artwork, characters and any third-party elements separately. If the license is unclear, do not add it.

## Required review before adding an item

1. Open the original source page, not just a search result.
2. Confirm the uploader/creator and that the license applies to the exact downloadable video.
3. Confirm commercial use is allowed, modifications/branding overlays are allowed, and the rights apply in the territories where the Facebook Page is viewed.
4. Check whether music, voice, characters, logos or embedded footage have separate rights.
5. Read the license terms. CC-BY requires proper attribution. CC-BY-SA can impose share-alike obligations on adaptations. CC0 and public-domain marks still require checking that the work is genuinely free of third-party rights worldwide.
6. Keep a record of the source page, license page, date checked, and attribution wording. Do not use a source if you cannot substantiate these points.

The code's boolean rights fields are human attestations, not legal verification. Do not set them to true just to make the workflow pass.

## Manifest format

Add a reviewed item to `licensed_assets.json`:

```json
{
  "assets": [
    {
      "id": "unique-short-id",
      "title": "Exact work title",
      "creator": "Creator or rights holder",
      "source_page_url": "https://original-host.example/page-for-this-work",
      "video_url": "https://original-host.example/direct-download/video.mp4",
      "license": "CC-BY-4.0",
      "license_url": "https://creativecommons.org/licenses/by/4.0/",
      "attribution": "Title — Creator — source page — CC BY 4.0",
      "rights_verified": true,
      "commercial_use": true,
      "modifications_allowed": true,
      "worldwide_rights_confirmed": true
    }
  ]
}
```

Replace every example value with real evidence for the selected work. Do not use the example domain. The direct video URL must be an HTTPS downloadable video. The downloader checks file size and video duration.

## Run it

1. Commit the reviewed entry to `licensed_assets.json`.
2. In GitHub Actions, open **Long-Form Cartoon Daily Publisher** and select **Run workflow**.
3. Set `publish=true`, `source_mode=licensed`, and select 5, 7 or 10 minutes.
4. The video is branded with the configured Facebook Page name and source-credit overlay; the post caption includes creator, license and source attribution.
5. Inspect the Buffer queue entry before enabling automatic daily publishing.

If the manifest is empty, rights fields are incomplete, or the video duration does not match the selected target, the workflow stops before upload. The software does not strip third-party watermarks or replace creator branding.
