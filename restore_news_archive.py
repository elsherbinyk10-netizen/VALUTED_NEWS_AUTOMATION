"""Rebuild missing Valuted News archive entries from saved publishing records.

Only restore a story when its original RSS entry is still available, the publisher page
confirms a story-specific high-resolution image, and a relevant public video embed
passes the same playback gate used by the daily publisher. No article body is invented
or copied wholesale from the publisher page. Unrecoverable items remain in the report.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import news_worker as worker
from publisher_image_policy import verify_publisher_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data" / "processed.json"
FEEDS_FILE = ROOT / "feeds.json"


def load_rss_index():
    """Index current RSS excerpts by canonical publisher URL; never scrape full article text."""
    feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    index = {}
    for feed in feeds:
        try:
            parsed = worker.feedparser.parse(feed["url"])
            for entry in parsed.entries:
                url = worker.canonical_url(entry.get("link") or "")
                if not url:
                    continue
                text = worker.extract_entry_text(entry)
                if text:
                    index[url] = {
                        "text": text,
                        "publisher": feed.get("name", "Original publisher"),
                        "category": feed.get("category", "World"),
                        "published": entry.get("published") or entry.get("updated") or "",
                    }
        except Exception:
            logging.exception("Unable to read archive source feed: %s", feed.get("name"))
    return index


def publisher_html(url):
    response = worker.requests.get(
        url,
        headers={"User-Agent": "VALUTED-News-Archive-Restore/1.0", "Accept": "text/html,application/xhtml+xml"},
        timeout=(5, 12),
        allow_redirects=True,
    )
    try:
        if not response.ok or "html" not in response.headers.get("Content-Type", "").lower():
            return ""
        return response.text
    finally:
        response.close()


def main():
    blog_id = worker.env("SHOPIFY_BLOG_ID")
    if not blog_id:
        raise RuntimeError("Missing SHOPIFY_BLOG_ID; refusing to restore to an unknown blog.")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    records = state.get("items")
    if not isinstance(records, dict):
        raise RuntimeError("processed.json has no valid items map.")
    feed_index = load_rss_index()
    existing_titles, existing_sources, related_articles = worker.load_existing_shopify_story_index(blog_id)
    limit = max(1, min(25, int(worker.env("ARCHIVE_RESTORE_PER_RUN", "15"))))
    restored = skipped = failed = 0
    now = datetime.now(timezone.utc)

    candidates = sorted(
        ((key, value) for key, value in records.items()
         if value.get("status") == "published" and not value.get("restored_shopify_article_id")),
        key=lambda pair: str(pair[1].get("created_at") or ""),
    )
    logging.info("Archive restore inventory: %d historical published records; this run limit=%d",
                 len(candidates), limit)

    for key, record in candidates:
        if restored >= limit:
            break
        title = worker.clean_text(record.get("title") or "")
        source_url = worker.canonical_url(record.get("source_url") or "")
        if not title or not source_url or record.get("risk_flag"):
            record["restore_status"] = "blocked_missing_metadata_or_high_risk"
            record["restore_attempted_at"] = now.isoformat()
            skipped += 1
            continue

        source = feed_index.get(source_url)
        if not source:
            record["restore_status"] = "blocked_original_rss_excerpt_unavailable"
            record["restore_attempted_at"] = now.isoformat()
            skipped += 1
            logging.warning("Cannot safely reconstruct source text from RSS: %s", title)
            continue

        description = worker.clean_text(source.get("text") or "")
        if len(description.split()) < 120 or len(description) < 800:
            record["restore_status"] = "blocked_insufficient_recoverable_source_text"
            record["restore_attempted_at"] = now.isoformat()
            skipped += 1
            logging.warning("Insufficient recoverable RSS text; not inventing article copy: %s", title)
            continue

        if worker.normalized_story_title(title) in existing_titles or source_url in existing_sources:
            record["restore_status"] = "already_present_in_shopify"
            record["restore_attempted_at"] = now.isoformat()
            skipped += 1
            continue

        try:
            markup = publisher_html(source_url)
            if not markup:
                raise ValueError("original publisher page is unavailable")
            media = worker.fetch_article_media(source_url)
            image_url = media.get("image_url") or ""
            if not image_url:
                raise ValueError("no publisher-declared featured image was recoverable")
            image_check = verify_publisher_image(
                source_url, markup, title, image_url,
                article_published_at=record.get("created_at"),
            )
            if not image_check.get("ok"):
                raise ValueError("publisher image provenance check failed: " + str(image_check.get("reason")))

            video_html = media.get("video_html") or ""
            if not video_html:
                video_html = worker.fetch_related_youtube_embed(
                    title, source.get("category", "World")
                )
            if not video_html or not worker.video_embed_is_available(video_html):
                raise ValueError("no relevant, playable public embedded video was verified")

            category = worker.classify_story_category(title, description, source.get("category", "World"))
            publisher = worker.clean_text(record.get("publisher") or source.get("publisher") or "Original publisher")
            published_at = record.get("created_at") or source.get("published") or None
            body_summary = worker.normalize_article_summary(description, title)
            body = worker.make_public_news_brief(
                title, publisher, category, description, source_url,
                image_url, video_html, related_articles, published_at,
            )
            created = worker.create_shopify_article(
                blog_id, title, body_summary, body, source_url, publisher,
                category, True, image_url, publish_date=published_at,
            )
            if not created or not created.get("id") or not created.get("isPublished"):
                raise RuntimeError("Shopify did not confirm a published restored article.")

            record["restored_shopify_article_id"] = created["id"]
            record["restored_handle"] = created.get("handle")
            record["restored_at"] = now.isoformat()
            record["restore_status"] = "restored_and_verified"
            existing_titles.add(worker.normalized_story_title(title))
            existing_sources.add(source_url)
            if created.get("handle"):
                related_articles.append({
                    "title": title, "body": body,
                    "url": "https://valutednews.com/blogs/news/" + created["handle"],
                })
            restored += 1
            logging.info("RESTORED %s | %s | image=verified | video=verified",
                         title, created.get("handle"))
            time.sleep(0.5)
        except Exception as error:
            record["restore_status"] = "retryable_blocker"
            record["restore_error"] = str(error)[:500]
            record["restore_attempted_at"] = now.isoformat()
            failed += 1
            logging.exception("Archive restore blocked for: %s", title)

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                          encoding="utf-8")
    remaining = sum(
        1 for value in records.values()
        if value.get("status") == "published" and not value.get("restored_shopify_article_id")
        and value.get("restore_status") != "already_present_in_shopify"
    )
    logging.info(
        "ARCHIVE RESTORE REPORT: restored=%d skipped=%d failed=%d remaining=%d total_historical_published=%d",
        restored, skipped, failed, remaining,
        sum(1 for value in records.values() if value.get("status") == "published"),
    )


if __name__ == "__main__":
    main()
