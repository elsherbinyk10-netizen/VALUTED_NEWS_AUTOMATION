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
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urlencode, quote_plus

import requests
from news_worker import env, shopify_graphql, fetch_article_media, canonical_url, clean_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BLOG_ID = env("SHOPIFY_BLOG_ID", "gid://shopify/Blog/126010065175")
HEADERS = {"User-Agent": "ValutedNewsMediaBackfill/1.0 (editorial media metadata; contact site owner)"}
BAD_IMAGE_TERMS = ("google-news", "google_news", "valuted-news-placeholder", "valuted_news_placeholder", "logo", "favicon", "default-thumbnail")


def normalized_image_identity(url):
    """Normalize image URL variants so the same source asset is not reused."""
    parsed = urlparse(url or "")
    basename = parsed.path.rsplit("/", 1)[-1]
    basename = re.sub(r"_s0-w[0-9]+", "", basename, flags=re.I)
    basename = re.sub(r"_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\\.)", "", basename, flags=re.I)
    return (parsed.hostname or "").lower() + "/" + basename if basename else ""


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
        # Never treat another owned network site or our own storefront as a news publisher.
        # Internal links and old placeholder URLs can otherwise attach unrelated site artwork.
        owned_hosts = (
            "valutednews.com", "skyvalutsweather.space", "solepick.site",
            "valutedmovies.online", "pdfdownloader.online",
        )
        if (not host or any(host == domain or host.endswith("." + domain) for domain in owned_hosts)
                or host.endswith("google.com") or host.endswith("googleusercontent.com")):
            continue
        if host in ("youtube.com", "www.youtube.com", "youtu.be", "facebook.com", "instagram.com", "x.com", "twitter.com"):
            continue
        clean = canonical_url(url)
        if clean and clean not in seen:
            seen.add(clean)
            yield clean


def find_publisher_source(title):
    """Search Google News RSS for the exact story, then resolve to the publisher URL.
    Google News is used only to discover a source URL, never as an image source.
    """
    endpoint = "https://news.google.com/rss/search?q=" + quote_plus('"' + title + '"') + "&hl=en-US&gl=US&ceid=US:en"
    try:
        response = requests.get(endpoint, headers=HEADERS, timeout=(5, 12), allow_redirects=True)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        title_terms = set(re.findall(r"[a-z0-9]{4,}", title.lower()))
        stop = {"news", "latest", "update", "updates", "what", "when", "where", "does", "that", "this", "from", "with", "about", "guide", "how", "follow", "world", "report", "reports", "today", "2026"}
        title_terms -= stop
        choices = []
        for item in root.findall(".//item")[:12]:
            item_title = clean_text(item.findtext("title", ""))
            url = (item.findtext("link", "") or "").strip()
            if not url:
                continue
            shared = len(title_terms & set(re.findall(r"[a-z0-9]{4,}", item_title.lower())))
            if shared < min(3, max(1, len(title_terms))):
                continue
            try:
                resolved = requests.get(url, headers=HEADERS, timeout=(5, 12), allow_redirects=True, stream=True)
                final_url = resolved.url
                resolved.close()
                parsed = urlparse(final_url)
                host = (parsed.hostname or "").lower()
                if parsed.scheme not in ("http", "https") or not host or host.endswith("google.com") or host.endswith("googleusercontent.com"):
                    continue
                choices.append((shared, canonical_url(final_url)))
            except requests.RequestException:
                continue
        if choices:
            choices.sort(reverse=True)
            return choices[0][1]
    except (requests.RequestException, ET.ParseError) as exc:
        logging.info("Publisher discovery unavailable for %s: %s", title, exc)
    return ""


