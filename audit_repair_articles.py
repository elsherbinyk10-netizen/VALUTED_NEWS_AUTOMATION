"""Audit every Valuted News article and repair only reversible text/footer defects."""
import logging
import re
import time

from article_quality import normalize_article_summary, repair_mojibake
from news_worker import env, shopify_graphql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BLOG_ID = env("SHOPIFY_BLOG_ID", "gid://shopify/Blog/126010065175")

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

# The legacy create path appended this footer after the closing article tag,
# even when the article body already had its own source attribution.
DUPLICATE_TRAILING_SOURCE = re.compile(
    r"</article>\s*<hr>\s*<p><strong>Source:</strong>.*?"
    r"Read the original report</a></p>\s*$",
    re.I | re.S,
)


def repair_article_fields(article):
    """Repair reversible encoding only; remove only the known trailing duplicate footer."""
    original_title = article.get("title", "") or ""
    original_summary = article.get("summary", "") or ""
    original_body = article.get("body", "") or ""
    title = repair_mojibake(original_title)
    summary = normalize_article_summary(repair_mojibake(original_summary), title or original_title)
    body = repair_mojibake(original_body)

    if body.lower().count("read the original report") > 1:
        body, count = DUPLICATE_TRAILING_SOURCE.subn("</article>", body, count=1)

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
    scanned = repaired = 0
    while True:
        data = shopify_graphql(LIST_QUERY, {"blogId": BLOG_ID, "after": after})
        connection = ((data.get("blog") or {}).get("articles") or {})
        nodes = connection.get("nodes") or []
        if not nodes and scanned == 0:
            raise RuntimeError("Shopify returned no articles; refusing to report a successful audit.")

        for article in nodes:
            scanned += 1
            changes = repair_article_fields(article)
            if not changes:
                continue
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

        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor")
        if not after:
            raise RuntimeError("Shopify pagination returned hasNextPage without an endCursor.")

    logging.info("Existing article repair complete: scanned=%d repaired=%d", scanned, repaired)


if __name__ == "__main__":
    main()
