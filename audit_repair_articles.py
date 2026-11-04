"""Audit every Valuted News article and repair only reversible text/footer defects."""
import logging
import re
import time

from article_quality import normalize_article_summary, repair_mojibake, text_integrity_issues
from news_worker import env, shopify_graphql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BLOG_ID = env("SHOPIFY_BLOG_ID", "gid://shopify/Blog/107387158765")

LIST_QUERY = """
query AuditNewsArticles($blogId: ID!, $after: String) {
  blog(id: $blogId) {
    articles(first: 50, after: $after, reverse: true) {
      nodes { id title body summary }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

UPDATE_MUTATION = """
mutation RepairNewsArticle($id: ID!, $article: ArticleUpdateInput!) {
  articleUpdate(id: $id, article: $article) {
    article { id title }
    userErrors { field message }
  }
}
"""

# Legacy publisher output appended a second source block after </article>.
# Match it even when image-credit markup follows; preserve all in-article content.
DUPLICATE_EXTERNAL_SOURCE = re.compile(
    r"""(?P<close></article>)\s*<hr>\s*(?P<footer><p[^>]*>\s*<strong>\s*Source:\s*</strong>.*?Read the original report</a>\s*</p>)""",
    re.I | re.S,
)


def _has_duplicate_external_source(body):
    """True only when a post-article footer repeats the in-article source URL."""
    match = DUPLICATE_EXTERNAL_SOURCE.search(body or "")
    if not match:
        return False
    inside = (body or "")[:match.start()]
    footer = match.group("footer")
    link_pattern = re.compile(
        r"""<a\b[^>]*href=["']([^"']+)["'][^>]*>Read the original report</a>""",
        re.I,
    )
    inside_links = link_pattern.findall(inside)
    footer_links = link_pattern.findall(footer)
    if inside_links and footer_links:
        return inside_links[-1].strip() == footer_links[-1].strip()
    source_pattern = re.compile(r"<strong>\s*Source:\s*</strong>\s*([^.<]+)", re.I)
    inside_sources = source_pattern.findall(inside)
    footer_sources = source_pattern.findall(footer)
    return bool(
        inside_sources and footer_sources
        and inside_sources[-1].strip().casefold() == footer_sources[0].strip().casefold()
    )


def repair_article_fields(article):
    """Repair reversible encoding and remove only a confirmed duplicate source footer."""
    original_title = article.get("title", "") or ""
    original_summary = article.get("summary", "") or ""
    original_body = article.get("body", "") or ""
    title = repair_mojibake(original_title)
    summary = normalize_article_summary(repair_mojibake(original_summary), title or original_title)
    body = repair_mojibake(original_body)

    if _has_duplicate_external_source(body):
        body = DUPLICATE_EXTERNAL_SOURCE.sub(lambda m: m.group("close"), body, count=1)

    changes = {}
    if title != original_title:
        changes["title"] = title
    if summary != original_summary:
        changes["summary"] = summary
    if body != original_body:
        changes["body"] = body
    return changes


def main():
    after = None
    scanned = repaired = residual_encoding = residual_duplicate = 0
    while True:
        data = shopify_graphql(LIST_QUERY, {"blogId": BLOG_ID, "after": after})
        connection = ((data.get("blog") or {}).get("articles") or {})
        nodes = connection.get("nodes") or []
        if data.get("blog") is None:
            identity = shopify_graphql("query { shop { name myshopifyDomain primaryDomain { host } } }", {})
            shop = identity.get("shop") or {}
            raise RuntimeError(
                f"Configured Shopify destination blog {BLOG_ID} was not found on "
                f"connected store {shop.get('name', 'unknown')} "
                f"({shop.get('myshopifyDomain', 'unknown')}; primary domain "
                f"{(shop.get('primaryDomain') or {}).get('host', 'unknown')}). "
                "Check SHOPIFY_STORE_DOMAIN and the Shopify app credentials; refusing to publish to another store."
            )
        if not nodes and scanned == 0:
            logging.warning("The verified News blog exists but currently contains zero articles. Archive restoration is still required; continuing so fresh eligible stories can be collected.")
            break

        for article in nodes:
            scanned += 1
            changes = repair_article_fields(article)
            if changes:
                result = shopify_graphql(
                    UPDATE_MUTATION,
                    {"id": article["id"], "article": changes},
                ).get("articleUpdate") or {}
                errors = result.get("userErrors") or []
                if errors:
                    raise RuntimeError(
                        "Shopify rejected repair for "
                        + str(article.get("title", article["id"]))
                        + ": " + str(errors)
                    )
                repaired += 1
                logging.info("Repaired article %s (%s)", article["id"], ", ".join(changes))
                time.sleep(0.25)

            final_title = changes.get("title", article.get("title", "") or "")
            final_summary = changes.get("summary", article.get("summary", "") or "")
            final_body = changes.get("body", article.get("body", "") or "")
            if text_integrity_issues(final_title, final_summary, final_body):
                residual_encoding += 1
                logging.error("Unresolved text-integrity issue: %s", article.get("title"))
            if _has_duplicate_external_source(final_body):
                residual_duplicate += 1
                logging.error("Unresolved duplicate source footer: %s", article.get("title"))

        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor")
        if not after:
            raise RuntimeError("Shopify pagination returned hasNextPage without an endCursor.")

    logging.info(
        "Existing article repair complete: scanned=%d repaired=%d residual_encoding=%d residual_duplicate_source=%d",
        scanned, repaired, residual_encoding, residual_duplicate,
    )
    if residual_encoding or residual_duplicate:
        raise RuntimeError(
            f"Article quality gate failed: {residual_encoding} encoding issues and "
            f"{residual_duplicate} duplicate source footers remain."
        )


if __name__ == "__main__":
    main()
