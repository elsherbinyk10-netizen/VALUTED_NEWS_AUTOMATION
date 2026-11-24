#!/usr/bin/env bash
set -Eeuo pipefail

REPO="elsherbinyk10-netizen/VALUTED_NEWS_AUTOMATION"
SHOP_DOMAIN="0k31v6-th.myshopify.com"

command -v gh >/dev/null 2>&1 || {
  echo "ERROR: GitHub CLI (gh) is not installed. Install it from https://cli.github.com/ and rerun."
  exit 1
}
gh auth status >/dev/null 2>&1 || {
  echo "ERROR: Sign in first: gh auth login"
  exit 1
}

echo "VALUTED MUSIC — GitHub Actions credential setup"
echo "Repository: $REPO"
echo "Shopify store: $SHOP_DOMAIN"
echo
echo "Secret values are entered invisibly and sent directly to GitHub."
echo "They are not written to files or printed in the terminal."
echo

set_secret() {
  local name="$1"
  local prompt="$2"
  local value=""
  while [[ -z "$value" ]]; do
    read -r -s -p "$prompt: " value
    printf '\n'
    if [[ -z "$value" ]]; then
      echo "This credential is required; please try again."
    fi
  done
  printf '%s' "$value" | gh secret set "$name" --repo "$REPO"
  unset value
  echo "Saved secret: $name"
}

set_secret "VALUTED_MUSIC_SHOPIFY_ADMIN_ACCESS_TOKEN" "Paste Shopify Admin API access token"
set_secret "VALUTED_MUSIC_YOUTUBE_DATA_API_KEY" "Paste Google YouTube Data API key"

echo
echo "The Music News workflow also needs OPENAI_API_KEY."
echo "If you skip it, video and catalogue workflows can still run, but the news workflow will not authenticate."
read -r -s -p "Paste OpenAI API key (press Enter to skip): " openai_key
printf '\n'
if [[ -n "$openai_key" ]]; then
  printf '%s' "$openai_key" | gh secret set "OPENAI_API_KEY" --repo "$REPO"
  echo "Saved secret: OPENAI_API_KEY"
else
  echo "Skipped OPENAI_API_KEY. Daily Music News will need this before it can run."
fi
unset openai_key

gh variable set "VALUTED_MUSIC_SHOPIFY_ADMIN_DOMAIN" --repo "$REPO" --body "$SHOP_DOMAIN"
echo "Saved repository variable: VALUTED_MUSIC_SHOPIFY_ADMIN_DOMAIN"

echo
echo "Checking configured secret names (GitHub never reveals secret values):"
gh secret list --repo "$REPO"
echo
echo "Repository variable:"
gh variable list --repo "$REPO"
echo
echo "Setup command completed. This confirms names were saved, not that credentials have been tested against Shopify or Google."
