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

## Music Radar audio recognition — browser-only, no API and no VPS

The browser prototype is in `music/radar-browser/`. It is a static HTML/CSS/JavaScript app: microphone capture, audio decoding, fingerprint generation and matching run on the visitor's device. It does not call AudD, AcoustID, Shazam, Spotify, Apple Music, or any external recognition API. It does not need a VPS, a recognition backend, or a server-side database.

The prototype uses a local constellation-style audio fingerprint (FFT spectral peaks paired across time) and matches against a private VALUTED MUSIC JSON fingerprint catalogue. The bundled `library.json` is currently empty. A site owner can add audio files they are authorized to process in the Library Builder, export the JSON catalogue, and publish the resulting JSON as the shared static catalogue. Visitors can also import a catalogue locally.

Important limitations:
- Radar recognizes only recordings already included in its fingerprint library; it is not a worldwide music database and cannot identify every song.
- It does not recognize humming or singing.
- This is an experimental prototype, not a production-grade Shazam replacement. It requires real-device tests with known audio clips, noisy microphone recordings, and iOS Safari before release.
- Microphone access requires HTTPS and explicit browser permission. Upload is the fallback.
- Audio samples are processed in memory; only fingerprints and metadata are stored in browser local storage or the exported JSON.
- The browser downloads the static catalogue JSON from the same site. This is static file hosting, not an external recognition API.

The app can be hosted on a static HTTPS host such as GitHub Pages and embedded in a Shopify page. Static hosting must be enabled/configured for the repository before the page is publicly available. Do not deploy the old `music/radar-worker.js` proxy; it is retired.

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
