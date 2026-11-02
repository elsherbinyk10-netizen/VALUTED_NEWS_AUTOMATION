"""Extract playable video players directly from a cited publisher article.

Only article-body players from a conservative provider allowlist are accepted.
No search-result or title-similar videos are substituted for the publisher's own clip.
"""
import html
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "ValutedNewsPublisherMedia/1.0 (+source-attributed video restoration)"
PLAYER_HOSTS = (
    "youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com",
    "brightcove.net", "jwplayer.com", "jwplatform.com", "dailymotion.com",
    "wistia.net", "wistia.com", "kaltura.com", "theplatform.com",
    "vidyard.com", "sproutvideo.com", "cloudinary.com",
)


def _trusted_player_url(url):
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        return False
    trusted = any(host == domain or host.endswith("." + domain) for domain in PLAYER_HOSTS)
    path = parsed.path.lower()
    return trusted and ("/embed" in path or "/player" in path or "/video" in path
                        or "/iframe" in path or host.startswith(("player.", "players.", "embed.")))


def _frame(src, title):
    return (
        '<div class="valuted-news-video" style="position:relative;width:100%;aspect-ratio:16/9;margin:24px 0;overflow:hidden">'
        '<iframe src="' + html.escape(src, quote=True) + '" title="' +
        html.escape(title or "Original publisher video", quote=True) +
        '" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" '
        'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
        'allowfullscreen style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe></div>'
    )


def fetch_publisher_video(source_url, timeout=(4, 10)):
    """Return a playable player found inside the cited article, or an empty string."""
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
        # Prefer the publisher's own article-body iframe; ignore ads and page chrome.
        for iframe in root.find_all("iframe", src=True):
            src = urljoin(response.url, str(iframe.get("src") or "").strip())
            if not _trusted_player_url(src):
                continue
            try:
                check = requests.get(src, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
                                     timeout=timeout, allow_redirects=True, stream=True)
                try:
                    if check.ok and ("html" in check.headers.get("Content-Type", "").lower()
                                     or "javascript" in check.headers.get("Content-Type", "").lower()):
                        return _frame(src, str(iframe.get("title") or "Original publisher video"))
                finally:
                    check.close()
            except requests.RequestException:
                continue
        # Native HTML5 publisher-hosted video.
        for video in root.find_all("video"):
            sources = video.find_all("source", src=True)
            if not sources and video.get("src"):
                sources = [video]
            for source in sources:
                src = urljoin(response.url, str(source.get("src") or "").strip())
                parsed = urlparse(src)
                media_type = str(source.get("type") or "").lower()
                if parsed.scheme != "https" or not parsed.hostname:
                    continue
                if not (media_type.startswith("video/") or parsed.path.lower().endswith((".mp4", ".webm", ".ogg"))):
                    continue
                try:
                    check = requests.get(src, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"},
                                         timeout=timeout, allow_redirects=True, stream=True)
                    try:
                        if check.ok and check.headers.get("Content-Type", "").lower().startswith("video/"):
                            return ('<video controls preload="metadata" playsinline style="display:block;width:100%;height:auto;max-width:100%;margin:24px 0">'
                                    '<source src="' + html.escape(src, quote=True) + '"></video>')
                    finally:
                        check.close()
                except requests.RequestException:
                    continue
    except requests.RequestException:
        return ""
    return ""
