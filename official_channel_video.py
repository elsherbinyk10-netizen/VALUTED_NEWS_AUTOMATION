"""Story-matched video discovery from explicitly verified publisher YouTube channels."""
import html
import re
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

# Channel IDs are fixed allowlisted identities, not names inferred from search results.
OFFICIAL_CHANNELS = {
    "bbc.co.uk": ("BBC News", "UC16niRr50-MSBwiO3YDb3RA"),
    "bbc.com": ("BBC News", "UC16niRr50-MSBwiO3YDb3RA"),
    "nasa.gov": ("NASA", "UCLA_DiR1FfKNvjuUpBHmylQ"),
}
USER_AGENT = "ValutedNewsOfficialVideoDiscovery/1.0"


def _publisher_channel(source_url):
    host = (urlparse(source_url or "").hostname or "").lower().removeprefix("www.")
    for domain, identity in OFFICIAL_CHANNELS.items():
        if host == domain or host.endswith("." + domain):
            return identity
    return None


def _playable_youtube_video(video_id, timeout=(3, 7)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(video_id or "")):
        return False
    try:
        metadata = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": "https://www.youtube.com/watch?v=" + video_id, "format": "json"},
            headers={"User-Agent": USER_AGENT}, timeout=timeout,
        )
        payload = metadata.json() if metadata.ok else {}
        if not (metadata.ok and isinstance(payload, dict) and payload.get("title")):
            return False
        player = requests.get(
            "https://www.youtube.com/embed/" + video_id,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ValutedNewsMedia/1.0)",
                     "Accept": "text/html,application/xhtml+xml",
                     "Referer": "https://valutednews.com/"},
            timeout=(4, 9), allow_redirects=True,
        )
        if not player.ok:
            return False
        markup = str(getattr(player, "text", "") or "").lower()
        blocked = ("video unavailable", "this video is unavailable", "private video",
                   "embedding this video is disabled", "embedding disabled",
                   "playback on other websites has been disabled",
                   "uploader has not made this video available",
                   "video is not available in your country")
        return not any(marker in markup for marker in blocked)
    except (requests.RequestException, ValueError):
        return False


def fetch_official_channel_video(story_title, source_url):
    """Return an embed only when the cited publisher's own official channel has a matching playable clip."""
    identity = _publisher_channel(source_url)
    if not identity:
        return ""
    channel_name, channel_id = identity
    terms = set(re.findall(r"[a-z0-9]{3,}", str(story_title or "").lower()))
    stop = {"the", "and", "for", "with", "from", "that", "this", "after", "before",
            "latest", "news", "update", "says", "said", "will", "into", "about"}
    terms -= stop
    if len(terms) < 2:
        return ""
    feed_url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + channel_id
    try:
        response = requests.get(feed_url, headers={"User-Agent": USER_AGENT}, timeout=(3, 7))
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except (requests.RequestException, Exception):
        return ""
    ranked = []
    for entry in parsed.entries[:25]:
        entry_channel = str(entry.get("yt_channelid") or entry.get("channel_id") or "")
        if entry_channel and entry_channel != channel_id:
            continue
        video_id = str(entry.get("yt_videoid") or "")
        if not video_id:
            link = str(entry.get("link") or "")
            match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", link)
            video_id = match.group(1) if match else ""
        title = str(entry.get("title") or "")
        words = set(re.findall(r"[a-z0-9]{3,}", title.lower())) - stop
        overlap = len(terms & words)
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) and overlap >= 2:
            ranked.append((overlap, video_id, title))
    for _, video_id, title in sorted(ranked, reverse=True):
        if not _playable_youtube_video(video_id):
            continue
        safe_id = html.escape(video_id, quote=True)
        safe_title = html.escape(title or (channel_name + " official video"), quote=True)
        return (
            '<div class="valuted-news-video" style="position:relative;width:100%;aspect-ratio:16/9;margin:24px 0">'
            '<iframe src="https://www.youtube-nocookie.com/embed/' + safe_id +
            '" title="' + safe_title + '" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" '
            'allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
            'allowfullscreen style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe></div>'
            '<p class="vn-video-credit">Official video: ' + html.escape(channel_name) + '</p>'
        )
    return ""
