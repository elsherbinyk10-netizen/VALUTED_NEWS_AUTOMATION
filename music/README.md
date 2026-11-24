# VALUTED MUSIC automation system

This project is isolated to the VALUTED MUSIC Shopify store (`valutedmusic.site`), Shopify Admin host `0k31v6-th.myshopify.com`, and its existing `news` blog. It does not authorize edits to VALUTED NEWS, VALUTED BEAUTY, or any other store.

## Daily Cairo publishing schedule

GitHub Actions uses UTC cron. The configured UTC times below match Cairo local time during the UTC+2 season; Egypt daylight-saving changes can shift the displayed local hour unless the cron is adjusted seasonally.

| Cairo target (UTC+2 season) | Workflow | Daily limit |
|---|---|---:|
| 9:00 PM | Official music video / lyrics video / official audio discovery and publishing | Up to 2 |
| 9:15 PM | RSS-based music news briefs | Up to 3 |
| 9:30 PM | MusicBrainz artist, album and recording catalogue | Up to 30 |
| 10:00 PM | Read-only technical and content SEO audit | All published blog articles |

The three publishing workflows retain their current limits and duplicate protections. Manual dispatch remains dry-run by default unless the explicit publish input is selected. Scheduled runs use the configured automatic publishing behavior.

## Content and discovery

- **Music news:** RSS discovery from established music publishers, source attribution and links to the original reporting, freshness checks, duplicate prevention, Shopify SEO title/description fields and genre tags. No OpenAI API key is used.
- **Official videos:** manually verified official-channel allowlist, public YouTube channel RSS and no-key oEmbed metadata, thumbnail reachability checks, responsive official embeds and VideoObject JSON-LD. No YouTube Data API key is used by the current worker. Only candidates that pass its configured checks are eligible.
- **Music catalogue:** public MusicBrainz search for artist, album/release and recording metadata; stable MusicBrainz ID deduplication; source links; no invented streaming or official-video links.
- **VALUTED Radar:** browser-only microphone/upload fingerprint matcher. No recognition API, server, VPS, or external audio-recognition service. It only recognizes audio already represented in the fingerprint library.

## Daily SEO audit

The new `music/seo_audit.py` workflow is read-only. It checks published article pages for:
- Shopify SEO title and meta-description fields, including length warnings.
- Public page reachability, rendered title and meta description.
- Canonical URL consistency and noindex directives.
- Presence of the article URL in the Shopify blog sitemap.
- One-H1 structure and descriptive image alt text.
- Video embeds and VideoObject JSON-LD consistency.
- Thin-content warnings for editorial and catalogue pages.
- Site robots.txt availability and broad crawl blocking.

The audit uploads a Markdown and JSON report as a GitHub Actions artifact. It does not rewrite articles, alter handles, delete historical content, change the theme, or claim that Google has indexed a page. Actual indexing and search performance must be checked in Google Search Console; this workflow does not have Search Console access.

## SEO publishing standards

- Keep stable, descriptive article URLs; never change existing handles just to insert keywords.
- Write unique, accurate titles and descriptions for each page; avoid keyword stuffing.
- Keep original source attribution and links on news briefs.
- Use useful, original editorial context. The audit flags thin pages rather than fabricating facts or padding articles.
- Use descriptive image alt text and responsive video embeds.
- Include valid structured data only when the page genuinely contains the corresponding content.
- Maintain crawlable internal navigation and a valid Shopify sitemap.
- Google indexing is not guaranteed by publishing or sitemap presence. Monitor indexing, impressions, clicks and query performance in Search Console.

## Safety and preservation

- Every publishing worker verifies the exact Shopify store name, primary domain and existing `news` blog before writing.
- Existing articles and URLs are preserved; video IDs and MusicBrainz IDs support duplicate checks.
- No workflow changes Shopify themes, domains, navigation, billing or storefront settings.
- The SEO audit is read-only.
- Radar audio is processed in the visitor's browser. The source audio is not uploaded; fingerprints and metadata are the only catalogue data.
- Shopify credentials remain in GitHub Actions secrets. Never place credentials in source files, issues, commits or chat.

## Radar limitations and release

The shared Radar catalogue starts empty. Recognition is limited to recordings included in a fingerprint library made from audio the owner is authorized to process. It is an experimental matcher, not a global music database or a Shazam-equivalent, and it does not recognize humming or singing. Test current Safari, Chrome and Firefox, iOS microphone permission, noisy recordings and labeled samples before public release.

Radar hosting and Shopify embedding are separate release steps. Do not publish or modify a live Shopify theme without separate approval.
