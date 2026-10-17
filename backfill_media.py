"""Backfill missing article featured images from source metadata or Wikimedia Commons.

Only attach a candidate after validating that the URL serves an image. Source images are
preferred for current news. Wikimedia is used for evergreen explainers only; its license
and attribution are recorded in the article body. Generic Google News/Valuted placeholders
are explicitly rejected.
"""
import html
import json
import logging
import re
import time
from urllib.parse import urlparse, urlencode

import requests
from news_worker import env, shopify_graphql, fetch_article_media, canonical_url, clean_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BLOG_ID = env("SHOPIFY_BLOG_ID", "gid://shopify/Blog/126010065175")
HEADERS = {"User-Agent": "ValutedNewsMediaBackfill/1.0 (editorial media metadata; contact site owner)"}
BAD_IMAGE_TERMS = ("google-news", "google_news", "valuted-news-placeholder", "valuted_news_placeholder", "logo", "favicon", "default-thumbnail")


def image_is_valid(url):
    if not url:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if host in ("news.google.com", "google.com", "www.google.com") or any(term in path for term in BAD_IMAGE_TERMS):
        return False
    try:
        response = requests.get(url, headers=HEADERS, stream=True, timeout=(4, 8), allow_redirects=True)
        try:
            return response.ok and response.headers.get("Content-Type", "").lower().startswith("image/")
        finally:
            response.close()
    except requests.RequestException:
        return False


def source_urls(body):
    urls = re.findall(r"""href=["'](https?://[^"'<> ]+)["']""", body or "", re.I)
    seen = set()
    for url in urls:
        url = html.unescape(url)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host or host.endswith("valutednews.com") or host.endswith("google.com") or host.endswith("googleusercontent.com"):
            continue
        if host in ("youtube.com", "www.youtube.com", "youtu.be", "facebook.com", "instagram.com", "x.com", "twitter.com"):
            continue
        clean = canonical_url(url)
        if clean and clean not in seen:
            seen.add(clean)
            yield clean


def wikimedia_image(title):
    """Find a genuinely related Commons image with a reusable license and return its credit."""
    query = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": title, "gsrnamespace": 6, "gsrlimit": 8,
            "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1400,
        },
        headers=HEADERS, timeout=(5, 12),
    )
    query.raise_for_status()
    pages = query.json().get("query", {}).get("pages", {})
    title_terms = set(re.findall(r"[a-z0-9]{4,}", title.lower()))
    candidates = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = clean_text((meta.get("LicenseShortName") or {}).get("value", ""))
        license_url = clean_text((meta.get("LicenseUrl") or {}).get("value", ""))
        artist = clean_text((meta.get("Artist") or {}).get("value", ""))
        description = clean_text((meta.get("ImageDescription") or {}).get("value", ""))
        combined = (page.get("title", "") + " " + description).lower()
        score = len(title_terms & set(re.findall(r"[a-z0-9]{4,}", combined)))
        if score < 1 or not info.get("thumburl") or not license_name:
            continue
        if not any(x in license_name.lower() for x in ("cc0", "public domain", "cc by", "cc-by", "cc by-sa", "cc-by-sa")):
            continue
        candidates.append((score, info["thumburl"], page.get("title", ""), artist, license_name, license_url))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    score, url, file_title, artist, license_name, license_url = candidates[0]
    if not image_is_valid(url):
        return None
    credit = "Image credit: Wikimedia Commons — " + file_title
    if artist:
        credit += " · " + artist
    credit += " · " + license_name
    if license_url:
        credit += " · " + license_url
    return {"url": url, "credit": credit, "alt": title}


def list_articles():
    query = """
    query BackfillArticles($id: ID!) {
      blog(id: $id) {
        articles(first: 250, reverse: true) {
          nodes { id title handle body isPublished image { url altText } }
        }
      }
    }
    """
    data = shopify_graphql(query, {"id": BLOG_ID})
    return (data.get("blog") or {}).get("articles", {}).get("nodes", [])


def update_article(article, image_url, alt_text, credit=""):
    body = article.get("body") or ""
    if credit and credit not in body:
        body += '<p class="vn-image-credit">' + html.escape(credit) + '</p>'
    mutation = """
    mutation BackfillNewsImage($id: ID!, $article: ArticleUpdateInput!) {
      articleUpdate(id: $id, article: $article) {
        article { id title image { url altText } }
        userErrors { field message }
      }
    }
    """
    data = shopify_graphql(mutation, {
        "id": article["id"],
        "article": {
            "image": {"url": image_url, "altText": alt_text[:250]},
            **({"body": body} if credit else {}),
        },
    })
    result = data.get("articleUpdate") or {}
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError(str(errors))
    return result.get("article")


def main():
    if not env("SHOPIFY_STORE_DOMAIN"):
        raise RuntimeError("Missing SHOPIFY_STORE_DOMAIN.")
    articles = list_articles()
    def needs_real_image(article):
        image = article.get("image") or {}
        url = str(image.get("url") or "")
        alt = str(image.get("altText") or "")
        combined = (url + " " + alt).lower()
        generic = any(term in combined for term in (
            "google news", "google-news", "google_news", "valuted news", "valuted-news",
            "valuted_news", "placeholder", "generic poster", "default thumbnail"
        ))
        return not url or generic
    missing = [a for a in articles if a.get("isPublished") and needs_real_image(a)]
    limit = max(1, min(20, int(env("MEDIA_BACKFILL_LIMIT", "5"))))
    fixed = 0
    unresolved = []
    logging.info("Published articles checked=%d; missing images=%d; per-run limit=%d", len(articles), len(missing), limit)
    for article in missing:
        if fixed >= limit:
            break
        chosen = None
        source = None
        for url in list(source_urls(article.get("body", "")))[:5]:
            media = fetch_article_media(url)
            candidate = media.get("image_url", "")
            if image_is_valid(candidate):
                chosen = {"url": candidate, "alt": article["title"], "credit": "Image source: " + url}
                source = url
                break
        # Use Commons only for evergreen guides with no usable source image.
        if not chosen and re.search(r"\b(guide|how to|how does|explainer|what happened|how to verify|news:|how to follow)\b", article["title"], re.I):
            try:
                chosen = wikimedia_image(article["title"])
            except Exception as exc:
                logging.info("Commons lookup failed for %s: %s", article["title"], exc)
        if not chosen:
            unresolved.append(article["title"])
            logging.warning("No verified image found; leaving image blank: %s", article["title"])
            continue
        try:
            result = update_article(article, chosen["url"], chosen.get("alt", article["title"]), chosen.get("credit", ""))
            if not result:
                raise RuntimeError("Shopify returned no updated article.")
            fixed += 1
            logging.info("Attached article-specific image: %s (%s)", article["title"], source or "Wikimedia Commons")
            time.sleep(0.4)
        except Exception:
            logging.exception("Image update failed for %s", article["title"])
    logging.info("Media backfill complete: fixed=%d unresolved=%d", fixed, len(unresolved))
    if unresolved:
        logging.warning("Still missing verified images: %s", " | ".join(unresolved[:30]))


if __name__ == "__main__":
    main()
