"""Strict provenance, relevance and freshness policy for featured news images.

Only image URLs explicitly declared by the original publisher/official organization
on the cited article page are eligible. Commons/Openverse discovery is intentionally
not accepted for current-news featured images by this policy.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

STOP = {
    "the","and","for","with","from","that","this","what","when","where","will",
    "after","before","into","over","under","says","said","have","has","are","was",
    "were","its","their","how","why","who","new","latest","news","2026","2025",
    "about","report","reports","update","updates","official","watch","video",
}
DATE_KEYS = (
    "article:published_time", "datePublished", "datepublished",
    "parsely-pub-date", "pubdate", "publishdate", "date",
    "article:modified_time", "dateModified", "datemodified",
)


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


def inspect_publisher_page(page_url, html_text, article_title, article_date=None):
    """Validate publisher identity, article title relevance, canonical image and date."""
    page = urlparse(page_url)
    host = _host(page_url)
    if page.scheme != "https" or not host:
        return {"ok": False, "reason": "publisher-page-not-https"}
    soup = BeautifulSoup(html_text or "", "html.parser")
    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    canonical_url = urljoin(page_url, canonical.get("href", "")) if canonical else page_url
    if _host(canonical_url) != host:
        return {"ok": False, "reason": "canonical-host-mismatch"}
    page_title = ""
    for selector in ({"property":"og:title"},{"name":"twitter:title"}):
        node = soup.find("meta", attrs=selector)
        if node and node.get("content"):
            page_title = node["content"]
            break
    if not page_title and soup.title:
        page_title = soup.title.get_text(" ", strip=True)
    expected = _tokens(article_title)
    observed = _tokens(page_title)
    if len(expected) < 2 or len(expected & observed) < min(3, len(expected)):
        return {"ok": False, "reason": "publisher-page-title-mismatch", "page_title": page_title}

    image_urls = []
    for attrs in ({"property":"og:image"},{"name":"twitter:image"},{"name":"twitter:image:src"}):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            image_urls.append(urljoin(page_url, node["content"]))
    # JSON-LD images are accepted only when they are part of the original publisher page.
    for node in soup.find_all("script", type="application/ld+json"):
        raw = node.string or node.get_text()
        for match in re.findall(r'"image"\s*:\s*(?:"([^"]+)"|\[\s*"([^"]+)"|\{[^}]*?"url"\s*:\s*"([^"]+)")', raw or "", re.I):
            candidate = next((x for x in match if x), "")
            if candidate:
                image_urls.append(urljoin(page_url, candidate))
    image_urls = list(dict.fromkeys(image_urls))
    if not image_urls:
        return {"ok": False, "reason": "publisher-image-metadata-missing"}

    dates = []
    for key in DATE_KEYS:
        node = soup.find("meta", attrs={"property":key}) or soup.find("meta", attrs={"name":key})
        if node and node.get("content"):
            parsed = _parse_date(node["content"])
            if parsed:
                dates.append(parsed)
    for node in soup.find_all("script", type="application/ld+json"):
        raw = node.string or node.get_text()
        for key in ("datePublished","dateModified"):
            dates.extend(filter(None, (_parse_date(v) for v in re.findall(r'"'+key+r'"' + r'\s*:\s*"([^"]+)"', raw or "", re.I))))
    source_date = max(dates) if dates else None
    expected_date = _parse_date(article_date)
    if not source_date:
        return {"ok": False, "reason": "publisher-date-missing"}
    if expected_date and abs((source_date - expected_date).total_seconds()) > 7 * 86400:
        return {"ok": False, "reason": "publisher-date-outside-article-window",
                "source_date": source_date.isoformat(), "article_date": expected_date.isoformat()}
    return {"ok": True, "publisher_host": host, "page_title": page_title,
            "source_date": source_date.isoformat(), "image_urls": image_urls}


def verify_publisher_image(page_url, html_text, article_title, candidate_url, article_date=None):
    result = inspect_publisher_page(page_url, html_text, article_title, article_date)
    if not result.get("ok"):
        return result
    candidate = urljoin(page_url, str(candidate_url or ""))
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or _host(candidate) != result["publisher_host"]:
        return {"ok": False, "reason": "image-not-hosted-by-original-publisher"}
    approved = {_normalize_url(x) for x in result["image_urls"]}
    if _normalize_url(candidate) not in approved:
        return {"ok": False, "reason": "image-not-declared-by-publisher-page"}
    result["image_url"] = candidate
    result["credit"] = "Image source: " + page_url
    return result


def _normalize_url(url):
    parsed = urlparse(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(),
            parsed.path.rstrip("/"))
