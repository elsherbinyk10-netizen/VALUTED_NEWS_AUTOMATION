"""Inspect official Formula 1 and Sky Sports video pages for embeddable player metadata."""
import json
import re
import requests
from bs4 import BeautifulSoup

TARGETS = {
    "formula1": "https://www.formula1.com/en/video/this-is-nine-years-of-development-toto-wolff-on-antonellis-title-journey.1880716992673506519",
    "sky_sports": "https://www.skysports.com/f1/video/13606892/mexico-city-gp-toto-wolff-jubilant-after-kimi-antonelli-wins-maiden-world-title",
}

for label, url in TARGETS.items():
    print(f"\n=== {label} ===")
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ValutedNewsMediaAudit/1.0)", "Accept": "text/html,application/xhtml+xml"},
            timeout=(5, 15),
            allow_redirects=True,
        )
        print("status=", response.status_code, "final_url=", response.url)
        print("content_type=", response.headers.get("Content-Type", ""))
        print("x_frame_options=", response.headers.get("X-Frame-Options", ""))
        print("csp=", response.headers.get("Content-Security-Policy", "")[:500])
        if not response.ok or "html" not in response.headers.get("Content-Type", "").lower():
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup.find_all("meta"):
            key = str(tag.get("property") or tag.get("name") or "").lower()
            if key in {"og:video", "og:video:url", "og:video:secure_url", "twitter:player"}:
                print("META_PLAYER", key, tag.get("content"))
        for script_tag in soup.find_all("script", type=re.compile(r"ld\\+json", re.I)):
            raw = script_tag.string or script_tag.get_text(" ", strip=True)
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    if str(item.get("@type", "")).lower() == "videoobject":
                        print("VIDEO_OBJECT", json.dumps({k:item.get(k) for k in ("name","embedUrl","contentUrl","thumbnailUrl")}, ensure_ascii=False))
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
                elif isinstance(item, list):
                    stack.extend(item)
        for iframe in soup.find_all("iframe", src=True):
            print("IFRAME", iframe.get("src"))
        for video in soup.find_all("video"):
            print("VIDEO", video.get("src"), [s.get("src") for s in video.find_all("source", src=True)])
        for key in ("videoId", "video_id", "brightcove", "jwplayer", "player.sky"):
            if key.lower() in response.text.lower():
                print("PAGE_MARKER", key)
        patterns = (
            r"players\\.brightcove\\.net/[^\\s\\\"']+",
            r"videoId\\s*[:=]\\s*[\\\"']([^\\\"']+)",
            r"accountId\\s*[:=]\\s*[\\\"']([^\\\"']+)",
            r"\\bvideo_id\\b\\s*[:=]\\s*[\\\"']([^\\\"']+)",
            r"brightcove[^\\s<>]{0,300}",
        )
        for pattern in patterns:
            matches = re.findall(pattern, response.text, re.I)
            for match in matches[:12]:
                print("PLAYER_PATTERN", pattern, match[:600] if isinstance(match, str) else match)
        for marker in ("BRIGHTCOVE_ACCOUNTID", "BRIGHTCOVE_ATOMPLAYERID", "BRIGHTCOVE_HUBPLAYERID", "videoId", "brightcove-"):
            start = 0
            shown = 0
            while shown < 5:
                pos = response.text.lower().find(marker.lower(), start)
                if pos < 0:
                    break
                print("PLAYER_CONTEXT", marker, response.text[max(0,pos-300):pos+700].replace("\\n"," ")[:1000])
                start = pos + len(marker)
                shown += 1
    except requests.RequestException as error:
        print("REQUEST_ERROR", repr(error))
