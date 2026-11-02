"""Extract playable video players directly from a cited publisher article.

Only article-body players or explicit VideoObject/Open Graph video metadata on the
cited publisher page are accepted. No search-result or title-similar videos are used.
"""
import html
import json
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "ValutedNewsPublisherMedia/1.1 (+source-attributed video restoration)"
PLAYER_HOSTS = (
    "youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com",
    "brightcove.net", "jwplayer.com", "jwplatform.com", "dailymotion.com",
    "wistia.net", "wistia.com", "kaltura.com", "theplatform.com",
    "vidyard.com", "sproutvideo.com", "cloudinary.com", "ooyala.com",
    "video.ibm.com", "ustream.tv",
)


def _trusted_player_url(url, source_host=""):
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        return False
    trusted = any(host == domain or host.endswith("." + domain) for domain in PLAYER_HOSTS)
    publisher_host = (source_host or "").lower().rstrip(".")
    same_publisher = bool(publisher_host and (host == publisher_host or host.endswith("." + publisher_host)))
    path = parsed.path.lower()
    player_path = any(part in path for part in ("/embed", "/player", "/video", "/iframe", "/media"))
    return (trusted and (player_path or host.startswith(("player.", "players.", "embed.")))) or (same_publisher and player_path)


def _frame(src, title):
    return (
        '<div class="valuted-news-video" style="position:relative;width:100%;aspect-ratio:16/9;margin:24px 0;overflow:hidden">'
        '<iframe src="' + html.escape(src, quote=True) + '" title="' +
        html.escape(title or "Original publisher video", quote=True) +
        '" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" '
        'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
        'allowfullscreen style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe></div>'
    )


def _video_object_urls(value):
    """Yield explicit embed/content URLs only from VideoObject structured data."""
    if isinstance(value, list):
        for item in value:
            yield from _video_object_urls(item)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if any(str(item).lower() == "videoobject" for item in types):
            for key in ("embedUrl", "contentUrl"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate:
                    yield candidate
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _video_object_urls(child)


def fetch_publisher_video(source_url, timeout=(4, 10)):
    """Return a playable player explicitly published with the cited article, or empty."""
    parsed_source = urlparse(source_url or "")
    if parsed_source.scheme != "https" or not parsed_source.hostname:
        return ""
    try:
        response = requests.get(source_url, headers={"User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml"}, timeout=timeout, allow_redirects=True)
        if not response.ok or "html" not in response.headers.get("Content-Type", "").lower():
            return ""
        soup = BeautifulSoup(response.text, "html.parser")
        root = soup.find("article") or soup.find("main")
        if root is None:
            return ""

        candidates = []
        # Open Graph / Twitter player metadata is an explicit publisher declaration.
        for tag in soup.find_all("meta"):
            key = str(tag.get("property") or tag.get("name") or "").lower()
            if key in {"og:video", "og:video:url", "og:video:secure_url", "twitter:player"}:
                value = tag.get("content")
                if value:
                    candidates.append((urljoin(response.url, str(value)), str(tag.get("name") or key)))

        # Structured data commonly exposes the exact embedded clip even when the
        # publisher builds its player client-side and has no iframe in static HTML.
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string or script.get_text() or "")
            except (TypeError, ValueError):
                continue
            for value in _video_object_urls(payload):
                candidates.append((urljoin(response.url, value), "Original publisher video"))

        # Prefer the article body's actual iframe over metadata candidates.
        for iframe in root.find_all("iframe", src=True):
            src = urljoin(response.url, str(iframe.get("src") or "").strip())
            candidates.insert(0, (src, str(iframe.get("title") or "Original publisher video")))

        seen = set()
        for src, title in candidates:
            if src in seen or not _trusted_player_url(src, urlparse(response.url).hostname or ""):
                continue
            seen.add(src)
            try:
                check = requests.get(src, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
                                     timeout=timeout, allow_redirects=True, stream=True)
                try:
                    content_type = check.headers.get("Content-Type", "").lower()
                    if check.ok and ("html" in content_type or "javascript" in content_type or "json" in content_type):
                        return _frame(src, title)
                finally:
                    check.close()
            except requests.RequestException:
                continue
    except requests.RequestException:
        return ""
    return ""
