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


def safe_diagnostic(raw: bytes, client_id: str, client_secret: str) -> str:
    """Return Shopify's useful error code without leaking credentials or tokens."""
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, TypeError):
        return "Shopify returned a non-JSON error response."
    if not isinstance(payload, dict):
        return "Shopify returned an unrecognized error response."
    code = payload.get("error")
    if isinstance(code, dict):
        code = code.get("message") or code.get("code")
    description = payload.get("error_description") or payload.get("error_description_hint")
    if not isinstance(code, str):
        code = "unknown_error"
    parts = [code]
    if isinstance(description, str) and description.strip():
        parts.append(description.strip())
    value = "; description=".join(parts)
    for secret in (client_id, client_secret):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"shpat_[A-Za-z0-9]+|shpca_[A-Za-z0-9]+|access_token[^,}]*", "[REDACTED]", value, flags=re.I)
    return value[:500]


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
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read(8192)
        request_id = exc.headers.get("x-request-id", "not supplied")
        diagnostic = safe_diagnostic(body, client_id, client_secret)
        fail(f"Shopify returned HTTP {exc.code}; error={diagnostic}; request_id={request_id}. Verify the Client ID/secret from this app's Dev Dashboard Settings.")
    except (urllib.error.URLError, TimeoutError):
        fail("Could not reach Shopify token endpoint. Check network and try again.")
    except (json.JSONDecodeError, UnicodeDecodeError):
        fail("Shopify returned an unreadable token response.")

    token = data.get("access_token")
    scopes = {scope.strip() for scope in (data.get("scope") or "").split(",") if scope.strip()}
    if not isinstance(token, str) or not token:
        fail("Shopify response did not contain an access token.")
    if "write_content" not in scopes:
        fail("The installed app is missing the required write_content scope.")

    # Register the dynamically issued token with the Actions log masker before it enters later-step env output.
    print(f"::add-mask::{token}", flush=True)

    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        fail("GITHUB_ENV is not set. Run this helper inside a GitHub Actions step.")
    with open(github_env, "a", encoding="utf-8") as env_file:
        env_file.write(f"SHOPIFY_ADMIN_ACCESS_TOKEN={token}\n")
    print("Shopify authentication succeeded; a short-lived token is ready for the next workflow step.")
    print("Granted content scope verified: write_content (includes content read access).")
    print(f"Token lifetime reported by Shopify: {data.get('expires_in', 'not supplied')} seconds.")


if __name__ == "__main__":
    main()
