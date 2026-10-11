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
- `SHOPIFY_ADMIN_ACCESS_TOKEN` = your Shopify Admin API token
- `OPENAI_API_KEY` = optional; if omitted, articles stay review-only drafts

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
After adding the secrets and variables, open Actions → **Valuted News RSS Automation** → Run workflow. Confirm Shopify drafts appear before considering any change to publishing behavior.
