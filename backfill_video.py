"""Verify and repair live Valuted News videos against each article's cited publisher.

Only videos present on the cited publisher page and whose player endpoint responds with
valid metadata are embedded. Stale/unrelated embeds are removed after a successful
publisher-page check; inaccessible source pages are left untouched for safety.
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from news_worker import env, shopify_graphql, fetch_article_media, video_embed_is_available, fetch_related_youtube_embed

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
          nodes { id title handle body isPublished tags updatedAt }
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



def find_verified_related_video(title, tags=None):
    """Find a clearly labelled, title-matched related clip when the publisher has no player."""
    category = " ".join(tags or []) if isinstance(tags, (list, tuple)) else str(tags or "")
    candidate = fetch_related_youtube_embed(title, category)
    if candidate and video_embed_is_available(candidate):
        return candidate
    return ""


def existing_related_video_is_playable(body):
    """Keep a previously embedded related clip if its player still passes playback checks."""
    match = re.search(
        r'<section\b[^>]*class=["\'][^"\']*vn-related-video[^"\']*["\'][^>]*>[\s\S]*?</section>',
        body or "",
        re.I,
    )
    return bool(match and video_embed_is_available(match.group(0)))


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def should_recheck_article(article, attempted_at, now, interval_hours=168):
    """Recheck articles without a valid YouTube embed; skip already-embedded stories."""
    body = str(article.get("body") or "")
    valid_embed = re.search(
        r"""<iframe\b[^>]*\bsrc=["']https?://(?:www\.)?youtube(?:-nocookie)?\.com/embed/[A-Za-z0-9_-]{11}""",
        body,
        re.I,
    )
    if valid_embed:
        return False
    last_checked = _parse_iso_datetime(attempted_at)
    if not last_checked:
        return True
    if now - last_checked > timedelta(hours=interval_hours):
        return True
    article_updated = _parse_iso_datetime(article.get("updatedAt"))
    if article_updated and article_updated > last_checked + timedelta(minutes=5):
        return True
    return False


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

    recheck_hours = max(1, int(env("VIDEO_RECHECK_HOURS", "168")))
    for article in articles:
        article_id = str(article.get("id") or "")
        title = article.get("title") or "(untitled)"
        if not should_recheck_article(article, attempted.get(article_id), now, recheck_hours):
            unchanged += 1
            continue
        source_url = primary_source_url(article.get("body", ""))
        checked += 1
        try:
            media = fetch_article_media(source_url) if source_url else {"video_html": "", "source_page_ok": False}
            candidate = media.get("video_html") or ""
            if candidate and not video_embed_is_available(candidate):
                logging.warning("Publisher video player failed availability check: %s", title)
                candidate = ""

            original_body = article.get("body") or ""
            # When the cited publisher has no playable player, use a title-matched
            # clip and label it Related video; never present it as publisher footage.
            if not candidate:
                candidate = find_verified_related_video(title, article.get("tags"))
                if candidate:
                    logging.info("Found verified title-matched related video: %s", title)
            body_without_video = remove_related_video(original_body)
            current_sources = re.findall(r'<iframe\b[^>]*src=["\']([^"\']+)["\']', original_body, re.I)
            candidate_sources = re.findall(r'<iframe\b[^>]*src=["\']([^"\']+)["\']', candidate, re.I)

            if candidate and current_sources and current_sources == candidate_sources:
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
            elif existing_related_video_is_playable(original_body):
                unchanged += 1
                logging.info("Kept existing related video because its player is playable: %s", title)
            elif body_without_video != original_body:
                update_body(article_id, body_without_video)
                removed += 1
                logging.warning("Removed unplayable related video; no verified replacement was found: %s", title)
            else:
                unchanged += 1
                logging.warning("No verified publisher or title-matched related video found: %s", title)

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
