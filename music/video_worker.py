#!/usr/bin/env python3
"""VALUTED MUSIC official music-video publisher. Fails closed without verified channel IDs and secrets."""
import os, sys, json, re, html
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import requests, feedparser
from bs4 import BeautifulSoup

EXPECTED_NAME = "VALUTED MUSIC"
EXPECTED_HOST = "valutedmusic.site"
SHOP = os.getenv("SHOPIFY_ADMIN_DOMAIN", "").strip()
TOKEN = os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", "")
YOUTUBE_KEY = os.getenv("YOUTUBE_DATA_API_KEY", "")
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2026-10")
BLOG_HANDLE = "news"
MAX_VIDEOS = min(5, max(0, int(os.getenv("MAX_VIDEOS_PER_RUN", "5"))))
MAX_AGE_HOURS = int(os.getenv("MAX_VIDEO_AGE_HOURS", "72"))
AUTO_PUBLISH = os.getenv("AUTO_PUBLISH", "true").lower() == "true"
BASE = "https://www.googleapis.com/youtube/v3"
session = requests.Session()
session.headers["User-Agent"] = "VALUTED-MUSIC-VideoBot/1.0 (+https://valutedmusic.site)"

def log(message): print(message, flush=True)
def gql(query, variables=None):
    r = session.post(f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json",
        headers={"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}}, timeout=35)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"): raise RuntimeError("Shopify GraphQL error: " + json.dumps(data["errors"])[:1000])
    return data["data"]

def guard():
    if not TOKEN or not SHOP.endswith(".myshopify.com") or not YOUTUBE_KEY:
        raise RuntimeError("Missing Music Shopify token/domain or YOUTUBE_DATA_API_KEY. No publishing.")
    data = gql("""query Guard { shop { name primaryDomain { host } } blogs(first:50) { edges { node { id handle } } } }""")
    shop = data["shop"]
    if shop["name"].strip().casefold() != EXPECTED_NAME.casefold() or shop["primaryDomain"]["host"].lower() != EXPECTED_HOST:
        log("WRONG SHOP CONNECTED — NO CHANGES MADE.")
        sys.exit(0)
    blog = next((x["node"] for x in data["blogs"]["edges"] if x["node"]["handle"] == BLOG_HANDLE), None)
    if not blog: raise RuntimeError("Expected existing news blog missing. No writes.")
    log(f"SHOP VERIFIED: {shop['name']} | {EXPECTED_HOST}; blog={BLOG_HANDLE}")
    return blog["id"]

def yt(path, params):
    params = dict(params, key=YOUTUBE_KEY)
    r = session.get(f"{BASE}/{path}", params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if payload.get("error"): raise RuntimeError(payload["error"].get("message", "YouTube API error"))
    return payload

def channel_allowlist():
    with open("music/official_channels.json", encoding="utf-8") as f:
        config = json.load(f)
    channels = config.get("channels", [])
    clean = []
    for item in channels:
        cid = str(item.get("channel_id", "")).strip()
        if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", cid):
            clean.append({"channel_id": cid, "label": str(item.get("label", ""))[:100]})
    if not clean: raise RuntimeError("No manually verified official YouTube channel IDs in music/official_channels.json. Refusing unverified uploads.")
    return clean

def collect(channels):
    now = datetime.now(timezone.utc)
    candidates = []
    for channel in channels:
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel['channel_id']}")
        for entry in feed.entries[:20]:
            video_id = entry.get("yt_videoid") or entry.get("id", "").rsplit(":", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id): continue
            published = entry.get("published")
            try: dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except Exception: continue
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            if now - dt > timedelta(hours=MAX_AGE_HOURS) or dt > now + timedelta(hours=1): continue
            candidates.append({"video_id": video_id, "channel_id": channel["channel_id"], "channel_label": channel["label"], "published": dt})
    unique = {x["video_id"]: x for x in candidates}
    if not unique: return []
    ids = ",".join(unique)
    verified = yt("videos", {"part":"snippet,status,contentDetails", "id":ids, "maxResults":50}).get("items", [])
    results = []
    for video in verified:
        vid = video["id"]; sn = video["snippet"]; st = video["status"]
        expected = unique.get(vid)
        if not expected or sn.get("channelId") != expected["channel_id"]: continue
        if st.get("privacyStatus") != "public" or st.get("embeddable") is not True: continue
        thumbs = sn.get("thumbnails", {})
        thumb = next((thumbs[k]["url"] for k in ("maxres","standard","high","medium","default") if k in thumbs), "")
        if not thumb.startswith("https://"): continue
        title = html.unescape(sn.get("title", "")).strip()
        description = html.unescape(sn.get("description", "")).strip()
        duration = video.get("contentDetails", {}).get("duration", "")
        # Keep the catalogue focused on full-length official music videos, not label promos,
        # interviews, corporate clips, lyric-only uploads or Shorts.
        if not title or len(description) < 40: continue
        if re.search(r"\b(shorts?|teaser|trailer|behind the scenes|interview|lyrics?|audio only|visuali[sz]er)\\b", title, re.I): continue
        if not re.search(r"\b(official music video|official video|music video|official video clip|official clip)\\b", title, re.I): continue
        if re.search(r"#shorts?\\b", title + " " + description, re.I): continue
        results.append({"video_id":vid,"title":title,"description":description[:1200],"channel_id":sn["channelId"],
            "channel_title":sn.get("channelTitle",""),"thumbnail":thumb,"published":expected["published"],
            "duration":duration,"embed_url":f"https://www.youtube-nocookie.com/embed/{vid}",
            "watch_url":f"https://www.youtube.com/watch?v={vid}"})
    return sorted(results,key=lambda x:x["published"],reverse=True)

def already_exists(blog_id, video):
    q="""query Existing($id:ID!,$after:String){blog(id:$id){articles(first:100,after:$after){edges{node{id body tags}}pageInfo{hasNextPage endCursor}}}}"""
    cursor=None
    while True:
        page=gql(q,{"id":blog_id,"after":cursor})["blog"]["articles"]
        for edge in page["edges"]:
            node=edge["node"]
            if video["video_id"] in (node.get("body") or "") or video["video_id"] in (node.get("tags") or []): return True
        info=page["pageInfo"]
        if not info["hasNextPage"]: return False
        cursor=info["endCursor"]

def publish(blog_id, video):
    if already_exists(blog_id, video):
        log(f"DUPLICATE SKIP: {video['title']}"); return False
    description = re.sub(r"<[^>]+>", " ", video["description"])
    description = re.sub(r"\s+", " ", description).strip()
    body = f'''<p>{html.escape(description[:700])}</p>
<div class="vm-official-video" style="position:relative;aspect-ratio:16/9;max-width:100%;background:#08080d">
<iframe src="{html.escape(video["embed_url"], quote=True)}" title="{html.escape(video["title"], quote=True)}" loading="eager" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin" style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>
</div>
<p><strong>Official source:</strong> <a href="{html.escape(video["watch_url"], quote=True)}" rel="nofollow noopener" target="_blank">{html.escape(video["channel_title"])}</a></p>
<p>Video is hosted by YouTube. Playback, regional availability, captions and advertising are controlled by YouTube and the rights holder.</p>'''
    handle = re.sub(r"[^a-z0-9-]+","-",video["title"].lower()).strip("-")[:130] + "-" + video["video_id"].lower()
    tags = ["official-music-video", "music-video", video["video_id"]]
    mutation = """mutation Create($blog:ID!,$article:ArticleCreateInput!){articleCreate(blogId:$blog,article:$article){article{id title handle isPublished}userErrors{field message}}}"""
    article = {"title":video["title"],"handle":handle,"body":body,"tags":tags,"isPublished":AUTO_PUBLISH,
        "summary":description[:240],"seo":{"title":(video["title"]+" | VALUTED MUSIC")[:70],"description":description[:300]}}
    if not AUTO_PUBLISH:
        log(f"DRY RUN: {video['title']}"); return False
    result=gql(mutation,{"blog":blog_id,"article":article})["articleCreate"]
    if result["userErrors"]: raise RuntimeError(json.dumps(result["userErrors"]))
    created=result["article"]
    # Article metafields power VideoObject JSON-LD in the article template.
    fields=[
      {"ownerId":created["id"],"namespace":"custom","key":"video_id","type":"single_line_text_field","value":video["video_id"]},
      {"ownerId":created["id"],"namespace":"custom","key":"video_embed_url","type":"url","value":video["embed_url"]},
      {"ownerId":created["id"],"namespace":"custom","key":"video_thumbnail","type":"url","value":video["thumbnail"]},
      {"ownerId":created["id"],"namespace":"custom","key":"video_channel","type":"single_line_text_field","value":video["channel_title"]},
      {"ownerId":created["id"],"namespace":"custom","key":"video_upload_date","type":"date_time","value":video["published"].isoformat()},
      {"ownerId":created["id"],"namespace":"custom","key":"video_duration","type":"single_line_text_field","value":video["duration"]},
      {"ownerId":created["id"],"namespace":"custom","key":"video_description","type":"single_line_text_field","value":description[:300]},
    ]
    saved=gql("""mutation SetVideoMetadata($metafields:[MetafieldsSetInput!]!){metafieldsSet(metafields:$metafields){metafields{key value}userErrors{field message}}}""",{"metafields":fields})["metafieldsSet"]
    if saved["userErrors"]: raise RuntimeError("Article created but VideoObject metadata failed; manual repair required: "+json.dumps(saved["userErrors"]))
    log(f"PUBLISHED VIDEO: {created['title']} | /blogs/{BLOG_HANDLE}/{created['handle']} | official channel allowlist + embeddable/public verified")
    return True

def main():
    blog_id=guard()
    channels=channel_allowlist()
    candidates=collect(channels)
    log(f"OFFICIAL VIDEO CANDIDATES VERIFIED: {len(candidates)}")
    count=0
    for video in candidates:
        if count >= MAX_VIDEOS: break
        try:
            if publish(blog_id,video): count += 1
        except Exception as exc:
            log(f"HOLD/FAIL {video.get('title','(untitled)')}: {exc}")
    log(f"VIDEO RUN COMPLETE: published={count}; max={MAX_VIDEOS}; no theme/domain changes.")

if __name__=="__main__":
    try: main()
    except SystemExit: raise
    except Exception as exc:
        log(f"VIDEO WORKFLOW FAILED CLOSED: {exc}")
        sys.exit(1)
