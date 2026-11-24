#!/usr/bin/env python3
"""Exchange Shopify Dev Dashboard app credentials for a short-lived Admin API token.

Intended for GitHub Actions. The token is written only to GITHUB_ENV and is
never printed. Shopify client-credentials tokens expire; request one per run.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


def fail(message: str) -> None:
    print(f"Shopify authentication failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    domain = os.environ.get("SHOPIFY_ADMIN_DOMAIN", "").strip().lower()
    client_id = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", domain):
        fail("SHOPIFY_ADMIN_DOMAIN must be a valid *.myshopify.com host.")
    if not client_id or not client_secret:
        fail("Set SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET in the environment.")

    endpoint = f"https://{domain}/admin/oauth/access_token"
    payload = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not print response body: it may contain provider diagnostics.
        fail(f"Shopify returned HTTP {exc.code}. Check app installation, organization, and credentials.")
    except (urllib.error.URLError, TimeoutError):
        fail("Could not reach Shopify token endpoint. Check network and try again.")
    except (json.JSONDecodeError, UnicodeDecodeError):
        fail("Shopify returned an unreadable token response.")

    token = data.get("access_token")
    scopes = set((data.get("scope") or "").split(","))
    required = {"read_content", "write_content"}
    missing = required - scopes
    if not isinstance(token, str) or not token:
        fail("Shopify response did not contain an access token.")
    if missing:
        fail("The installed app is missing required scopes: " + ", ".join(sorted(missing)))

    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        fail("GITHUB_ENV is not set. Run this helper inside a GitHub Actions step.")
    with open(github_env, "a", encoding="utf-8") as env_file:
        env_file.write(f"SHOPIFY_ADMIN_ACCESS_TOKEN={token}\n")
    print("Shopify authentication succeeded; a short-lived token is ready for the next workflow step.")
    print(f"Granted content scopes verified: {', '.join(sorted(required))}.")
    print(f"Token lifetime reported by Shopify: {data.get('expires_in', 'not supplied')} seconds.")


if __name__ == "__main__":
    main()
