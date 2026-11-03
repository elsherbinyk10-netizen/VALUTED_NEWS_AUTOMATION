"""Find published articles with absent, placeholder, or suspiciously reused featured art.

This script deliberately errs on the side of review: it only requeues clear failures
(missing/generic image, dead image URL, or one identical image used for unrelated
headlines). It does not replace an image solely because an automated text score is low.
"""
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from urllib.parse import urlparse


import backfill_media
from image_quality import inspect_image_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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
        # Existing-image provenance checks were causing hundreds of unnecessary
        # publisher-page fetches. Only flag concrete image defects here; any
        # replacement is independently verified against the cited publisher in
        # backfill_media.py before Shopify is updated.
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
    def is_critical_low_resolution(article, reason):
        image = article.get("image") or {}
        return (
            reason.startswith("low-resolution-or-invalid-image:")
            and ((image.get("width") or 0) < 500 or (image.get("height") or 0) < 300)
        )

    prioritized = sorted(
        flagged.values(),
        key=lambda item: (
            0 if is_critical_low_resolution(item[0], item[1]) else
            1 if item[1].startswith("low-resolution-or-invalid-image:") else 2,
            str(item[0].get("title", "")).casefold(),
        ),
    )
    critical_ids = {
        article["id"] for article, reason in prioritized
        if is_critical_low_resolution(article, reason)
    }
    targeted = []
    for article, reason in prioritized:
        row = dict(article)
        row["image"] = None
        targeted.append(row)
    original_list_articles = backfill_media.list_articles
    previous_excluded = os.environ.get("EXCLUDED_IMAGE_IDENTITIES")
    try:
        backfill_media.list_articles = lambda: targeted
        # Preserve the full-store no-reuse guard even though the backfill receives
        # only the selected repair candidates.
        existing_identities = {
            backfill_media.normalized_image_identity(str((article.get("image") or {}).get("url") or ""))
            for article in audited if (article.get("image") or {}).get("url")
        }
        os.environ["EXCLUDED_IMAGE_IDENTITIES"] = json.dumps(sorted(x for x in existing_identities if x))
        os.environ["MEDIA_BACKFILL_LIMIT"] = str(min(100, max(1, len(targeted))))
        backfill_media.main()
    finally:
        backfill_media.list_articles = original_list_articles
        if previous_excluded is None:
            os.environ.pop("EXCLUDED_IMAGE_IDENTITIES", None)
        else:
            os.environ["EXCLUDED_IMAGE_IDENTITIES"] = previous_excluded

    if critical_ids:
        refreshed = original_list_articles()
        refreshed_by_id = {article.get("id"): article for article in refreshed}
        unresolved_critical = []
        for article_id in critical_ids:
            current = refreshed_by_id.get(article_id) or {}
            image = current.get("image") or {}
            if not image.get("url") or (image.get("width") or 0) < 500 or (image.get("height") or 0) < 300:
                unresolved_critical.append(current.get("title") or article_id)
        if unresolved_critical:
            raise RuntimeError(
                "Critical low-resolution featured images remain after repair: "
                + " | ".join(unresolved_critical)
            )
        logging.info("Critical low-resolution image post-check passed for %d articles.", len(critical_ids))


if __name__ == "__main__":
    main()
