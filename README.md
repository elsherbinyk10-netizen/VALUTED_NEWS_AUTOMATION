# Valuted News automated RSS → Shopify pipeline

This project replaces **Vercel** and the **GNews API** with a scheduled GitHub Actions worker that reads publisher RSS feeds and writes eligible stories to the existing Shopify **VALUTED NEWS** blog.

## Important operating defaults

- `AUTO_PUBLISH=false`: creates Shopify drafts until you explicitly enable publishing.
- No feed item is treated as independently verified just because an AI wrote about it.
- When `OPENAI_API_KEY` is missing, stories are held as drafts with an editorial-review note.
- The worker uses canonical source URLs to deduplicate and stores processing state in `data/processed.json`.
- Do not republish full RSS article text. The worker uses only title, short feed description and a source link.
- The included feeds are starter examples. Check each publisher's RSS terms and replace/add sources you are permitted to use.

## Shopify store already identified

- Store domain: `valutednews.com`
- Blog title: `VALUTED NEWS`
- Blog handle: `news`
- Blog GID: `gid://shopify/Blog/126010065175`

## 1. Put this folder in a private GitHub repository

Create a private repository such as `valuted-news-automation`, upload all files in this folder, and ensure the default branch is `main`. The workflow lives at `.github/workflows/news-collector.yml`.

## 2. Create a Shopify Admin API credential

Create or configure a Shopify custom app with the minimum content scopes required to create blog articles (typically `write_content`; Shopify may also require `read_content` for your app setup). Install the app and copy its Admin API access token once. **Never paste the token into this README, a theme, a chat, or a committed file.**

In GitHub → repository → Settings → Secrets and variables → Actions, add repository secrets:

- `SHOPIFY_STORE_DOMAIN` = `valutednews.com`
- `SHOPIFY_ADMIN_ACCESS_TOKEN` = your Admin API token
- `OPENAI_API_KEY` = optional; required for AI-generated draft article text

Add Actions variables:

- `SHOPIFY_API_VERSION` = `2026-10`
- `SHOPIFY_BLOG_ID` = `gid://shopify/Blog/126010065175`
- `AUTO_PUBLISH` = `false`
- `MAX_ARTICLES_PER_RUN` = `3`
- `MAX_AGE_HOURS` = `36`
- `MIN_WORDS_FOR_PUBLISH` = `180`
- `OPENAI_MODEL` = `gpt-4.1-mini`

If you do not configure the optional OpenAI key, the pipeline intentionally holds items as review drafts rather than pretending it has created original reporting.

## 3. Run a safe first test

1. Keep `AUTO_PUBLISH=false`.
2. In GitHub → Actions → **Valuted News RSS Automation**, choose **Run workflow**.
3. Review the workflow logs and Shopify blog drafts.
4. Check source links, titles, tags, and how the theme renders each article.
5. Only after testing should you change `AUTO_PUBLISH` to `true`.

## 4. What runs automatically

The workflow is scheduled at minutes 17 and 47 of every UTC hour. GitHub Actions schedules can be delayed during heavy load, so this is periodic automation, not a guaranteed real-time breaking-news wire. Manual runs are also supported.

Each run:
1. Fetches configured RSS feeds.
2. Normalizes URLs and checks duplicates.
3. Rejects stale items and malformed entries.
4. Applies conservative risk checks.
5. Creates an original, source-attributed draft using the optional model, or a review-only draft if no model key exists.
6. Creates Shopify drafts by default; automatic publication is gated by environment variables and risk/quality checks.
7. Saves state and logs each outcome.

## 5. Safeguards and limitations

- The AI can make mistakes. High-impact or sensitive stories are held for review.
- This is a starter implementation, not a substitute for newsroom fact-checking or legal review.
- Never auto-publish allegations, unverified breaking events, private personal information, medical/financial advice, or content whose source permissions are unclear.
- Feed URLs and terms change; monitor failures and update `feeds.json`.
- GitHub Actions is not a database. The JSON state file is suitable for a small starter pipeline, but a production newsroom should use a durable database and alerting.
- To avoid accidental mass publication, the worker caps each run at three articles by default.

## Local smoke test

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill values locally; never commit .env
python news_worker.py --dry-run
```

`--dry-run` reads feeds and reports candidate items without writing to Shopify.
