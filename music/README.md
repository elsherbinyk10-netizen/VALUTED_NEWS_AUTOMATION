# VALUTED MUSIC automation system

This project is isolated to the Shopify store VALUTED MUSIC (valutedmusic.site), Shopify Admin host 0k31v6-th.myshopify.com, and its existing news blog. It does not authorize edits to VALUTED NEWS or VALUTED BEAUTY.

## Modules
- **Official music videos:** YouTube channel RSS discovery, strict allowlist matching, YouTube Data API verification of channel ownership/public status/embeddability/duration, thumbnail + responsive player + VideoObject JSON-LD + SEO metadata, duplicate prevention. Accepts verified official music videos, official lyrics videos and official audio.
- **Music catalogue:** MusicBrainz artist, album/release and recording discovery, stable MBID deduplication, source-linked catalogue entries; no invented playback or official-video claims.
- **VALUTED Radar:** browser-only microphone/upload fingerprint matching. No recognition API, server, VPS, or external audio service. It only matches recordings already indexed in the owner's local/shared fingerprint library.

## Safety defaults
- Scheduled workflows publish automatically only from the Music-only GitHub secrets after their release configuration is complete. Manual dispatch retains an explicit publish checkbox defaulting off.
- Manual workflow dispatch includes an explicit publish checkbox; it defaults off.
- Video articles are created as drafts with thumbnail and all required video metadata in the same Shopify mutation. They are published only after the draft is re-read and the image/metafields are verified.
- Exact Shopify host, store name, primary domain and existing blog handle are checked before any write.
- Only manually verified official YouTube channel IDs are accepted: Rotana, Warner Music Group, Sony Music UK, THEBLACKLABEL, Daddy Yankee and Naima Bock.
- Existing articles are preserved; video IDs and MusicBrainz IDs are used for duplicate checks.
- The Radar never uploads audio; audio samples are processed in-browser. Only fingerprints and metadata are saved/exported.
- No workflow changes Shopify themes, domains, navigation, billing or storefront settings.

## Credentials
GitHub Actions → Settings → Secrets and variables:
- Secret VALUTED_MUSIC_SHOPIFY_ADMIN_ACCESS_TOKEN: token for the Music store only, with read_content and write_content.
- Secret VALUTED_MUSIC_YOUTUBE_DATA_API_KEY: YouTube Data API key for official-video discovery.
- Secret OPENAI_API_KEY: required only by the separate music-news editorial worker.
- Variable VALUTED_MUSIC_SHOPIFY_ADMIN_DOMAIN: 0k31v6-th.myshopify.com.

Never paste credentials into source files, issues, chat or commits. The direct Shopify publishing test already completed separately; it does not supply GitHub Actions secrets.

## Schedule and limits
- Official music-video / lyrics-video / official-audio watch pages: daily 9:00 PM Cairo; up to 2 verified videos/run; maximum age 72 hours.
- Music news: daily 9:15 PM Cairo; up to 3 source-attributed stories/run; maximum age 36 hours.
- Editorial + video publishing ceiling: 5 new content articles/day (2 video pages + 3 news stories maximum).
- Music catalogue: daily 9:30 PM Cairo; up to 30 artist, album and recording pages/day, tracked separately from the five editorial/video stories.
- Scheduled runs publish automatically; manual dispatch remains opt-in. Missing credentials fail closed.

## Radar limitations
The bundled shared library.json starts empty. Radar can identify only recordings included in a fingerprint library created from audio the owner is authorized to process. It is an experimental fingerprint matcher, not a global music database or a Shazam-equivalent. It does not identify humming or singing. Test iOS Safari, microphone permissions, noisy recordings and labeled samples before release.

## Release gates
1. Configure Music-only GitHub secrets/variable.
2. Run discovery-only workflows and review candidate logs.
3. Enable publish only for a deliberate manual run after review.
4. Test the public Radar static host and real-device audio matching.
5. Connect the Radar page in a duplicate/unpublished Shopify theme; never publish the live theme without separate approval.

The development pull request remains unmerged. Scheduled workflows are not active on the default branch until the pull request is reviewed and merged.
