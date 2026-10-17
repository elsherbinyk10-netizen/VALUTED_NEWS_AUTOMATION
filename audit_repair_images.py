"""Find published articles with absent, placeholder, or suspiciously reused featured art and repair them.

This script deliberately errs on the side of review: it only requeues clear failures
(missing/generic image, dead image URL, or one identical image used for unrelated
headlines). It does not replace an image solely because an automated text score is low.
"""
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from urllib.parse import urlparse

import requests

import backfill_media

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
HEADERS = {"User-Agent": "ValutedNewsImageAudit/1.0"}


def image_url_ok(url):
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        response = requests.get(url, headers=HEADERS, stream=True, timeout=(4, 8), allow_redirects=True)
        try:
            return response.ok and response.headers.get("Content-Type", "").lower().startswith("image/")
        finally:
            response.close()
    except requests.RequestException:
        return False


def normalized_title(title):
    return " ".join(re.findall(r"[a-z0-9]+", (title or "").lower()))


def main():
    articles = backfill_media.list_articles()
    published = [a for a in articles if a.get("isPublished")]
    by_image = defaultdict(list)
    for article in published:
        image = article.get("image") or {}
        url = str(image.get("url") or "")
        if url:
            parsed = urlparse(url)
            identity = (parsed.hostname or "").lower() + parsed.path
            by_image[identity].append(article)

    # Check URLs concurrently to keep the daily run within the GitHub Actions time budget.
    urls = list({str((a.get("image") or {}).get("url") or "") for a in published if (a.get("image") or {}).get("url")})
    with ThreadPoolExecutor(max_workers=12) as pool:
        url_health = dict(zip(urls, pool.map(image_url_ok, urls)))

    flagged = {}
    for article in published:
        image = article.get("image") or {}
        url = str(image.get("url") or "")
        alt = str(image.get("altText") or "")
        combined = (url + " " + alt).lower()
        reason = None
        if not url or any(term in combined for term in (
            "google news", "google-news", "google_news", "valuted news", "valuted-news",
            "valuted_news", "placeholder", "default-thumbnail", "generic poster", "favicon"
        )):
            reason = "missing-or-placeholder"
        elif not url_health.get(url, False):
            reason = "image-url-unavailable-or-not-image"
        else:
            parsed = urlparse(url)
            identity = (parsed.hostname or "").lower() + parsed.path
            siblings = by_image[identity]
            unique_titles = {normalized_title(x.get("title")) for x in siblings}
            # Only flag an asset reused for three or more distinct headlines.
            if len(siblings) >= 3 and len(unique_titles) >= 3:
                reason = "same-image-reused-across-unrelated-headlines"
        if reason:
            flagged[article["id"]] = (article, reason)

    logging.info("Image audit: published=%d flagged=%d", len(published), len(flagged))
    for article, reason in flagged.values():
        logging.warning("Flagged (%s): %s", reason, article.get("title", "(untitled)"))

    if not flagged:
        logging.info("No obvious image failures detected.")
        return

    # Reuse the existing source-metadata/licensed-Commons repair logic for only flagged rows.
    targeted = []
    for article, reason in flagged.values():
        row = dict(article)
        row["image"] = None
        targeted.append(row)
    original_list_articles = backfill_media.list_articles
    try:
        backfill_media.list_articles = lambda: targeted
        os.environ["MEDIA_BACKFILL_LIMIT"] = str(min(20, max(1, len(targeted))))
        backfill_media.main()
    finally:
        backfill_media.list_articles = original_list_articles


if __name__ == "__main__":
    main()
