"""Backfill category-matched YouTube videos into published Valuted News articles.

Videos are optional: articles are updated only when the RSS search returns a title-matched
video appropriate to the story category. Existing embeds are preserved.
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from news_worker import env, shopify_graphql, fetch_related_youtube_embed, fetch_article_media
from backfill_media import source_urls

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BLOG_ID = env("SHOPIFY_BLOG_ID", "gid://shopify/Blog/126010065175")
STATE_FILE = Path("data/video_backfill.json")
# Retry unresolved articles every scheduled run so the whole archive is rechecked.
RETRY_DAYS = 0


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
    # Read every page in the blog archive; Shopify caps each page at 250.
    while True:
        data = shopify_graphql(query, {"id": BLOG_ID, "after": cursor})
        connection = (data.get("blog") or {}).get("articles", {})
        articles.extend(connection.get("nodes", []))
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            break
        cursor = page_info["endCursor"]
    return articles


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
    body = article.get("body") or ""
    combined = tags + " " + title

    # Prefer the explicit editorial section in RSS-derived drafts.
    # This avoids treating general news about TV networks as entertainment.
    section = re.search(r"<strong>\\s*Section:\\s*</strong>\\s*([^<]+)", body, re.I)
    if section:
        section_name = section.group(1).strip().lower()
        section_map = {
            "business": "Business", "world": "World", "politics": "Politics",
            "technology": "Technology", "science": "Science", "sports": "Sports",
            "health": "Health", "entertainment": "Entertainment", "music": "Music",
            "movies": "Movies", "news": "News"
        }
        if section_name in section_map:
            return section_map[section_name]

    if re.search(r"\\b(movie|movies|film|films|cinema|streaming|trailer)\\b", combined):
        return "Movies"
    if re.search(r"\\b(music|song|songs|album|albums|singer|singers|concert|concerts|tour|tours|music video)\\b", combined):
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
    limit = max(1, min(250, int(env("VIDEO_BACKFILL_LIMIT", "250"))))
    articles = list_articles()
    eligible = []
    for article in articles:
        body = article.get("body") or ""
        if any(marker in body.lower() for marker in ("youtube-nocookie.com/embed/", "youtube.com/embed/", "player.vimeo.com/video/", "<video")):
            continue
        key = str(article.get("id") or "")
        stamp = attempted.get(key, "")
        try:
            last_attempt = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
        except ValueError:
            last_attempt = None
        # Retry unresolved videos after the cooldown so the archive can be processed in batches,
        # while still allowing later runs to find videos newly indexed by search providers.
        if last_attempt and last_attempt > cutoff:
            continue
        eligible.append(article)

    # Process never-attempted articles first, then the oldest attempts. This prevents
    # unresolved early articles from starving the rest of a large archive.
    eligible.sort(key=lambda article: attempted.get(str(article.get("id") or ""), ""))
    logging.info("Articles checked (published + drafts)=%d; missing video=%d; batch limit=%d", len(articles), len(eligible), limit)
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
            # Prefer a video embedded on the article's own cited publisher page.
            # Only fall back to public video search when source-page metadata has no video.
            embed = ""
            source_candidates = list(source_urls(article.get("body", "")))[:5]
            for source_url in source_candidates:
                try:
                    media = fetch_article_media(source_url)
                    candidate_embed = media.get("video_html", "")
                    if candidate_embed and any(host in candidate_embed.lower() for host in (
                        "youtube-nocookie.com/embed/", "youtube.com/embed/",
                        "player.vimeo.com/video/", "<video"
                    )):
                        embed = candidate_embed
                        logging.info("Found publisher-page video for: %s", article.get("title"))
                        break
                except Exception as source_error:
                    logging.info("Publisher video lookup failed for %s: %s", article.get("title"), source_error)
            if not embed:
                embed = fetch_related_youtube_embed(article.get("title", ""), category)
            if not embed:
                # Search exact source headline first, then retry with a shorter
                # entity-rich query. The selector still enforces title/category
                # overlap before any video can be attached.
                source_title = article.get("title", "")
                short_title = re.sub(r"[:|—–-].*$", "", source_title).strip()
                if short_title and short_title.lower() != source_title.lower():
                    embed = fetch_related_youtube_embed(short_title, category)
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
