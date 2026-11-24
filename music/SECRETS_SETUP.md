# VALUTED MUSIC — Shopify app and GitHub credentials

This repository uses a Shopify Dev Dashboard custom app and Shopify's client credentials grant. It does not use a manually copied or permanent Admin API token.

## A. Create the Shopify app once

1. Open the VALUTED MUSIC Shopify admin: https://admin.shopify.com/store/0k31v6-th/settings/apps
2. Choose **Develop apps** → **Build apps in Dev Dashboard** → **Create app**.
3. Name it **VALUTED MUSIC Automation**.
4. Create an app version and request these Admin API scopes:
   - \`read_content\`
   - \`write_content\`
5. Release the version.
6. Install the app on the VALUTED MUSIC store and approve access.
7. In the app's **Settings → Credentials**, copy the **Client ID** and **Client secret**.

Important: the app and store must belong to the same Shopify organization for the client credentials grant. If Shopify returns \`shop_not_permitted\`, stop and confirm both are in the same organization; do not repeatedly retry.

## B. Run the Terminal setup

Requirements: macOS Terminal, Git, and GitHub CLI.

Install GitHub CLI if needed: https://cli.github.com/

Then run:

\`\`\`bash
git clone https://github.com/elsherbinyk10-netizen/VALUTED_NEWS_AUTOMATION.git
cd VALUTED_NEWS_AUTOMATION
git pull origin main
gh auth login
chmod +x scripts/setup_valuted_music_github_secrets.sh
./scripts/setup_valuted_music_github_secrets.sh
\`\`\`

The script asks for the Shopify Client ID, Client secret, YouTube Data API key, and optionally OpenAI API key. Secret input is hidden and piped directly to GitHub CLI. No credentials are written into the repository or a local file.

## C. What GitHub stores

Repository secrets:
- \`VALUTED_MUSIC_SHOPIFY_CLIENT_ID\`
- \`VALUTED_MUSIC_SHOPIFY_CLIENT_SECRET\`
- \`VALUTED_MUSIC_YOUTUBE_DATA_API_KEY\`
- \`OPENAI_API_KEY\` (required by the Music News workflow)

Repository variable:
- \`VALUTED_MUSIC_SHOPIFY_ADMIN_DOMAIN=0k31v6-th.myshopify.com\`

## D. Automatic token exchange

Before each scheduled Shopify job, \`music/shopify_auth.py\` exchanges the Client ID and Client secret at Shopify's \`/admin/oauth/access_token\` endpoint using \`grant_type=client_credentials\`. Shopify issues a short-lived token (typically 24 hours). The helper checks that \`read_content\` and \`write_content\` were granted and writes the token only to the current GitHub Actions job environment. It never prints the token.

## E. Verify

Open the repository's **Settings → Secrets and variables → Actions** and confirm the secret names exist. GitHub does not reveal secret values.

Then open **Actions** and inspect the workflow runs. A successful credential setup is not proof of publishing: verify the run logs and the resulting article in Shopify.

Schedules remain 9:00 PM video + SEO, 9:15 PM Music News, and 9:30 PM catalogue (Cairo time). Manual dispatch remains dry-run by default.
