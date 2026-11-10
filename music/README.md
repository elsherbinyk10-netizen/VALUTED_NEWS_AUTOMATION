# VALUTED MUSIC daily publishing

This is a separately configured workflow in the GitHub account. It does not reuse VALUTED NEWS's Shopify token.

## Target and schedule
- Store display name must equal `VALUTED MUSIC` (case-insensitive exact match).
- Shopify primary-domain host must equal `valutedmusic.site` (exact match).
- Existing Shopify blog handle: `news`.
- Daily schedule: 21:00 Cairo time (19:00 UTC); manual dispatch is also available.
- Maximum five articles per run; zero is an acceptable result.

## Mandatory GitHub Actions secrets
Repository → Settings → Secrets and variables → Actions:
- `VALUTED_MUSIC_SHOPIFY_ADMIN_ACCESS_TOKEN`: Shopify Admin API token for the VALUTED MUSIC shop only, with `read_content` and `write_content` scopes.
- `OPENAI_API_KEY`: used only to draft original copy from the retrieved live publisher page text.

Never put tokens in source files, workflow YAML, issues, or chat. Do not reuse the VALUTED NEWS store token.

## Safety behavior
1. Before any Shopify article write, query the shop identity, exact primary domain, themes and blogs.
2. If the shop name or domain differs, log exactly `WRONG SHOP CONNECTED — NO CHANGES MADE.` and exit without writing.
3. Record the single MAIN theme name, ID and role. No theme, design, app, billing, domain, navigation, locale or storefront mutations are implemented.
4. Read direct publisher pages from the configured RSS discovery feeds. Redirects and canonical URLs must remain on the approved publisher allowlist. Pages must contain sufficient live article text and be recent (36 hours by default).
5. Drafting is constrained to the live page text. Canonical source URL attribution is mandatory. Duplicate source URLs are checked before each write.
6. After each article creation, re-query Shopify and verify title, handle, publication status, body/source, tags, SEO title/description and target blog. Verification failures stop the run; the script never blindly retries an article creation.
7. No video is embedded by this initial release. It publishes source-linked news only; it does not claim any video is official or playable. This avoids fabricated IDs and unverified channel attribution.
8. English is the only generated language in this initial release. Arabic translation is not claimed or auto-published.
9. The worker never modifies Shopify themes or storefront settings.

## Important setup
The workflow is committed but cannot publish until both secrets above are configured in GitHub. Confirm that the token belongs to the VALUTED MUSIC shop before adding it. Run the workflow manually only after the correct secret is installed; its first action is the hard identity guard.
