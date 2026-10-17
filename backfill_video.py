"""Backfill category-matched YouTube videos into published Valuted News articles.

Videos are optional: articles are updated only when the RSS search returns a title-matched
video appropriate to the story category. Existing embeds are preserved.
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from news_worker import env, shopify_graphql, fetch_related_youtube_embed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BLOG_ID = env("SHOPIFY_BLOG_ID", "gid://shopify/Blog/126010065175")
STATE_FILE = Path("data/video_backfill.json")
RETRY_DAYS = 30


def load_state():
    try:
        data = json.loads(STATE_FILE.read_text())
        return data if isinstance(data, dict) else {"attempted": {}}
    except (OSError, json.JSONDecodeError):
        return {"attempted": {}}


def list_articles():
    query = """
    query PublishedArticlesForVideoBackfill($id: ID!) {
      blog(id: $id) {
        articles(first: 250, reverse: true) {
          nodes { id title handle body isPublished tags }
        }
      }
    }
    """
    data = shopify_graphql(query, {"id": BLOG_ID})
    return (data.get("blog") or {}).get("articles", {}).get("nodes", [])


def update_body(article_id, body):
    mutation = """
    mutation AddRelatedVideo($id: ID!, $article: ArticleUpdateInput!) {
      articleUpdate(id: $id, article: $article) {
        article { id title handle isPublished }
        userErrors { field message }
      }
    }
    """
    data = shopify_graphql(mutation, {"id": article_id, "article": {"body": body}})
    result = data.get("articleUpdate") or {}
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError(str(errors))
    return result.get("article")


def infer_category(article):
    tags = " ".join(article.get("tags") or []).lower()
    title = (article.get("title") or "").lower()
    combined = tags + " " + title
    if re.search(r"\b(movie|movies|film|films|cinema|streaming|tv|television|trailer)\b", combined):
        return "Movies"
    if re.search(r"\b(music|song|songs|album|albums|singer|singers|concert|concerts|tour|tours|music video)\b", combined):
        return "Music"
    return next((x.title() for x in ("technology", "science", "business", "sports", "world", "politics", "health", "entertainment") if x in combined), "News")


def main():
    if not env("SHOPIFY_STORE_DOMAIN"):
        raise RuntimeError("Missing SHOPIFY_STORE_DOMAIN.")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = load_state()
    attempted = state.setdefault("attempted", {})
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETRY_DAYS)
    limit = max(1, min(20, int(env("VIDEO_BACKFILL_LIMIT", "8"))))
    articles = list_articles()
    eligible = []
    for article in articles:
        if not article.get("isPublished"):
            continue
        body = article.get("body") or ""
        if re.search(r"youtube-nocookie\.com/embed/|youtube\.com/embed/|player\\.vimeo\.com/video/|<video\\b", body, re.I):
            continue
        key = str(article.get("id") or "")
        stamp = attempted.get(key, "")
        try:
            last_attempt = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
        except ValueError:
            last_attempt = None
        if last_attempt and last_attempt > cutoff:
            continue
        eligible.append(article)

    logging.info("Published articles=%d; missing video=%d; batch limit=%d", sum(bool(a.get("isPublished")) for a in articles), len(eligible), limit)
    processed = 0
    added = 0
    for article in eligible:
        if processed >= limit:
            break
        processed += 1
        key = str(article["id"])
        attempted[key] = now.isoformat()
        try:
            category = infer_category(article)
            embed = fetch_related_youtube_embed(article.get("title", ""), category)
            if not embed:
                logging.info("No confident %s video match; leaving article unchanged: %s", category, article.get("title"))
                continue
            body = article.get("body") or ""
            marker = '<section class="vn-related-video" aria-label="Related video"><h2>Related video</h2>' + embed + '</section>'
            insert_at = re.search(r"<p[^>]*>\s*<strong>Sources?:</strong>", body, re.I)
            if insert_at:
                body = body[:insert_at.start()] + marker + body[insert_at.start():]
            else:
                body += marker
            result = update_body(article["id"], body)
            if not result:
                raise RuntimeError("Shopify returned no updated article.")
            added += 1
            logging.info("Added category-matched video to: %s (%s)", article.get("title"), category)
        except Exception:
            logging.exception("Video backfill failed for: %s", article.get("title"))
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    logging.info("Video backfill finished: processed=%d added=%d", processed, added)


if __name__ == "__main__":
    main()
