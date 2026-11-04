# Valuted News RSS → Shopify automation

This folder is arranged with the correct GitHub Actions workflow and state-file paths.

## Safety defaults
- `AUTO_PUBLISH=true`: allows publication only when every automated quality gate passes; high-risk or incomplete stories are skipped.
- New stories are selected from fresh Google Trends signals and independent coverage, then attributed to direct publisher articles. Google News aggregator URLs are discovery-only and are never presented as the reporting source.
- Direct publishing sources are restricted to the approved publisher allowlist in `news_worker.py` (BBC, NPR, NASA, The Guardian, Variety, Rolling Stone, and Billboard). Add new publishers only after validating their official RSS feed and terms.
- Every published story must have a verified publisher-declared high-resolution image (minimum 1200×675; prefer 1600×900) and a playable video embedded by the cited publisher. Unrelated search-result videos are not substituted; stories without the publisher's own verified video are held.
- SEO title, unique description, canonical source attribution, category/tags, encoding, duplicate detection, and text integrity must pass before publishing. High-risk and incomplete items are held.
- For YouTube publisher embeds, the QA theme requests captions in the visitor's selected site language. Captions appear only where the publisher/video actually provides that language track; other publisher players control their own caption availability.
- The optional OpenAI key is stored only as a GitHub Actions secret, never in files.

## Shopify details
- Public domain: `valutednews.com`
- Shopify Admin API domain: `5xd8ae-md.myshopify.com`
- Blog: `VALUTED NEWS`
- Blog GID: `gid://shopify/Blog/107387158765`

## Upload to GitHub
Extract this ZIP and upload its contents to the repository root, preserving folders. The key paths must be:
- `.github/workflows/news-collector.yml`
- `data/processed.json`
- `news_worker.py`
- `feeds.json`
- `requirements.txt`

If GitHub's upload interface does not show hidden folders, create `.github/workflows/news-collector.yml` through **Add file → Create new file** instead.

## Required GitHub Actions secrets
Repository → Settings → Secrets and variables → Actions → New repository secret:
- `SHOPIFY_STORE_DOMAIN` = `5xd8ae-md.myshopify.com` (the Shopify Admin API domain, not the public custom domain)
- `SHOPIFY_ADMIN_ACCESS_TOKEN` = a Shopify Admin API token with permission to create blog articles (recommended). The workflow can alternatively use `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET` if the app's client-credentials flow is enabled for this store.
- No paid news API or Vercel service is used. RSS feeds are free to fetch, subject to each publisher's terms.
- Do not publish unless the cited publisher page, image provenance, player availability, and editorial safety checks pass. Publisher RSS excerpts are attributed source material, not independent reporting. Confirm reuse permissions and copyright terms.

Never paste your Shopify token into chat or commit it into the repository.

## Required Actions variables
Repository → Settings → Secrets and variables → Actions → Variables:
- `SHOPIFY_API_VERSION` = `2026-10`
- `SHOPIFY_BLOG_ID` = `gid://shopify/Blog/107387158765`
- `AUTO_PUBLISH` = `true`
- `MAX_ARTICLES_PER_RUN` = `5`
- `ARCHIVE_RESTORE_PER_RUN` = `15` (the workflow default; up to 25 is supported)
- `MAX_AGE_HOURS` = `36`
- `MIN_WORDS_FOR_PUBLISH` = `180`
- `OPENAI_MODEL` = `gpt-4.1-mini`

## Run
The workflow runs three primary publishing windows daily (06:17, 12:17, and 18:17 UTC) plus recovery windows (07:47, 13:47, and 19:47 UTC). This is 08:17, 14:17, 20:17 and 09:47, 15:47, 21:47 Cairo time. It deduplicates by canonical source URL, skips stale entries, uses Google Trends as a ranking signal, and publishes only direct, attributed stories that pass every media and SEO gate. The historical archive is metadata-only for 202 old records; restoration is best-effort and cannot reconstruct missing original reporting. Verify the first successful publishing run and Shopify blog identity before relying on automatic publication. A scheduled workflow only runs when required repository secrets are configured.
