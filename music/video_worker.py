#!/usr/bin/env python3
"""VALUTED MUSIC official video publisher with staged, fail-closed publishing."""
import os, sys, json, re, html
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import requests, feedparser
from bs4 import BeautifulSoup

EXPECTED_NAME="VALUTED MUSIC"
EXPECTED_HOST="valutedmusic.site"
EXPECTED_SHOP="0k31v6-th.myshopify.com"
BLOG_HANDLE="news"
SHOP=os.getenv("SHOPIFY_ADMIN_DOMAIN","").strip().lower()
TOKEN=os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN","").strip()
API_VERSION=os.getenv("SHOPIFY_API_VERSION","2026-10")
MAX_VIDEOS=min(5,max(0,int(os.getenv("MAX_VIDEOS_PER_RUN","2"))))
MAX_AGE_HOURS=max(1,int(os.getenv("MAX_VIDEO_AGE_HOURS","72")))
AUTO_PUBLISH=os.getenv("AUTO_PUBLISH","false").lower()=="true"
SESSION=requests.Session()
SESSION.headers["User-Agent"]="VALUTED-MUSIC-VideoBot/2.0 (+https://valutedmusic.site)"

def log(message): print(message,flush=True)

def gql(query,variables=None):
    r=SESSION.post(f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json",
        headers={"X-Shopify-Access-Token":TOKEN,"Content-Type":"application/json"},
        json={"query":query,"variables":variables or {}},timeout=35)
    r.raise_for_status(); data=r.json()
    if data.get("errors"): raise RuntimeError("Shopify GraphQL error: "+json.dumps(data["errors"])[:1200])
    return data["data"]

def guard():
    if not TOKEN: raise RuntimeError("Missing Music-only Shopify token. No writes.")
    if SHOP!=EXPECTED_SHOP: raise RuntimeError("SHOPIFY_ADMIN_DOMAIN is not the configured VALUTED MUSIC shop. No writes.")
    data=gql("""query Guard { shop { name primaryDomain { host } } blogs(first:50) { edges { node { id handle } } } }""")
    shop=data["shop"]
    if shop["name"].strip().casefold()!=EXPECTED_NAME.casefold() or (shop.get("primaryDomain") or {}).get("host","").lower()!=EXPECTED_HOST:
        raise RuntimeError("Wrong Shopify identity or primary domain. No changes made.")
    blog=next((e["node"] for e in data["blogs"]["edges"] if e["node"]["handle"]==BLOG_HANDLE),None)
    if not blog: raise RuntimeError("Expected VALUTED MUSIC news blog is missing. No writes.")
    log(f"SHOP VERIFIED: {EXPECTED_NAME} / {EXPECTED_HOST} / blog={BLOG_HANDLE}")
    return blog["id"]

def channel_allowlist(path="music/official_channels.json"):
    with open(path,encoding="utf-8") as f: config=json.load(f)
    channels=[]; seen=set()
    for item in config.get("channels",[]):
        cid=str(item.get("channel_id","")).strip(); label=str(item.get("label","")).strip()[:100]
        if re.fullmatch(r"UC[A-Za-z0-9_-]{22}",cid) and label and cid not in seen:
            channels.append({"channel_id":cid,"label":label}); seen.add(cid)
    if not channels: raise RuntimeError("No manually verified official channel IDs. Refusing unverified uploads.")
    return channels

