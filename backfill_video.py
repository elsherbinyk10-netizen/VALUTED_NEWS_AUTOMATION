"""Verify and repair live Valuted News videos against each article's cited publisher.

Only videos present on the cited publisher page and whose player endpoint responds with
valid metadata are embedded. Stale/unrelated embeds are removed after a successful
publisher-page check; inaccessible source pages are left untouched for safety.
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from news_worker import env, shopify_graphql, fetch_article_media, video_embed_is_available

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BLOG_ID = env("SHOPIFY_BLOG_ID", "gid://shopify/Blog/126010065175")
STATE_FILE = Path("data/video_backfill.json")


def load_state():
    try:
        data = json.loads(STATE_FILE.read_text())
        return data if isinstance(data, dict) else {"attempted": {}}
    except (OSError, json.JSONDecodeError):
        return {"attempted": {}}


def list_articles():
    query = """
    query PublishedArticlesForVideoBackfill($id: ID!, $after: String) {
      blog(id: $id) {
        articles(first: 250, reverse: true, after: $after) {
          nodes { id title handle body isPublished tags }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """
    articles = []
    cursor = None
    while True:
        data = shopify_graphql(query, {"id": BLOG_ID, "after": cursor})
        connection = (data.get("blog") or {}).get("articles", {})
        articles.extend(connection.get("nodes", []))
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            break
        cursor = page_info["endCursor"]
    return [article for article in articles if article.get("isPublished")]


def primary_source_url(body):
    """Return only the explicit source link, never an internal related-story link."""
    match = re.search(
        r'<p[^>]*>\s*<strong>Source:</strong>[\s\S]*?<a[^>]+href=["\']([^"\']+)["\']',
        body or "",
        re.I,
    )
    if not match:
        return ""
    url = match.group(1).replace("&amp;", "&")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return url


def remove_related_video(body):
    """Remove only the article's designated Related video block, preserving story text."""
    original = body or ""
    cleaned = re.sub(
        r'<section\b[^>]*class=["\'][^"\']*vn-related-video[^"\']*["\'][^>]*>[\s\S]*?</section>',
        "",
        original,
        flags=re.I,
    )
    cleaned = re.sub(
        r'<h2\b[^>]*>\s*Related video\s*</h2>\s*'
        r'(?:<div\b[^>]*class=["\'][^"\']*valuted-news-video[^"\']*["\'][^>]*>[\s\S]*?</div>'
        r'|<video\b[\s\S]*?</video>)',
        "",
        cleaned,
        flags=re.I,
    )
    return cleaned


def update_body(article_id, body):
    mutation = """
    mutation VerifyAndRepairRelatedVideo($id: ID!, $article: ArticleUpdateInput!) {
      articleUpdate(id: $id, article: $article) {
        article { id title handle isPublished body }
        userErrors { field message }
      }
    }
    """
    data = shopify_graphql(mutation, {"id": article_id, "article": {"body": body}})
    result = data.get("articleUpdate") or {}
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError(str(errors))
    article = result.get("article")
    if not article:
        raise RuntimeError("Shopify returned no updated article.")
    return article


def insert_related_video(body, embed):
    marker = (
        '<section class="vn-related-video" aria-label="Related video">'
        '<h2>Related video</h2>' + embed + '</section>'
    )
    insert_at = re.search(r"<p[^>]*>\s*<strong>Sources?:</strong>", body, re.I)
    if insert_at:
        return body[:insert_at.start()] + marker + body[insert_at.start():]
    return body + marker


def main():
    if not env("SHOPIFY_STORE_DOMAIN"):
        raise RuntimeError("Missing SHOPIFY_STORE_DOMAIN.")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = load_state()
    attempted = state.setdefault("attempted", {})
    now = datetime.now(timezone.utc)
    articles = list_articles()
    logging.info("Published Valuted News articles queued for publisher/player verification: %d", len(articles))
    checked = added = replaced = removed = unchanged = unverified = 0

    for article in articles:
        article_id = str(article.get("id") or "")
        title = article.get("title") or "(untitled)"
        source_url = primary_source_url(article.get("body", ""))
        if not source_url:
            unverified += 1
            logging.warning("No explicit cited publisher URL; leaving video unchanged: %s", title)
            continue
        checked += 1
        try:
            media = fetch_article_media(source_url)
            if not media.get("source_page_ok"):
                unverified += 1
                logging.warning("Publisher page unavailable; leaving existing video unchanged: %s", title)
                continue

            candidate = media.get("video_html") or ""
            if candidate and not video_embed_is_available(candidate):
                logging.warning("Publisher video player failed availability check: %s", title)
                candidate = ""

            original_body = article.get("body") or ""
            body_without_video = remove_related_video(original_body)
            current_sources = re.findall(r'<iframe\b[^>]*src=["\']([^"\']+)["\']', original_body, re.I)
            candidate_sources = re.findall(r'<iframe\b[^>]*src=["\']([^"\']+)["\']', candidate, re.I)

            if candidate and current_sources == candidate_sources and body_without_video != original_body:
                unchanged += 1
                attempted[article_id] = now.isoformat()
                continue

            if candidate:
                new_body = insert_related_video(body_without_video, candidate)
                if new_body == original_body:
                    unchanged += 1
                else:
                    update_body(article_id, new_body)
                    if current_sources:
                        replaced += 1
                        logging.info("Replaced old embed with verified publisher video: %s", title)
                    else:
                        added += 1
                        logging.info("Restored verified publisher video: %s", title)
            elif body_without_video != original_body:
                update_body(article_id, body_without_video)
                removed += 1
                logging.warning("Removed unverified/unplayable video; cited source has no playable video: %s", title)
            else:
                unchanged += 1

            attempted[article_id] = now.isoformat()
        except Exception:
            unverified += 1
            logging.exception("Publisher video audit failed for: %s", title)

    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    logging.info(
        "Publisher video audit finished: checked=%d added=%d replaced=%d removed=%d unchanged=%d unverified=%d",
        checked, added, replaced, removed, unchanged, unverified,
    )


if __name__ == "__main__":
    main()
