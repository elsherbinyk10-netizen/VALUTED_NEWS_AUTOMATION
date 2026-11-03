"""Strict featured-image provenance, subject and date verification.

The image must be explicitly declared by the original publisher/official page,
the page title must match the article, and publisher dates must align with Shopify
publication/update dates. Unverifiable cases are rejected rather than guessed.
"""
import json
import re
from datetime import timezone
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

STOP = {
    "the","and","for","with","from","that","this","what","when","where","will",
    "after","before","into","over","under","says","said","have","has","are","was",
    "were","its","their","how","why","who","new","latest","news","2026","2025",
    "about","report","reports","update","updates","official","watch","video",
}
PUBLISHED_KEYS = ("article:published_time", "datePublished", "parsely-pub-date", "pubdate", "publishdate")
MODIFIED_KEYS = ("article:modified_time", "dateModified", "datemodified")


def _tokens(value):
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(value or "").lower()) if w not in STOP}


def _parse_date(value):
    if not value:
        return None
    try:
        from dateutil import parser
        dt = parser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def _host(url):
    return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")


def _jsonld_dates(value):
    found = {"published": [], "modified": [], "images": []}
    def walk(node):
        if isinstance(node, dict):
            for key in ("datePublished", "dateCreated"):
                dt = _parse_date(node.get(key))
                if dt:
                    found["published"].append(dt)
            for key in ("dateModified",):
                dt = _parse_date(node.get(key))
                if dt:
                    found["modified"].append(dt)
            image = node.get("image")
            values = image if isinstance(image, list) else [image]
            for item in values:
                if isinstance(item, str):
                    found["images"].append(item)
                elif isinstance(item, dict) and item.get("url"):
                    found["images"].append(item["url"])
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    try:
        walk(json.loads(value))
    except (ValueError, TypeError):
        pass
    return found


def inspect_publisher_page(page_url, html_text, article_title,
                           article_published_at=None, article_updated_at=None):
    parsed_page = urlparse(page_url)
    host = _host(page_url)
    if parsed_page.scheme != "https" or not host:
        return {"ok": False, "reason": "publisher-page-not-https"}
    soup = BeautifulSoup(html_text or "", "html.parser")
    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    canonical_url = urljoin(page_url, canonical.get("href", "")) if canonical else page_url
    if _host(canonical_url) != host:
        return {"ok": False, "reason": "canonical-host-mismatch"}

    page_title = ""
    for selector in ({"property": "og:title"}, {"name": "twitter:title"}):
        node = soup.find("meta", attrs=selector)
        if node and node.get("content"):
            page_title = node["content"]
            break
    if not page_title and soup.title:
        page_title = soup.title.get_text(" ", strip=True)
    expected, observed = _tokens(article_title), _tokens(page_title)
    if len(expected) < 2 or len(expected & observed) < min(3, len(expected)):
        return {"ok": False, "reason": "publisher-page-title-mismatch", "page_title": page_title}

    images, published, modified = [], [], []
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}, {"name": "twitter:image:src"}):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            images.append(urljoin(page_url, node["content"]))
    for key in PUBLISHED_KEYS:
        node = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if node and node.get("content"):
            dt = _parse_date(node["content"])
            if dt:
                published.append(dt)
    for key in MODIFIED_KEYS:
        node = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if node and node.get("content"):
            dt = _parse_date(node["content"])
            if dt:
                modified.append(dt)
    for node in soup.find_all("script", type="application/ld+json"):
        dates = _jsonld_dates(node.string or node.get_text())
        published.extend(dates["published"])
        modified.extend(dates["modified"])
        images.extend(urljoin(page_url, x) for x in dates["images"])
    images = list(dict.fromkeys(images))
    if not images:
        return {"ok": False, "reason": "publisher-image-metadata-missing"}
    source_published = min(published) if published else None
    source_modified = max(modified) if modified else source_published
    article_pub = _parse_date(article_published_at)
    article_update = _parse_date(article_updated_at)

    if not source_published:
        return {"ok": False, "reason": "publisher-publication-date-missing"}
    if article_pub and abs((source_published - article_pub).total_seconds()) > 7 * 86400:
        return {"ok": False, "reason": "publisher-publication-date-mismatch",
                "source_date": source_published.isoformat(), "article_date": article_pub.isoformat()}
    if article_update and article_pub and abs((article_update - article_pub).total_seconds()) > 86400:
        if not modified:
            return {"ok": False, "reason": "publisher-update-date-missing"}
        if abs((source_modified - article_update).total_seconds()) > 7 * 86400:
            return {"ok": False, "reason": "publisher-update-date-mismatch",
                    "source_date": source_modified.isoformat(), "article_date": article_update.isoformat()}
    return {
        "ok": True, "publisher_host": host, "page_title": page_title,
        "published_date": source_published.isoformat(),
        "modified_date": source_modified.isoformat(),
        "image_urls": images,
    }


def verify_publisher_image(page_url, html_text, article_title, candidate_url,
                           article_published_at=None, article_updated_at=None):
    result = inspect_publisher_page(
        page_url, html_text, article_title, article_published_at, article_updated_at
    )
    if not result.get("ok"):
        return result
    candidate = urljoin(page_url, str(candidate_url or ""))
    if urlparse(candidate).scheme != "https" or _host(candidate) != result["publisher_host"]:
        return {"ok": False, "reason": "image-not-hosted-by-original-publisher"}
    approved = {_normalize_url(x) for x in result["image_urls"]}
    if _normalize_url(candidate) not in approved:
        return {"ok": False, "reason": "image-not-declared-by-publisher-page"}
    result["image_url"] = candidate
    result["credit"] = "Image source: " + page_url
    return result


def _normalize_url(url):
    parsed = urlparse(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.path.rstrip("/"))
