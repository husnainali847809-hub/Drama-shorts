# Authorized mood-matched music

Create one folder for each scene category:
- action/
- emotional/
- comedy/
- romantic/
- suspense/
- interesting/

Place only music you own, have written permission to use, or that has an accepted reusable licence in the matching folder.

For every audio file, add a sidecar named exactly like this:
`track.mp3.license.json`

Example:
```json
{
  "title": "My licensed emotional instrumental",
  "license": "direct permission",
  "permission_reference": "Written permission email dated 2026-11-08"
}
```

Accepted licence values: `public domain`, `cc0`, `cc-by`, `cc-by-sa`, or `direct permission`.
For `cc-by` and `cc-by-sa`, include an `attribution` field. For direct permission, include a `permission_reference` field.
Tracks must be at least as long as CLIP_SECONDS (default 85 seconds). Music without valid sidecar metadata is ignored.