def wikimedia_image(title, excluded_identities=None):
    """Find a related, reusable Commons image with title overlap and explicit attribution."""
    stopwords = {"news", "latest", "update", "updates", "what", "when", "where", "does", "that", "this", "from", "with", "about", "guide", "how", "follow", "world", "report", "reports", "explainer", "explained", "today", "2026", "after", "amid", "says", "said", "could", "would", "will", "over", "into", "their", "your", "new"}
    title_terms = list(dict.fromkeys(re.findall(r"[a-z0-9]{4,}", title.lower())))
    useful_terms = [term for term in title_terms if term not in stopwords]
    queries = [title]
    if len(useful_terms) >= 3:
        queries.append(" ".join(useful_terms[:6]))
    if len(useful_terms) >= 4:
        queries.append(" ".join(useful_terms[:3]))
    pages = {}
    for search_term in dict.fromkeys(queries):
        try:
            params = {"action":"query","format":"json","generator":"search","gsrsearch":search_term,"gsrnamespace":6,"gsrlimit":20,"prop":"imageinfo","iiprop":"url|extmetadata","iiurlwidth":1400}
            query = None
            for attempt in range(3):
                query = requests.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params=params, headers=HEADERS, timeout=(5, 12),
                )
                if query.status_code != 429 and query.status_code < 500:
                    break
                query.close()
                time.sleep(2 * (attempt + 1))
            if query is None:
                continue
            query.raise_for_status()
            pages.update(query.json().get("query", {}).get("pages", {}))
        except (requests.RequestException, ValueError) as exc:
            logging.info("Commons search unavailable for '%s': %s", search_term, exc)
    candidates = []
    term_set = set(useful_terms)
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = clean_text((meta.get("LicenseShortName") or {}).get("value", ""))
        license_url = clean_text((meta.get("LicenseUrl") or {}).get("value", ""))
        artist = clean_text((meta.get("Artist") or {}).get("value", ""))
        description = clean_text((meta.get("ImageDescription") or {}).get("value", ""))
        combined = (page.get("title", "") + " " + description).lower()
        overlap = term_set & set(re.findall(r"[a-z0-9]{4,}", combined))
        if len(overlap) < 2 or not info.get("thumburl") or not license_name:
            continue
        if excluded_identities and normalized_image_identity(info["thumburl"]) in excluded_identities:
            continue
        if not any(x in license_name.lower() for x in ("cc0", "public domain", "cc by", "cc-by", "cc by-sa", "cc-by-sa")):
            continue
        candidates.append((len(overlap), info["thumburl"], page.get("title", ""), artist, license_name, license_url, description))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    score, url, file_title, artist, license_name, license_url, description = candidates[0]
    if not image_is_valid(url):
        return None
    credit = "Image credit: Wikimedia Commons — " + file_title
    if artist:
        credit += " · " + artist
    credit += " · " + license_name
    if license_url:
        credit += " · " + license_url
    desc_terms = set(re.findall(r"[a-z0-9]{4,}", (file_title + " " + description).lower()))
    alt = title if len(term_set & desc_terms) >= 3 else "Illustrative image related to: " + title + " (not necessarily depicting the specific event)"
    return {"url": url, "credit": credit, "alt": alt}


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
    def media_identity(article):
        image = article.get("image") or {}
        url = str(image.get("url") or "")
        parsed = urlparse(url)
        basename = parsed.path.rsplit("/", 1)[-1]
        # Shopify's image resize variants can add different UUID suffixes to the same source asset.
        match = re.match(r"^(.+?_s0-w\d+)", basename, re.I)
        return (parsed.hostname or "").lower() + "/" + (match.group(1) if match else basename) if basename else ""

    from collections import Counter
    identity_counts = Counter(media_identity(a) for a in articles if media_identity(a))
    # Exclude all currently-used assets during repairs; never reuse one image across unrelated stories.
    try:
        excluded_image_identities = set(json.loads(env("EXCLUDED_IMAGE_IDENTITIES", "[]")))
    except (TypeError, ValueError):
        excluded_image_identities = set()
    excluded_image_identities.update(
        normalized_image_identity(str((a.get("image") or {}).get("url") or ""))
        for a in articles if (a.get("image") or {}).get("url")
    )
    def needs_real_image(article):
        image = article.get("image") or {}
        url = str(image.get("url") or "")
        alt = str(image.get("altText") or "")
        combined = (url + " " + alt).lower()
        generic = any(term in combined for term in (
            "google news", "google-news", "google_news", "valuted news", "valuted-news",
            "valuted_news", "placeholder", "generic poster", "default thumbnail"
        ))
        body = (article.get("body") or "").lower()
        repeated_aggregator_art = ("google news top stories" in body and identity_counts[media_identity(article)] > 1) if media_identity(article) else False
        return not url or generic or repeated_aggregator_art

    missing = [a for a in articles if needs_real_image(a)]
    limit = max(1, min(100, int(env("MEDIA_BACKFILL_LIMIT", "100"))))
    fixed = 0
    unresolved = []
    logging.info("Articles checked (published + drafts)=%d; missing/generic images=%d; per-run limit=%d", len(articles), len(missing), limit)
    for article in missing:
        if fixed >= limit:
            break
        chosen = None
        source = None
        source_candidates = list(source_urls(article.get("body", "")))[:5]
        # If a source URL was not retained in the article body, discover the publisher page
        # from the story headline. Google News is used only for URL discovery, never artwork.
        discovered = find_publisher_source(article["title"])
        if discovered and discovered not in source_candidates:
            source_candidates.insert(0, discovered)
        for url in source_candidates[:6]:
            media = fetch_article_media(url)
            candidate = media.get("image_url", "")
            if image_is_valid(candidate) and normalized_image_identity(candidate) not in excluded_image_identities:
                chosen = {"url": candidate, "alt": article["title"], "credit": "Image source: " + url}
                source = url
                break
        # Licensed, title-matched Commons artwork is a fallback for current stories too.
        # If it may not depict the exact event, the image alt text explicitly says illustrative.
        if not chosen:
            try:
                candidate = wikimedia_image(article["title"], excluded_image_identities)
                if candidate:
                    chosen = candidate
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
            excluded_image_identities.add(normalized_image_identity(chosen["url"]))
            logging.info("Attached article-specific image: %s (%s)", article["title"], source or "Wikimedia Commons")
            time.sleep(0.4)
        except Exception:
            logging.exception("Image update failed for %s", article["title"])
    logging.info("Media backfill complete: fixed=%d unresolved=%d", fixed, len(unresolved))
    if unresolved:
        logging.warning("Still missing verified images: %s", " | ".join(unresolved[:30]))


if __name__ == "__main__":
    main()
