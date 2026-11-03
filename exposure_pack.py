import argparse
import csv
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from news_worker import shopify_graphql, env


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = 0
        self.headings = 0

    def handle_data(self, data):
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links += 1
        if tag in ("h1", "h2", "h3"):
            self.headings += 1


def inspect(value):
    parser = Text()
    parser.feed(str(value or ""))
    text = re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip()
    return text, parser.links, parser.headings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    query = """query Exposure($id: ID!, $n: Int!) {
      blog(id: $id) { articles(first: $n, reverse: true) {
        nodes { title handle summary body isPublished tags image { url }
          metafields(first: 10, namespace: "global") { nodes { key value } }
        }
      } }
    }"""
    data = shopify_graphql(query, {
        "id": env("SHOPIFY_BLOG_ID"),
        "n": max(1, min(args.limit, 10))
    })
    packs = []
    for article in (data.get("blog") or {}).get("articles", {}).get("nodes", []):
        if not article.get("isPublished") or not article.get("handle"):
            continue
        title = inspect(article.get("title"))[0]
        body, links, headings = inspect(article.get("body"))
        summary = inspect(article.get("summary"))[0] or body[:230]
        url = "https://valutednews.com/blogs/news/" + article["handle"]
        metafields = {
            item.get("key"): item.get("value", "")
            for item in (article.get("metafields") or {}).get("nodes", [])
        }
        seo_title = metafields.get("title_tag") or title
        description = metafields.get("description_tag") or summary
        image = (article.get("image") or {}).get("url", "")
        words = len(body.split())
        issues = []
        checks = {
            "seo_title_70_chars_or_less": len(seo_title) <= 70,
            "meta_description_110_to_160_chars": 110 <= len(description) <= 160,
            "featured_image_present": bool(image),
            "article_body_at_least_500_words_review": words >= 500,
            "at_least_one_article_link": links >= 1,
            "heading_structure_present": headings >= 1,
            "summary_present": bool(summary),
        }
        issues = [key for key, passed in checks.items() if not passed]
        tags = []
        for raw in list(article.get("tags") or []) + re.findall(r"[A-Za-z0-9]+", title):
            tag = "".join(part.title() for part in re.findall(r"[A-Za-z0-9]+", str(raw)))
            if len(tag) > 2 and tag.lower() not in {"the", "and", "with", "from", "news", "today"}:
                value = "#" + tag
                if value not in tags:
                    tags.append(value)
        social = {
            "facebook": f"{title}\n\n{summary}\n\nRead the full report: {url}",
            "instagram": f"{title}\n\n{summary}\n\nRead more via link in bio.\n{' '.join(tags[:8])}",
            "x": f"{title[:180]}\n{url}",
            "linkedin": f"{title}\n\n{summary}\n\nRead the full article: {url}",
            "pinterest": f"{title} — {summary}\n{url}",
        }
        packs.append({
            "title": title, "url": url, "seo_title": seo_title,
            "meta_description": description, "image_url": image,
            "body_word_count": words, "social": social,
            "audit": checks, "issues_to_review": issues,
        })

    out = Path("exposure_output")
    out.mkdir(exist_ok=True)
    (out / "valuted-news-exposure.json").write_text(
        json.dumps(packs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Valuted News — daily growth and exposure audit", "",
        "This report prepares promotion copy and flags editorial/SEO items for review.",
        "It does not publish to social accounts or change Shopify SEO fields.", "",
        f"Articles checked: {len(packs)}", ""
    ]
    for pack in packs:
        lines += [
            f"## {pack['title']}", f"URL: {pack['url']}",
            f"SEO title: {pack['seo_title']}",
            f"Meta description: {pack['meta_description']}",
            f"Body words: {pack['body_word_count']}",
            f"Featured image: {pack['image_url'] or 'MISSING'}", "",
            "### Review flags"
        ]
        lines += [f"- [{'x' if ok else ' '}] {key}" for key, ok in pack["audit"].items()]
        if pack["issues_to_review"]:
            lines += ["- Manual review: " + ", ".join(pack["issues_to_review"])]
        lines += [""]
        for platform, copy in pack["social"].items():
            lines += [f"### {platform.title()} copy", copy, ""]

    lines += [
        "# Free-traffic operating plan", "",
        "1. Publish only accurate, useful news with clear source attribution and meaningful original context; avoid thin rewrites and duplicate feeds.",
        "2. Add 2–4 relevant internal links from each new article to existing topic coverage and one useful topic hub.",
        "3. Share each article once with a platform-specific caption; do not spam groups or repeat identical posts.",
        "4. Build weekly topic clusters around search demand and update evergreen explainers when facts change.",
        "5. Review Google Search Console weekly: impressions, clicks, CTR and queries; use the Indexing report for index status. Improve pages with impressions but weak CTR.",
        "6. Use Search Console clicks, impressions, CTR and query data to prioritize useful content improvements.",
        "7. Monetization gate: verify ad-network eligibility, privacy/consent requirements and policy compliance before inserting ads.",
        "8. Revenue target: work toward $100/month combined; do not assume a traffic-to-revenue rate until actual RPM and affiliate conversion data exist.",
        "",
        "## Important limitation",
        "The automation reads published Shopify content and creates this report. It does not modify SEO metafields, submit URLs to search engines, or publish social posts."
    ]
    (out / "valuted-news-growth-plan.md").write_text("\n".join(lines), encoding="utf-8")
    tracker = out / "monthly-performance-tracker.csv"
    if not tracker.exists():
        with tracker.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["month", "site", "search_clicks", "search_impressions", "ad_revenue_usd", "affiliate_revenue_usd", "other_revenue_usd", "notes"])
    print(f"Audited {len(packs)} published Valuted News articles; report and tracker generated.")


if __name__ == "__main__":
    main()