def parse_published(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (TypeError,ValueError):return None

def duration_seconds(value):
    m=re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",value or "")
    if not m:return 0
    h,mi,s=(int(x or 0) for x in m.groups())
    return h*3600+mi*60+s

EXCLUDED_TITLE=re.compile(r"\b(shorts?|teaser|trailer|behind the scenes|interview|audio only|visuali[sz]er|dance practice|reaction|live session)\b",re.I)
OFFICIAL_VIDEO_TITLE=re.compile(r"\b(official music video|official video|music video|official video clip|official clip|official lyrics? video|official audio)\b",re.I)

def classify_video_type(title):
    title=html.unescape(title or "").strip()
    if not title or EXCLUDED_TITLE.search(title) or re.search(r"#shorts?\b",title,re.I): return None
    if re.search(r"\bofficial\s+lyrics?\s+video\b",title,re.I): return "official-lyrics-video"
    if re.search(r"\bofficial\s+audio\b",title,re.I): return "official-audio"
    if OFFICIAL_VIDEO_TITLE.search(title): return "official-music-video"
    return None

def verify_thumbnail(url):
    """Require a reachable HTTPS image; never publish a broken or non-image thumbnail."""
    try:
        response=SESSION.get(url,stream=True,timeout=15,headers={"Range":"bytes=0-0"})
        try:
            return response.status_code in (200,206) and response.headers.get("Content-Type","").lower().startswith("image/")
        finally:
            response.close()
    except requests.RequestException:
        return False

def verify_embed(url):
    """Reject obvious unavailable/disabled embeds using the public player page."""
    try:
        response=SESSION.get(url,timeout=20,headers={"User-Agent":"Mozilla/5.0"})
        try:
            if response.status_code != 200:
                return False
            page=response.text[:250000].lower()
            return "video unavailable" not in page and "playback on other websites has been disabled" not in page
        finally:
            response.close()
    except requests.RequestException:
        return False

def public_player_duration(page, expected_video_id, expected_channel_id):
    """Return duration only when YouTube's public player confirms the exact public video and channel."""
    match=re.search(r"ytInitialPlayerResponse\s*=\s*(\{.*?\})\s*;",page or "",re.S)
    if not match:
        return 0
    try:
        player=json.loads(match.group(1))
    except (TypeError,ValueError):
        return 0
    details=player.get("videoDetails") or {}
    status=(player.get("playabilityStatus") or {}).get("status")
    if status!="OK" or details.get("videoId")!=expected_video_id:
        return 0
    if details.get("channelId")!=expected_channel_id or details.get("isPrivate") is True:
        return 0
    if details.get("isLiveContent") is True:
        return 0
    try:
        duration=int(details.get("lengthSeconds") or 0)
    except (TypeError,ValueError):
        return 0
    return duration if duration>=60 else 0


def is_official_music_video(title,description="",duration=""):
    title=html.unescape(title or "").strip()
    description=html.unescape(description or "").strip()
    if not classify_video_type(title):return False
    if re.search(r"#shorts?\b",title+" "+description,re.I):return False
    return duration_seconds(duration)>=60

def collect(channels,now=None):
    """Use public channel RSS plus YouTube's no-key oEmbed metadata endpoint."""
    now=now or datetime.now(timezone.utc); results=[]
    for channel in channels:
        url="https://www.youtube.com/feeds/videos.xml?channel_id="+channel["channel_id"]
        feed=feedparser.parse(url)
        if getattr(feed,"bozo",False) and not feed.entries:
            log("RSS unavailable: "+channel["label"]); continue
        for entry in feed.entries[:25]:
            vid=entry.get("yt_videoid") or entry.get("id","").rsplit(":",1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid):continue
            published=parse_published(entry.get("published"))
            if not published:continue
            age=now-published
            if age>timedelta(hours=MAX_AGE_HOURS) or age<timedelta(hours=-1):continue
            title=html.unescape(entry.get("title","")).strip()
            kind=classify_video_type(title)
            if not kind:continue
            watch=f"https://www.youtube.com/watch?v={vid}"
            try:
                watch_page=SESSION.get(watch,timeout=20,headers={"User-Agent":"Mozilla/5.0"})
                watch_page.raise_for_status()
                duration=public_player_duration(watch_page.text,vid,channel["channel_id"])
                if not duration:
                    log(f"HOLD video {vid}: public player did not confirm a full-length public upload from the allowlisted channel")
                    continue
                response=SESSION.get("https://www.youtube.com/oembed",
                    params={"url":watch,"format":"json"},timeout=20)
                response.raise_for_status()
                meta=response.json()
                thumbnail=meta.get("thumbnail_url","")
                if not meta.get("title") or not meta.get("author_name"):continue
                if html.unescape(meta.get("title","")).strip()!=title:continue
                if not is_official_music_video(title,entry.get("summary",""),f"PT{duration}S"):
                    log(f"HOLD video {vid}: title or duration did not pass the official full-length video gate")
                    continue
                if not verify_thumbnail(thumbnail):continue
                embed_url=f"https://www.youtube-nocookie.com/embed/{vid}"
                if not verify_embed(embed_url):
                    log(f"HOLD video {vid}: embed endpoint check failed")
                    continue
                # Source channel is manually allowlisted; thumbnail and player endpoint must pass.
                results.append({"video_id":vid,"title":title,
                    "description":BeautifulSoup(entry.get("summary",""),"html.parser").get_text(" ",strip=True)[:1800],
                    "channel_id":channel["channel_id"],"channel_title":meta["author_name"][:255],
                    "thumbnail":thumbnail,"published":published,"embed_url":embed_url,
                    "watch_url":watch,"video_type":kind,"duration":f"PT{duration}S",
                    "verification":"allowlisted channel RSS + public player channel/id/duration check + oEmbed + reachable image + embed endpoint"})
            except Exception as error:
                log(f"HOLD video {vid}: no-key metadata check failed ({error})")
    return sorted(results,key=lambda x:x["published"],reverse=True)

def already_exists(blog_id,video_id):
    q="""query Existing($id:ID!,$after:String){blog(id:$id){articles(first:100,after:$after){edges{node{id body tags isPublished}}pageInfo{hasNextPage endCursor}}}}"""
    cursor=None
    while True:
        page=gql(q,{"id":blog_id,"after":cursor})["blog"]["articles"]
        for edge in page["edges"]:
            node=edge["node"]
            if video_id in (node.get("tags") or []) or video_id in (node.get("body") or ""):return node
        info=page["pageInfo"]
        if not info["hasNextPage"]:return None
        cursor=info["endCursor"]

def build_article(video):
    description=BeautifulSoup(video["description"],"html.parser").get_text(" ",strip=True)
    description=re.sub(r"\s+"," ",description).strip()
    title=html.escape(video["title"],quote=True)
    channel=html.escape(video["channel_title"])
    kind=video.get("video_type") or "official-music-video"
    label={"official-music-video":"official music video","official-lyrics-video":"official lyrics video","official-audio":"official audio"}[kind]
    base=re.sub(r"[^a-z0-9-]+","-",video["title"].lower()).strip("-")[:120]
    handle="{}-{}".format(base,video["video_id"].lower()).strip("-")
    summary=("Watch {} — the {} from {}. ".format(video["title"],label,video["channel_title"])+description)[:300]
    canonical="https://{}/blogs/{}/{}".format(EXPECTED_HOST,BLOG_HANDLE,handle)
    schema={"@context":"https://schema.org","@type":"VideoObject","name":video["title"],
      "description":description[:1000],"thumbnailUrl":[video["thumbnail"]],
      "uploadDate":video["published"].date().isoformat(),
      "duration":video.get("duration"),
      "embedUrl":video["embed_url"],"publisher":{"@type":"Organization","name":video["channel_title"]},
      "mainEntityOfPage":canonical}
    schema_json=json.dumps(schema,ensure_ascii=False,separators=(",",":")).replace("<","\\u003c")
    heading={"official-music-video":"Watch the official music video","official-lyrics-video":"Watch the official lyrics video","official-audio":"Listen to the official audio"}[kind]
    body=f'''<p>{html.escape(description[:900])}</p>
<h2>{heading}</h2>
<div class="vm-official-video" style="position:relative;aspect-ratio:16/9;max-width:100%;background:#08080d">
<iframe src="{video["embed_url"]}" title="{title}" loading="eager" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin" style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>
</div>
<p><strong>Official source:</strong> <a href="{video["watch_url"]}" rel="nofollow noopener" target="_blank">Watch on YouTube — {channel}</a></p>
<p>VALUTED MUSIC embeds the official player. The recording remains hosted by YouTube and controlled by the artist and rights holder. Playback, regional availability, captions and advertising are subject to YouTube and the rights holder.</p>
<script type="application/ld+json">{schema_json}</script>'''
    metafields=[
      {"namespace":"global","key":"title_tag","type":"single_line_text_field","value":("Watch {} | VALUTED MUSIC".format(video["title"]))[:70]},
      {"namespace":"global","key":"description_tag","type":"single_line_text_field","value":summary[:320]},
      {"namespace":"custom","key":"video_id","type":"single_line_text_field","value":video["video_id"]},
      {"namespace":"custom","key":"video_embed_url","type":"url","value":video["embed_url"]},
      {"namespace":"custom","key":"video_thumbnail","type":"url","value":video["thumbnail"]},
      {"namespace":"custom","key":"video_channel","type":"single_line_text_field","value":video["channel_title"][:255]},
      {"namespace":"custom","key":"video_upload_date","type":"date_time","value":video["published"].isoformat()},
      {"namespace":"custom","key":"video_duration","type":"single_line_text_field","value":video.get("duration","")},
      {"namespace":"custom","key":"video_description","type":"single_line_text_field","value":description[:255]}]
    return {"author":{"name":"VALUTED MUSIC Video Desk"},"title":video["title"][:255],
      "handle":handle,"body":body,"summary":summary,
      "tags":[kind,"music-video",video["video_id"],"official-source"],
      "image":{"url":video["thumbnail"],"altText":"{} — official video thumbnail".format(video["title"])[:512]},
      "metafields":metafields,"isPublished":True}

def create_draft(blog_id,video):
    existing=already_exists(blog_id,video["video_id"])
    if existing:
        log(f"DUPLICATE SKIP: {video['title']} (published={existing['isPublished']})");return False
    if not AUTO_PUBLISH:
        log("DRY RUN — RSS/oEmbed candidate only; no publishing: "+video["title"]);return False
    mutation="""mutation CreateMusicVideo($article:ArticleCreateInput!){articleCreate(article:$article){article{id title handle isPublished image{altText originalSrc} metafields(first:20){edges{node{namespace key value}}}}userErrors{field message}}}"""
    result=gql(mutation,{"article":dict(build_article(video),blogId=blog_id)})["articleCreate"]
    if result["userErrors"]:raise RuntimeError("Shopify article creation rejected: "+json.dumps(result["userErrors"]))
    created=result["article"]
    expected={"video_id","video_embed_url","video_thumbnail","video_channel","video_upload_date","video_duration","video_description","title_tag","description_tag"}
    actual={e["node"]["key"] for e in created["metafields"]["edges"]}
    if not expected.issubset(actual) or not created.get("image") or created.get("isPublished") is not True:
        raise RuntimeError(f"Article {created['id']} failed image/metadata/published verification.")
    log(f"PUBLISHED WITH VERIFIED THUMBNAIL: {created['title']} | /blogs/{BLOG_HANDLE}/{created['handle']}")
    return True

def main():
    blog=guard(); channels=channel_allowlist(); candidates=collect(channels)
    log(f"RSS + oEmbed VIDEO CANDIDATES (embeddability not guaranteed): {len(candidates)}")
    count=0
    for video in candidates:
        if count>=MAX_VIDEOS:break
        try:
            if create_draft(blog,video):count+=1
        except Exception as error:log(f"HOLD/FAIL {video.get('title','(untitled)')}: {error}")
    mode="AUTO_PUBLISH" if AUTO_PUBLISH else "DRY_RUN"
    log(f"VIDEO RUN COMPLETE: published={count}; max={MAX_VIDEOS}; mode={mode}; official-channel RSS + oEmbed + reachable thumbnail + player endpoint check; no theme/domain changes.")

if __name__=="__main__":
    try:main()
    except SystemExit:raise
    except Exception as error:
        log("VIDEO WORKFLOW FAILED CLOSED: "+str(error));sys.exit(1)
