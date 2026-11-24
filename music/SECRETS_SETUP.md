# VALUTED MUSIC — GitHub Actions credentials

This setup configures the repository secrets used by the three scheduled VALUTED MUSIC workflows. It does not create Shopify or Google credentials; create those in their official dashboards first.

## Run from Terminal (macOS)

1. Install GitHub CLI: https://cli.github.com/
2. Authenticate with repository access:
   `gh auth login`
3. Download the repository and run the setup:

```bash
git clone https://github.com/elsherbinyk10-netizen/VALUTED_NEWS_AUTOMATION.git
cd VALUTED_NEWS_AUTOMATION
git pull origin main
chmod +x scripts/setup_valuted_music_github_secrets.sh
./scripts/setup_valuted_music_github_secrets.sh
```

The script asks for credentials using hidden terminal input and pipes them directly to `gh secret set`. It does not save credentials in a local file or print them.

## Credentials to create

### 1. Shopify Admin API token — required

In Shopify Admin for `0k31v6-th.myshopify.com`, open **Settings → Apps → Develop apps**. Create/install a custom app with Admin API scopes:

- `read_content`
- `write_content`

Generate an Admin API access token. Enter it when the script asks for `VALUTED_MUSIC_SHOPIFY_ADMIN_ACCESS_TOKEN`.

Use only the VALUTED MUSIC store's token. Never commit it, paste it into chat, or put it in a shell command argument.

### 2. YouTube Data API key — required for official-video checks

In Google Cloud Console, create/select a project, enable **YouTube Data API v3**, and create an API key. Restrict the key to YouTube Data API v3 where practical. Enter it for `VALUTED_MUSIC_YOUTUBE_DATA_API_KEY`.

### 3. OpenAI API key — required for Music News

Create an API key in the OpenAI Platform dashboard and enter it when prompted. API usage is billed separately from a ChatGPT subscription. If skipped, the daily Music News workflow cannot authenticate and will not publish.

## What the script configures

- Repository secret: `VALUTED_MUSIC_SHOPIFY_ADMIN_ACCESS_TOKEN`
- Repository secret: `VALUTED_MUSIC_YOUTUBE_DATA_API_KEY`
- Repository secret: `OPENAI_API_KEY` (optional in the script, required by the News workflow)
- Repository variable: `VALUTED_MUSIC_SHOPIFY_ADMIN_DOMAIN=0k31v6-th.myshopify.com`

The script prints only secret names, never secret values. GitHub does not allow reading secret values back; `gh secret list` verifies only that names exist.

## After setup

Open the repository's **Actions** tab and inspect the next scheduled runs. A successful setup command is not proof of a successful Shopify publish. Verify the workflow run logs and the published article in Shopify.

The scheduled workflows are configured for 9:00 PM, 9:15 PM, and 9:30 PM Cairo time. Manual dispatch defaults to dry-run; do not enable publishing manually until the credentials and first live run are verified.
