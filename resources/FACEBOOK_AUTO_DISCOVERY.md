# Automatic Facebook drama-source discovery

The automation no longer needs manually supplied Facebook Page URLs or
`resources/facebook_pages.json`. It searches public Facebook Pages for the
configured Pakistani-drama keywords, then checks recent public videos from
the returned Pages.

## Required GitHub configuration

1. Create/configure a Meta developer app and enable the Pages API.
2. Request and obtain Meta approval for **Page Public Content Access** (or
   another permission Meta explicitly confirms is sufficient for the intended
   public Page search and video-listing use case).
3. Create a valid app access token for that approved app.
4. In the GitHub repository, open **Settings → Secrets and variables →
   Actions → New repository secret**.
5. Add the secret named `META_APP_ACCESS_TOKEN` and paste the token there.
   Do not put the token in source files, commits, workflow variables, or chat.

The workflow uses Graph API `v26.0` by default. If Meta requires a different
supported version for the app, set the Actions variable
`META_GRAPH_API_VERSION` accordingly.

## Optional search tuning

Set the Actions variable `FACEBOOK_SEARCH_TERMS` to comma-separated Page
search terms. The default is:

`Pakistani drama,Pakistani drama official,Pakistani television drama`

The workflow checks up to 30 discovered video candidates by default. The
`FACEBOOK_MAX_CANDIDATES` value can be changed in
`.github/workflows/publish.yml`.

## Important limitations

- Meta's Pages Search API discovers Pages, not every Facebook post/video by
  keyword. This is not unrestricted Facebook-wide content search.
- Search and public video listing may return no data until Meta approves the
  required feature permissions and the token is valid.
- Finding a public video does not guarantee that its media stream is available
  to this runner. The existing downloader only attempts ordinary accessible
  streams; it does not bypass login, privacy settings, anti-bot checks, DRM,
  or other platform restrictions.
- Use videos only where the rights holder has authorized reuse. The existing
  repository rights check remains in place.
