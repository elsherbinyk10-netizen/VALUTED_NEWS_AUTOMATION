# VALUTED MUSIC platform setup and release checklist

## Verified target
- Shopify store: **VALUTED MUSIC**
- Public domain: https://valutedmusic.site
- Shopify Admin host: 0k31v6-th.myshopify.com
- Existing blog: news
- Preserve all six original Music articles and any additional existing articles.
- Do not access or modify VALUTED NEWS or VALUTED BEAUTY.

## 1. Official music-video publisher
Workflow: .github/workflows/valuted-music-video-daily.yml
Worker: music/video_worker.py

Discovery uses RSS feeds only from music/official_channels.json. Every candidate is rechecked with YouTube Data API for exact channel ID, public status, embeddability, valid thumbnail, recent upload, full-length duration and official music-video, official lyrics-video and official-audio title signals. Teasers, interviews, Shorts, visualizers and non-official uploads are rejected.

Before publishing, the worker:
1. Verifies exact Shopify Admin host, store name, primary domain and news blog.
2. Checks all existing blog pages for the YouTube video ID.
3. Creates the article as a draft with a featured thumbnail, responsive privacy-enhanced YouTube embed, source attribution and seven VideoObject metafields in the same mutation.
4. Verifies the draft's image and metadata.
5. Publishes only after those checks pass.

Shopify Admin GraphQL supports an article image and article metafields on ArticleCreateInput; publication can then be performed with articleUpdate. See [Shopify ArticleCreateInput](https://shopify.dev/docs/api/admin-graphql/2026-07/input-objects/ArticleCreateInput) and [articleUpdate](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/articleUpdate).

Required GitHub Actions secrets:
- VALUTED_MUSIC_SHOPIFY_ADMIN_ACCESS_TOKEN — Music store only, read_content + write_content.
- VALUTED_MUSIC_YOUTUBE_DATA_API_KEY — YouTube Data API.

Required Actions variable:
- VALUTED_MUSIC_SHOPIFY_ADMIN_DOMAIN=0k31v6-th.myshopify.com

The workflow schedule is 9:00 PM Cairo (19:00 UTC), maximum two verified videos/run, maximum age 72 hours. Each watch page receives a thumbnail, responsive embed, unique SEO title/description, VideoObject JSON-LD and article metafields. Schedule is 9:00 PM Cairo; scheduled publishing is enabled once Music-only credentials are configured. Manual dispatch has a publish checkbox defaulting off.

## 2. Music-news editorial workflow
Workflow: .github/workflows/valuted-music-daily.yml
Worker: music/worker.py

The existing RSS-based music-news workflow remains separate from the official-video and catalogue modules. It uses the Music-only Shopify credentials and OPENAI_API_KEY. It is scheduled daily at 9:15 PM Cairo, up to three recent source-attributed stories. Shopify global title_tag and description_tag metafields are set and verified after creation. Together with up to two official video pages, the editorial/video ceiling is five new articles per day. Scheduled publishing is enabled once Music-only credentials are configured; manual dispatch defaults off.

## 3. Music catalogue expansion
Workflow: .github/workflows/valuted-music-catalog-daily.yml
Worker: music/catalog_worker.py

Uses the public MusicBrainz search API to discover artist, album/release-group and recording metadata, with source links and stable MBID tags. Maximum 30 entries per run. Each artist, album and recording page receives SEO title and description metafields and a stable MusicBrainz ID tag. It does not create invented video links, audio streams or claims of music rights. Schedule is 9:30 PM Cairo; scheduled publishing is enabled once Music-only credentials are configured; manual dispatch defaults off.

## 4. VALUTED Radar — no recognition API
App: music/radar-browser/

Radar performs microphone capture or audio-file upload, audio decoding, fingerprint generation and matching entirely in the browser. It uses no AudD, AcoustID, Shazam, Spotify, Apple Music or other recognition API; no VPS or recognition backend is required. A static HTTPS host serves the app and shared JSON fingerprint catalogue only.

The shared library.json starts empty. The owner must create fingerprints from audio they are authorized to process, export the JSON catalogue and publish the reviewed catalogue. Radar recognizes only tracks in that library; it is not a worldwide music database, does not recognize humming/singing and remains experimental pending iOS Safari and noisy-recording tests.

## 5. Theme and launch boundary
The static Radar app still needs to be hosted and embedded in a duplicate/unpublished Shopify theme. No live theme, navigation, domain or storefront changes are part of this automation build. Do not publish a theme without separate explicit approval.

## 6. Credentials and activation
Never store credentials in source code. Configure the Music-only GitHub secrets/variable above. The draft PR remains unmerged; schedules are not active on the default branch until review and merge. Configure the Music-only secrets/variable, verify workflow runs, then merge to activate the scheduled publishing. No other store is in scope.
