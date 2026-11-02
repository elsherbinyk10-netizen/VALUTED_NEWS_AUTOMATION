"""Full published-article iframe audit and safe repair for Valuted News."""
import logging
import re
from datetime import datetime, timezone

from news_worker import (
    env, shopify_graphql, fetch_article_media,
    video_embed_is_available, fetch_related_youtube_embed,
)
from backfill_video import primary_source_url, update_body, insert_related_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BLOG_ID = env("SHOPIFY_BLOG_ID", "gid://shopify/Blog/126010065175")


def list_all_published_articles():
    query = """
    query AllPublishedArticlesForVideoAudit($id: ID!, $after: String) {
      blog(id: $id) {
        articles(first: 250, reverse: true, after: $after) {
          nodes { id title handle body isPublished tags }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """
    result, cursor = [], None
    while True:
        data = shopify_graphql(query, {"id": BLOG_ID, "after": cursor})
        connection = (data.get("blog") or {}).get("articles", {})
        result.extend(connection.get("nodes", []))
        info = connection.get("pageInfo") or {}
        if not info.get("hasNextPage") or not info.get("endCursor"):
            break
        cursor = info["endCursor"]
    return [a for a in result if a.get("isPublished")]


def iframe_sources(body):
    return re.findall(r'<iframe\\b[^>]*src=["\\']([^"\\']+)["\\']', body or "", re.I)


def strip_broken_iframes(body, broken):
    cleaned = body or ""
    for source in broken:
        escaped = re.escape(source).replace(r"\\&amp;", r"(?:&amp;|&)")
        iframe = r'<iframe\\b(?=[^>]*src=["\\']' + escaped + r'["\\'])[^>]*>\\s*</iframe>'
        section = r'<section\\b[^>]*class=["\\'][^"\\']*vn-related-video[^"\\']*["\\'][^>]*>[\\s\\S]*?' + iframe + r'[\\s\\S]*?</section>'
        cleaned, count = re.subn(section, "", cleaned, count=1, flags=re.I)
        if count:
            continue
        wrapper = r'<div\\b[^>]*class=["\\'][^"\\']*valuted-news-video[^"\\']*["\\'][^>]*>[\\s\\S]*?' + iframe + r'[\\s\\S]*?</div>'
        cleaned, count = re.subn(wrapper, "", cleaned, count=1, flags=re.I)
        if not count:
            cleaned = re.sub(iframe, "", cleaned, count=1, flags=re.I)
    return cleaned


def main():
    if not env("SHOPIFY_STORE_DOMAIN"):
        raise RuntimeError("Missing SHOPIFY_STORE_DOMAIN.")
    articles = list_all_published_articles()
    checked = broken_total = replaced = added = healthy = unresolved = errors = 0
    logging.info("Starting full video playback audit across %d published Valuted News articles.", len(articles))

    for article in articles:
        checked += 1
        title = article.get("title") or "(untitled)"
        body = article.get("body") or ""
        sources = iframe_sources(body)
        broken = []
        try:
            for source in sources:
                test_html = '<iframe src="' + source.replace("&amp;", "&") + '"></iframe>'
                if not video_embed_is_available(test_html):
                    broken.append(source)
            if not broken:
                if sources:
                    healthy += 1
                    logging.info("VIDEO_OK: %s (%d iframe(s))", title, len(sources))
                continue

            broken_total += len(broken)
            logging.warning("VIDEO_ERROR: %s (%d/%d broken iframe(s))", title, len(broken), len(sources))
            source_url = primary_source_url(body)
            media = fetch_article_media(source_url) if source_url else {"video_html": ""}
            candidate = media.get("video_html") or ""
            if candidate and not video_embed_is_available(candidate):
                candidate = ""
            if not candidate:
                category = " ".join(article.get("tags") or [])
                candidate = fetch_related_youtube_embed(title, category) or ""
                if candidate and not video_embed_is_available(candidate):
                    candidate = ""

            if not candidate:
                unresolved += 1
                logging.error("VIDEO_UNRESOLVED: no verified replacement; leaving article unchanged: %s", title)
                continue

            cleaned = strip_broken_iframes(body, broken)
            cleaned = re.sub(
                r'<section\\b[^>]*class=["\\'][^"\\']*vn-related-video[^"\\']*["\\'][^>]*>[\\s\\S]*?</section>',
                "", cleaned, flags=re.I,
            )
            updated = insert_related_video(cleaned, candidate)
            update_body(str(article["id"]), updated)
            replaced += 1
            logging.info("VIDEO_REPAIRED: replaced broken player with verified video: %s", title)
        except Exception:
            errors += 1
            logging.exception("VIDEO_AUDIT_ERROR: %s", title)

    logging.info(
        "FULL VIDEO AUDIT SUMMARY: checked=%d healthy_articles=%d broken_iframes=%d repaired=%d unresolved=%d errors=%d at=%s",
        checked, healthy, broken_total, replaced, unresolved, errors, datetime.now(timezone.utc).isoformat(),
    )
    if errors:
        raise RuntimeError(f"{errors} article(s) could not be audited; inspect logs.")
    if unresolved:
        logging.warning("%d article(s) still need an editor-approved replacement video.", unresolved)


if __name__ == "__main__":
    main()
