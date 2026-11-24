# VALUTED MUSIC video platform setup

## Target
- Shopify store: VALUTED MUSIC
- Public host: https://valutedmusic.site
- Existing content blog: news (do not rename or delete its existing articles)
- Daily run: 21:00 Cairo / 19:00 UTC
- Maximum: five verified official music videos per run; zero is valid.

## Official video publishing
The workflow is `.github/workflows/valuted-music-video-daily.yml`. It reads YouTube channel RSS only for channel IDs listed in `music/official_channels.json`, then verifies each candidate with YouTube Data API:
- channel ID matches the manually approved allowlist
- video is public and embeddable
- thumbnail is available over HTTPS
- video is recent and not already in the Music blog

Do not add a channel until its official artist/label ownership has been checked. Never add fan, lyric, re-upload or unofficial channels.

GitHub Actions secrets:
- `VALUTED_MUSIC_SHOPIFY_ADMIN_ACCESS_TOKEN`: token for VALUTED MUSIC only, with read_content/write_content and metafields write access.
- `VALUTED_MUSIC_YOUTUBE_DATA_API_KEY`: YouTube Data API key.

GitHub Actions variable:
- `VALUTED_MUSIC_SHOPIFY_ADMIN_DOMAIN`: `0k31v6-th.myshopify.com` (must remain the Music shop only).

The worker fails closed when secrets or the official channel allowlist are missing. The workflow is committed to the `valuted-music-video-platform` branch, not yet merged into the default branch, so the schedule is not active until reviewed and merged.

## Daily catalogue expansion
The workflow `.github/workflows/valuted-music-catalog-daily.yml` runs daily at 21:00 Cairo and invokes `music/catalog_worker.py`. It searches MusicBrainz for artists, albums/release groups and recordings, then creates crawlable editorial entries in the existing Music blog with MusicBrainz source links and stable MBID duplicate tags. The default cap is 15 new entries per run. It does not invent official video links or claim rights to audio. The MusicBrainz public API is rate-limited politely by the worker.

GitHub Actions reuses the Music-only Shopify secret and domain variable listed above. The workflow is committed to the development branch and is not scheduled until merged into the default branch.

## Music Radar audio recognition
`music/radar-worker.js` is a Cloudflare Worker proxy. Deploy it separately, then configure:
- Worker secret `AUDD_API_TOKEN` from the recognition provider.
- CORS is restricted to `https://valutedmusic.site`.
- The storefront should call the Worker URL; never expose the provider token in theme JavaScript.

The current Shopify Radar page still contains text search. Audio recording/upload UI must be connected to the deployed worker URL in the theme section setting before real recognition is available. Audio fingerprint recognition identifies recorded songs; humming recognition is not implemented.

## Video SEO
The theme contains a conditional `VideoObject` section for articles tagged `official-music-video`. The video worker writes the video ID, player URL, thumbnail, upload date, duration and description as article metafields.

Google's required VideoObject properties include unique `name`, `thumbnailUrl`, and `uploadDate`. `embedUrl` is recommended when the original video file URL is not available. Each video needs a crawlable watch page with the video prominent and consistent metadata. A valid schema does not guarantee Google indexing or video-feature appearance.

## Not yet complete
- Populate and verify official channel IDs.
- Configure the Shopify and YouTube secrets in GitHub Actions.
- Deploy the AudD proxy and add its token as a Worker secret.
- Connect the Radar page to the deployed Worker.
- Add verified official channel IDs and complete a real video workflow run; each created video article includes an embedded YouTube player in its page body and conditional VideoObject metadata.
- Merge and test the daily MusicBrainz catalogue workflow; it can add up to 15 artist/album/song pages daily once enabled.
- Connect the audio-recording UI on the Radar page to the deployed Worker URL; the current page still has its existing typed-search interface until that wiring is completed.
- Add a dedicated video sitemap only if required after checking Shopify's native sitemap and the resulting Search Console video indexing.
- Run a real workflow test, validate video pages and structured data, then inspect Search Console indexing.

Preserve all six existing Music blog articles. Do not modify the VALUTED NEWS domain/store or publish the unpublished Shopify theme without explicit approval.
