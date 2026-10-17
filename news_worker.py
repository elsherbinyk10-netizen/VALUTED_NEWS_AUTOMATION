import argparse
import hashlib
import html
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import feedparser
import requests
from dateutil import parser as dateparser

ROOT = Path(__file__).resolve().parent
FEEDS_FILE = ROOT / "feeds.json"
STATE_FILE = ROOT / "data" / "processed.json"
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
HIGH_RISK = re.compile(
    r"\b(election|war|attack|killed|death|terror|outbreak|epidemic|pandemic|recall|lawsuit|fraud|bankrupt|crash|emergency|earthquake|hurricane|president|prime minister|minister|shooting|hostage|missing child)\b",
    re.I,
)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def env(name, default=""):
    return os.getenv(name, default).strip()


def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", value or ""))).strip()


def canonical_url(url):
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", urlencode(query), ""))
    except Exception:
        return ""


def story_key(url, title):
    return hashlib.sha256((canonical_url(url) or clean_text(title).lower()).encode("utf-8")).hexdigest()


def load_state():
    if not STATE_FILE.exists():
        return {"version": 1, "items": {}}
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(data.get("items"), dict):
        raise RuntimeError("Deduplication state is malformed; stopping to avoid duplicate publishing.")
    return data


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_FILE)


def entry_datetime(entry):
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                parsed = dateparser.parse(raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except Exception:
                pass
    return None



def extract_image(entry):
    """Return publisher-supplied RSS artwork only; never synthesize a generic image."""
    candidates = []
    for field in ("media_content", "media_thumbnail"):
        values = entry.get(field, []) or []
        if isinstance(values, dict):
            values = [values]
        for item in values:
            if isinstance(item, dict) and item.get("url"):
                media_type = str(item.get("type", "")).lower()
                medium = str(item.get("medium", "")).lower()
                if medium == "image" or media_type.startswith("image/") or not media_type:
                    candidates.append(item["url"])
    for item in entry.get("enclosures", []) or []:
        if isinstance(item, dict) and item.get("href") and str(item.get("type", "")).lower().startswith("image/"):
            candidates.append(item["href"])
    html_fields = [entry.get("summary", ""), entry.get("description", "")]
    for content_item in entry.get("content", []) or []:
        if isinstance(content_item, dict):
            html_fields.append(content_item.get("value", ""))
    for markup in html_fields:
        match = re.search(r"""<img\b[^>]*?\b(?:src|data-src)=["']([^"']+)["']""", markup or "", re.I)
        if match:
            candidates.append(html.unescape(match.group(1)))
    for candidate in candidates:
        try:
            parsed = urlparse(str(candidate).strip())
            if parsed.scheme in ("http", "https") and parsed.netloc:
                return parsed.geturl()
        except Exception:
            continue
    return ""


def extract_video_embed(entry):
    """Use only video URLs supplied by the publisher's RSS metadata."""
    candidates = []
    for field in ("media_content", "media_player"):
        values = entry.get(field, []) or []
        if isinstance(values, dict):
            values = [values]
        for item in values:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("content") or item.get("href")
            media_type = str(item.get("type", "")).lower()
            if url and ("video" in media_type or field == "media_player"):
                candidates.append(str(url))
    for item in entry.get("enclosures", []) or []:
        if isinstance(item, dict):
            url = item.get("href")
            media_type = str(item.get("type", "")).lower()
            if url and (media_type.startswith("video/") or url.lower().split("?")[0].endswith((".mp4", ".webm", ".ogg"))):
                candidates.append(str(url))
    for markup in [entry.get("summary", ""), entry.get("description", "")] + [
        item.get("value", "") for item in (entry.get("content", []) or []) if isinstance(item, dict)
    ]:
        for match in re.findall(r"""https?://[^\s\"'<>]+""", markup or "", re.I):
            candidates.append(html.unescape(match).rstrip("),.;"))
    for candidate in candidates:
        try:
            parsed = urlparse(candidate)
            host = (parsed.hostname or "").lower()
            path = parsed.path.lower()
            if parsed.scheme not in ("http", "https"):
                continue
            if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
                video_id = ""
                if host == "youtu.be":
                    video_id = path.strip("/").split("/")[0]
                elif path == "/watch":
                    video_id = dict(parse_qsl(parsed.query)).get("v", "")
                elif path.startswith(("/embed/", "/shorts/")):
                    video_id = path.split("/")[2] if len(path.split("/")) > 2 else ""
                if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
                    return f'<div class="valuted-news-video" style="position:relative;width:100%;aspect-ratio:16/9;margin:24px 0"><iframe src="https://www.youtube-nocookie.com/embed/{video_id}" title="Related news video" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe></div>'
            if host in ("vimeo.com", "www.vimeo.com", "player.vimeo.com"):
                video_id = path.strip("/").split("/")[-1]
                if video_id.isdigit():
                    return f'<div class="valuted-news-video" style="position:relative;width:100%;aspect-ratio:16/9;margin:24px 0"><iframe src="https://player.vimeo.com/video/{video_id}" title="Related news video" loading="lazy" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe></div>'
            if path.endswith((".mp4", ".webm", ".ogg")):
                safe_url = html.escape(candidate, quote=True)
                return f'<video controls preload="metadata" playsinline style="display:block;width:100%;height:auto;max-width:100%;margin:24px 0"><source src="{safe_url}"></video>'
        except Exception:
            continue
    return ""


def fetch_article_media(source_url):
    """Read only public Open Graph/Twitter media metadata from the publisher page."""
    try:
        parsed = urlparse(source_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return {"image_url": "", "video_html": ""}
        response = requests.get(
            source_url,
            headers={"User-Agent": "VALUTED-NEWS-RSS-Bot/1.0 (+publisher metadata; contact site owner)", "Accept": "text/html,application/xhtml+xml"},
            timeout=(3, 7),
            allow_redirects=True,
            stream=True,
        )
        try:
            if not response.ok or "html" not in response.headers.get("Content-Type", "").lower():
                return {"image_url": "", "video_html": ""}
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= 1_500_000:
                    break
            markup = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        finally:
            response.close()

        image_url = ""
        meta_tags = re.findall(r"<meta\b[^>]*>", markup, re.I)
        for tag in meta_tags:
            prop = re.search(r"""(?:property|name)\s*=\s*["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["']""", tag, re.I)
            if not prop:
                continue
            match = re.search(r"""content\s*=\s*["']([^"']+)["']""", tag, re.I)
            if match:
                candidate = html.unescape(match.group(1)).strip()
                parsed_image = urlparse(candidate)
                if parsed_image.scheme in ("http", "https") and parsed_image.netloc:
                    image_url = candidate
                    break

        video_markup = []
        for tag in re.findall(r"<meta\b[^>]*>", markup, re.I):
            is_video = re.search(r"""(?:property|name)\s*=\s*["'](?:og:video(?::url|:secure_url|:type)?|twitter:player)["']""", tag, re.I)
            if is_video:
                match = re.search(r"""content\s*=\s*["']([^"']+)["']""", tag, re.I)
                if match:
                    video_markup.append('<iframe src="' + html.escape(html.unescape(match.group(1)), quote=True) + '"></iframe>')
        for match in re.findall(r"""<iframe\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>""", markup, re.I):
            video_markup.append('<iframe src="' + html.escape(html.unescape(match), quote=True) + '"></iframe>')
        video_html = ""
        for candidate_markup in video_markup[:10]:
            video_html = extract_video_embed({"content": [{"value": candidate_markup}]})
            if video_html:
                break
        return {"image_url": image_url, "video_html": video_html}
    except Exception as exc:
        logging.debug("Publisher media metadata unavailable for %s: %s", source_url, exc)
        return {"image_url": "", "video_html": ""}


def shopify_access_token():
    shop = env("SHOPIFY_STORE_DOMAIN")
    direct_token = env("SHOPIFY_ADMIN_ACCESS_TOKEN")
    if direct_token:
        logging.info("Using configured Shopify Admin API token.")
        return direct_token
    client_id = env("SHOPIFY_CLIENT_ID")
    client_secret = env("SHOPIFY_CLIENT_SECRET")

    if not shop:
        raise RuntimeError("Missing SHOPIFY_STORE_DOMAIN repository secret.")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing SHOPIFY_CLIENT_ID or SHOPIFY_CLIENT_SECRET repository secret."
        )

    endpoint = f"https://{shop}/admin/oauth/access_token"
    try:
        response = requests.post(
            endpoint,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(
                f"Shopify token request failed with HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Shopify token response did not include an access_token.")
        logging.info("Obtained a temporary Shopify Admin API token.")
        return token
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not obtain Shopify Admin API token: {exc}") from exc


def shopify_graphql(query, variables):
    shop = env("SHOPIFY_STORE_DOMAIN")
    api_version = env("SHOPIFY_API_VERSION", "2026-10")

    if not shop:
        raise RuntimeError("Missing SHOPIFY_STORE_DOMAIN.")

    token = shopify_access_token()
    endpoint = f"https://{shop}/admin/api/{api_version}/graphql.json"

    response = requests.post(
        endpoint,
        headers={
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": variables},
        timeout=30,
    )
    if response.status_code in (401, 403):
        raise RuntimeError(
            "Shopify authentication/permission failure (HTTP "
            + str(response.status_code)
            + "). Check the GitHub Actions secrets "
              "SHOPIFY_ADMIN_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN. "
              "They must match VALUTED NEWS; verify the token is current "
              "and the app has the required write_content access. "
              "Never print or commit the token."
        )
    response.raise_for_status()
    payload = response.json()

    if payload.get("errors"):
        raise RuntimeError(f"Shopify GraphQL error: {payload['errors']}")

    return payload.get("data", {})

def make_editorial(title, publisher, category, description, video_html=""):
    """Create a professionally structured, source-attributed review draft."""
    safe_title = clean_text(title)[:120] or "Valuted News update"
    excerpt = clean_text(description)
    publisher_text = clean_text(publisher) or "Original source"
    category_text = clean_text(category) or "World"

    # Escape untrusted feed content before inserting it into HTML.
    safe_description = html.escape(excerpt[:2500])
    safe_publisher = html.escape(publisher_text)
    safe_category = html.escape(category_text)

    summary = (
        excerpt[:280].rstrip()
        if excerpt
        else f"{safe_title}. Read the original report from {publisher_text}."
    )

    body = (
        '<div class="valuted-news-article">'
        '<p><strong>EDITORIAL REVIEW REQUIRED — NOT FOR PUBLICATION</strong></p>'
        '<p>This article draft was assembled from RSS metadata. '
        'The information has not been independently verified by Valuted News. '
        'Review the original source, confirm names, dates and claims, '
        'and add independently verified context before publishing.</p>'
        '<hr>'
        '<h2>At a glance</h2>'
        f'<p>{safe_description}</p>'
        if safe_description else
        '<div class="valuted-news-article">'
        '<p><strong>EDITORIAL REVIEW REQUIRED — NOT FOR PUBLICATION</strong></p>'
        '<p>The RSS feed did not provide a usable summary. '
        'Review the original source and write a verified report before publishing.</p>'
        '<hr>'
        '<h2>Story details</h2>'
        '<p>No source summary was available for this draft.</p>'
    )

    if video_html:
        body += '<h2>Related video</h2>' + video_html

    body += (
        '<h2>Editorial checklist</h2>'
        '<ul>'
        '<li>Verify the claims against the original report and, where appropriate, additional reliable sources.</li>'
        '<li>Add verified context and original reporting; do not infer missing facts.</li>'
        '<li>Check names, dates, locations, figures and quotations.</li>'
        '<li>Confirm image ownership and usage rights before adding a featured image.</li>'
        '</ul>'
        '<p><strong>Section:</strong> ' + safe_category + '</p>'
        '<p><strong>Original publisher:</strong> ' + safe_publisher + '</p>'
        '<p><em>Valuted News Desk — editorial draft</em></p>'
        '</div>'
    )

    return {
        "title": safe_title,
        "summary": summary[:300],
        "body": body,
        "quality_ok": False,
    }


def create_shopify_article(blog_id, title, summary, body, source_url, publisher, category, publish, image_url=''):
    mutation = """
    mutation CreateNewsArticle($article: ArticleCreateInput!) {
      articleCreate(article: $article) {
        article { id title handle isPublished }
        userErrors { field message }
      }
    }
    """
    source = html.escape(source_url, quote=True)
    publisher_safe = html.escape(publisher)
    body_with_credit = (
        body
        + f'<hr><p><strong>Source:</strong> {publisher_safe}. '
          f'<a href="{source}" rel="nofollow noopener">Read the original report</a></p>'
    )
    article = {
        "blogId": blog_id,
        "title": title[:120],
        "body": body_with_credit,
        "summary": summary[:300],
        "tags": ["Valuted News", category, publisher],
        "author": {"name": "Valuted News Desk"},
        "isPublished": bool(publish),
        "image": {"url": image_url, "altText": title[:250]} if image_url else None
    }
    data = shopify_graphql(mutation, {"article": article})
    result = data.get("articleCreate") or {}
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError(f"Shopify articleCreate rejected article: {errors}")
    return result.get("article")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Fetch feeds without writing to Shopify or state.")
    args = parser.parse_args()

    blog_id = env("SHOPIFY_BLOG_ID")
    if not args.dry_run and not blog_id:
        raise RuntimeError("Missing SHOPIFY_BLOG_ID GitHub variable.")
    feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    state = load_state()
    seen = state["items"]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=int(env("MAX_AGE_HOURS", "36")))
    max_items = max(1, min(10, int(env("MAX_ARTICLES_PER_RUN", "3"))))
    auto_publish = env("AUTO_PUBLISH", "false").lower() in {
        "1", "true", "yes", "on"
    }
    candidates = []
    candidate_keys = set()

    for config in feeds:
        name, url, category = config["name"], config["url"], config["category"]
        try:
            parsed = feedparser.parse(url)
            if parsed.bozo and not parsed.entries:
                logging.warning("Feed unavailable: %s (%s)", name, parsed.bozo_exception)
                continue
            for entry in parsed.entries[:40]:
                title = clean_text(entry.get("title", ""))
                source_url = canonical_url(entry.get("link", ""))
                if not title or not source_url:
                    continue
                key = story_key(source_url, title)
                if key in seen or key in candidate_keys:
                    continue
                candidate_keys.add(key)
                published = entry_datetime(entry)
                if published and published < cutoff:
                    if not args.dry_run:
                        seen[key] = {"status": "skipped_stale", "source": name, "seen_at": now.isoformat()}
                    continue
                description = clean_text(entry.get("summary", "") or entry.get("description", ""))
                risk = bool(HIGH_RISK.search(title + " " + description))
                candidates.append({
                    "key": key, "title": title, "url": source_url, "publisher": name,
                    "category": category, "description": description, "published": published,
                    "image_url": extract_image(entry), "video_html": extract_video_embed(entry), "risk": risk,
                })
        except Exception:
            logging.exception("Feed processing failed: %s", name)

    candidates.sort(key=lambda x: x["published"] or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    candidates = candidates[:max_items]
    logging.info("Found %d new candidate(s); dry_run=%s; auto_publish=%s", len(candidates), args.dry_run, auto_publish)

    failures = 0

    for item in candidates:
        logging.info("Candidate [%s] %s — %s", item["category"], item["title"], item["url"])
        if args.dry_run:
            continue
        try:
            # If RSS omits artwork/video metadata, check only the publisher's public page metadata.
            if not item.get("image_url") or not item.get("video_html"):
                media = fetch_article_media(item["url"])
                if not item.get("image_url") and media.get("image_url"):
                    item["image_url"] = media["image_url"]
                if not item.get("video_html") and media.get("video_html"):
                    item["video_html"] = media["video_html"]
            editorial = make_editorial(item["title"], item["publisher"], item["category"], item["description"], item.get("video_html", ""))
            # Publish automatically only when enabled and the story
            # has not triggered the high-risk review filter.
            # RSS metadata alone is not sufficient for publication.
            # Keep all generated articles as drafts pending human fact-checking.
            publish = False
            article = create_shopify_article(
                blog_id, editorial["title"], editorial["summary"], editorial["body"],
                item["url"], item["publisher"], item["category"], publish,
                item.get("image_url", "")
            )
            if not article:
                raise RuntimeError("Shopify returned no article and no userErrors.")
            seen[item["key"]] = {
                "status": "published" if publish else "draft",
                "shopify_article_id": article.get("id"),
                "title": article.get("title"),
                "source_url": item["url"],
                "publisher": item["publisher"],
                "risk_flag": item["risk"],
                "has_publisher_artwork": bool(item.get("image_url")),
                "has_embedded_video": bool(item.get("video_html")),
                "created_at": now.isoformat(),
            }
            logging.info("Created Shopify %s: %s (%s)", "article" if publish else "draft", article.get("title"), article.get("id"))
        except Exception as exc:
            failures += 1
            logging.exception("Failed to process %s: %s", item["title"], exc)
            if "Shopify authentication/permission failure" in str(exc):
                raise

    if not args.dry_run:
        save_state(state)

    if failures:
        raise RuntimeError(
            f"{failures} article(s) failed. See the log above; "
            "the workflow is marked failed so the problem is visible."
        )

    logging.info("Run finished.")