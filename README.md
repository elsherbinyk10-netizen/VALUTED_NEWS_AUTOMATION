# Valuted News RSS → Shopify automation

This folder is arranged with the correct GitHub Actions workflow and state-file paths.

## Safety defaults
- `AUTO_PUBLISH=false`: creates Shopify drafts, not live posts.
- Keep stories in draft until a human checks the facts, source link, headline, and article body.
- Starter RSS feeds are examples; verify publisher terms and permitted use.
- The optional OpenAI key is stored only as a GitHub Actions secret, never in files.

## Shopify details
- Store domain: `valutednews.com`
- Blog: `VALUTED NEWS`
- Blog GID: `gid://shopify/Blog/126010065175`

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
- `SHOPIFY_STORE_DOMAIN` = `valutednews.com`
- `SHOPIFY_ADMIN_ACCESS_TOKEN` = a Shopify Admin API token with permission to create blog articles (recommended). The workflow can alternatively use `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET` if the app's client-credentials flow is enabled for this store.
- No paid news API or Vercel service is used. RSS feeds are free to fetch, subject to each publisher's terms.
- Article creation remains draft-only; RSS summaries are not full independent reporting. Add or verify image rights before publishing.

Never paste your Shopify token into chat or commit it into the repository.

## Required Actions variables
Repository → Settings → Secrets and variables → Actions → Variables:
- `SHOPIFY_API_VERSION` = `2026-10`
- `SHOPIFY_BLOG_ID` = `gid://shopify/Blog/126010065175`
- `AUTO_PUBLISH` = `false`
- `MAX_ARTICLES_PER_RUN` = `3`
- `MAX_AGE_HOURS` = `36`
- `MIN_WORDS_FOR_PUBLISH` = `180`
- `OPENAI_MODEL` = `gpt-4.1-mini`

## Run
The workflow is scheduled three times daily (06:17, 12:17, and 18:17 UTC) and can also be started from Actions → **Valuted News RSS Automation** → Run workflow. It deduplicates by canonical source URL, skips old feed entries, and creates Shopify review drafts. Confirm the first run succeeds and check the draft article image/source before considering publication. A scheduled workflow only runs when required repository secrets are configured.
