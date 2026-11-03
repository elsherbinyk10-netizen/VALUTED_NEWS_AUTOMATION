"""Find published articles with absent, placeholder, or suspiciously reused featured art.

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
from image_quality import inspect_image_url
from publisher_image_policy import verify_publisher_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
HEADERS = {"User-Agent": "ValutedNewsImageAudit/1.0"}


def image_url_ok(url):
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    return inspect_image_url(url).get("ok", False)


def normalized_title(title):
    return " ".join(re.findall(r"[a-z0-9]+", (title or "").lower()))


def normalized_image_identity(url):
    """Collapse CDN resize and random UUID suffixes to detect reused source artwork."""
    parsed = urlparse(url or "")
    basename = parsed.path.rsplit("/", 1)[-1]
    basename = re.sub(r"_s0-w[0-9]+", "", basename, flags=re.I)
    basename = re.sub(r"_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)", "", basename, flags=re.I)
    return (parsed.hostname or "").lower() + "/" + basename if basename else ""


def main():
    articles = backfill_media.list_articles()
    audited = articles
    by_image = defaultdict(list)
    for article in audited:
        image = article.get("image") or {}
        url = str(image.get("url") or "")
        if url:
            identity = normalized_image_identity(url)
            by_image[identity].append(article)

    # Check URLs concurrently to keep the daily run within the GitHub Actions time budget.
    urls = list({str((a.get("image") or {}).get("url") or "") for a in audited if (a.get("image") or {}).get("url")})
    with ThreadPoolExecutor(max_workers=12) as pool:
        url_health = dict(zip(urls, pool.map(image_url_ok, urls)))

    flagged = {}
    for article in audited:
        image = article.get("image") or {}
        url = str(image.get("url") or "")
        alt = str(image.get("altText") or "")
        combined = (url + " " + alt).lower()
        reason = None
        if url and not reason:
            # Existing large images are not automatically trusted: re-check the cited
            # publisher page, title match, publication/update date and exact declared image.
            for source_url in list(backfill_media.source_urls(article.get("body", "")))[:3]:
                try:
                    page = requests.get(source_url, headers={**HEADERS, "Accept": "text/html"},
                                        timeout=(5, 12), allow_redirects=True)
                    try:
                        if not page.ok or "html" not in page.headers.get("Content-Type", "").lower():
                            continue
                        verdict = verify_publisher_image(
                            page.url, page.text, article.get("title", ""), url,
                            article.get("publishedAt"), article.get("updatedAt"),
                        )
                    finally:
                        page.close()
                    if verdict.get("ok"):
                        break
                    reason = "publisher-provenance-or-freshness-failed: " + verdict.get("reason", "unknown")
                except requests.RequestException:
                    reason = "publisher-page-verification-failed"
            else:
                reason = reason or "original-publisher-source-not-found"
        if not url or any(term in combined for term in (
            "google news", "google-news", "google_news", "valuted news", "valuted-news",
            "valuted_news", "placeholder", "default-thumbnail", "generic poster", "favicon"
        )):
            reason = "missing-or-placeholder"
        elif not url_health.get(url, False):
            quality = inspect_image_url(url)
            reason = "low-resolution-or-invalid-image: " + str(quality.get("reason", "unknown"))
        else:
            identity = normalized_image_identity(url)
            siblings = by_image[identity]
            unique_titles = {normalized_title(x.get("title")) for x in siblings}
            # Only flag an asset reused for three or more distinct headlines.
            if len(siblings) >= 3 and len(unique_titles) >= 3:
                reason = "same-image-reused-across-unrelated-headlines"
        if reason:
            flagged[article["id"]] = (article, reason)

    logging.info("Image audit: articles (published + drafts)=%d flagged=%d", len(audited), len(flagged))
    for article, reason in flagged.values():
        logging.warning("Flagged (%s): %s", reason, article.get("title", "(untitled)"))

    if not flagged:
        logging.info("No obvious image failures detected.")
        return

    # Requeue only candidates through the strict publisher-only repair path.
    # The backfill worker has a 100-article per-run cap. Prioritize verified
    # image-quality failures first so older low-resolution images are not starved
    # behind unrelated provenance warnings on newer articles.
    prioritized = sorted(
        flagged.values(),
        key=lambda item: (
            0 if item[1].startswith("low-resolution-or-invalid-image:") else 1,
            str(item[0].get("title", "")).casefold(),
        ),
    )
    targeted = []
    for article, reason in prioritized:
        row = dict(article)
        row["image"] = None
        targeted.append(row)
    original_list_articles = backfill_media.list_articles
    try:
        backfill_media.list_articles = lambda: targeted
        os.environ["MEDIA_BACKFILL_LIMIT"] = str(min(100, max(1, len(targeted))))
        backfill_media.main()
    finally:
        backfill_media.list_articles = original_list_articles


if __name__ == "__main__":
    main()
