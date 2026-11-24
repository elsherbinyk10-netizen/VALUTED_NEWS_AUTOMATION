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
YOUTUBE_KEY=os.getenv("YOUTUBE_DATA_API_KEY","").strip()
API_VERSION=os.getenv("SHOPIFY_API_VERSION","2026-10")
MAX_VIDEOS=min(5,max(0,int(os.getenv("MAX_VIDEOS_PER_RUN","5"))))
MAX_AGE_HOURS=max(1,int(os.getenv("MAX_VIDEO_AGE_HOURS","72")))
AUTO_PUBLISH=os.getenv("AUTO_PUBLISH","false").lower()=="true"
BASE="https://www.googleapis.com/youtube/v3"
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
    if not TOKEN or not YOUTUBE_KEY: raise RuntimeError("Missing Music-only Shopify token or YouTube Data API key. No writes.")
    if SHOP!=EXPECTED_SHOP: raise RuntimeError("SHOPIFY_ADMIN_DOMAIN is not the configured VALUTED MUSIC shop. No writes.")
    data=gql("""query Guard { shop { name primaryDomain { host } } blogs(first:50) { edges { node { id handle } } } }""")
    shop=data["shop"]
    if shop["name"].strip().casefold()!=EXPECTED_NAME.casefold() or (shop.get("primaryDomain") or {}).get("host","").lower()!=EXPECTED_HOST:
        raise RuntimeError("Wrong Shopify identity or primary domain. No changes made.")
    blog=next((e["node"] for e in data["blogs"]["edges"] if e["node"]["handle"]==BLOG_HANDLE),None)
    if not blog: raise RuntimeError("Expected VALUTED MUSIC news blog is missing. No writes.")
    log(f"SHOP VERIFIED: {EXPECTED_NAME} / {EXPECTED_HOST} / blog={BLOG_HANDLE}")
    return blog["id"]

def yt(path,params):
    r=SESSION.get(f"{BASE}/{path}",params=dict(params,key=YOUTUBE_KEY),timeout=30)
    r.raise_for_status(); payload=r.json()
    if payload.get("error"): raise RuntimeError(payload["error"].get("message","YouTube API error"))
    return payload

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

EXCLUDED_TITLE=re.compile(r"\b(shorts?|teaser|trailer|behind the scenes|interview|lyrics?|lyric video|audio only|visuali[sz]er|dance practice|reaction|live session)\b",re.I)
OFFICIAL_VIDEO_TITLE=re.compile(r"\b(official music video|official video|music video|official video clip|official clip)\b",re.I)

def is_official_music_video(title,description="",duration=""):
    title=html.unescape(title or "").strip()
    description=html.unescape(description or "").strip()
    if not title or EXCLUDED_TITLE.search(title):return False
    if re.search(r"#shorts?\b",title+" "+description,re.I):return False
    return bool(OFFICIAL_VIDEO_TITLE.search(title) and duration_seconds(duration)>=60)

def collect(channels,now=None):
    now=now or datetime.now(timezone.utc); candidates={}
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
            candidates[vid]={"video_id":vid,"channel_id":channel["channel_id"],"channel_label":channel["label"],"published":published}
    if not candidates:return []
    ids=list(candidates); verified=[]
    for start in range(0,len(ids),50):
        verified.extend(yt("videos",{"part":"snippet,status,contentDetails","id":",".join(ids[start:start+50]),"maxResults":50}).get("items",[]))
    results=[]
    for video in verified:
        vid=video.get("id",""); expected=candidates.get(vid)
        sn=video.get("snippet") or {}; st=video.get("status") or {}; cd=video.get("contentDetails") or {}
        if not expected or sn.get("channelId")!=expected["channel_id"]:continue
        if st.get("privacyStatus")!="public" or st.get("embeddable") is not True:continue
        title=html.unescape(sn.get("title","")).strip()
        description=html.unescape(sn.get("description","")).strip()
        duration=cd.get("duration","")
        if len(description)<40 or not is_official_music_video(title,description,duration):continue
        thumbs=sn.get("thumbnails") or {}
        thumbnail=next((thumbs[k].get("url","") for k in ("maxres","standard","high","medium","default") if thumbs.get(k,{}).get("url")),"")
        parsed=urlparse(thumbnail)
        if parsed.scheme!="https" or not parsed.netloc:continue
        results.append({"video_id":vid,"title":title,"description":description[:1800],
            "channel_id":sn["channelId"],"channel_title":sn.get("channelTitle",expected["channel_label"]),
            "thumbnail":thumbnail,"published":expected["published"],"duration":duration,
            "embed_url":f"https://www.youtube-nocookie.com/embed/{vid}",
            "watch_url":f"https://www.youtube.com/watch?v={vid}"})
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
    body=f'''<p>{html.escape(description[:900])}</p>
<div class="vm-official-video" style="position:relative;aspect-ratio:16/9;max-width:100%;background:#08080d">
<iframe src="{video["embed_url"]}" title="{title}" loading="eager" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin" style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>
</div>
<p><strong>Official source:</strong> <a href="{video["watch_url"]}" rel="nofollow noopener" target="_blank">{channel}</a></p>
<p>Video playback, regional availability, captions and advertising are controlled by YouTube and the rights holder.</p>'''
    base=re.sub(r"[^a-z0-9-]+","-",video["title"].lower()).strip("-")[:120]
    summary=description[:240] or f"Official music video from {video['channel_title']}."
    metafields=[
      {"namespace":"custom","key":"video_id","type":"single_line_text_field","value":video["video_id"]},
      {"namespace":"custom","key":"video_embed_url","type":"url","value":video["embed_url"]},
      {"namespace":"custom","key":"video_thumbnail","type":"url","value":video["thumbnail"]},
      {"namespace":"custom","key":"video_channel","type":"single_line_text_field","value":video["channel_title"][:255]},
      {"namespace":"custom","key":"video_upload_date","type":"date_time","value":video["published"].isoformat()},
      {"namespace":"custom","key":"video_duration","type":"single_line_text_field","value":video["duration"]},
      {"namespace":"custom","key":"video_description","type":"single_line_text_field","value":description[:255]}]
    return {"author":{"name":"VALUTED MUSIC Editorial Desk"},"title":video["title"][:255],
      "handle":f"{base}-{video['video_id'].lower()}".strip("-"),"body":body,"summary":summary,
      "tags":["official-music-video","music-video",video["video_id"],"official-source"],
      "image":{"url":video["thumbnail"],"altText":f"{video['title']} — official music video thumbnail"[:512]},
      "metafields":metafields,"isPublished":False}

def create_draft(blog_id,video):
    existing=already_exists(blog_id,video["video_id"])
    if existing:
        log(f"DUPLICATE SKIP: {video['title']} (published={existing['isPublished']})");return False
    if not AUTO_PUBLISH:
        log("DRY RUN — verified candidate only: "+video["title"]);return False
    mutation="""mutation CreateMusicVideo($article:ArticleCreateInput!){articleCreate(article:$article){article{id title handle isPublished image{altText originalSrc} metafields(first:10,namespace:"custom"){edges{node{key value}}}}userErrors{field message}}}"""
    result=gql(mutation,{"article":dict(build_article(video),blogId=blog_id)})["articleCreate"]
    if result["userErrors"]:raise RuntimeError("Shopify article creation rejected: "+json.dumps(result["userErrors"]))
    created=result["article"]
    expected={"video_id","video_embed_url","video_thumbnail","video_channel","video_upload_date","video_duration","video_description"}
    actual={e["node"]["key"] for e in created["metafields"]["edges"]}
    if not expected.issubset(actual) or not created.get("image"):
        raise RuntimeError(f"Article {created['id']} remains a draft: thumbnail or VideoObject metadata verification failed.")
    publish="""mutation PublishMusicVideo($id:ID!,$article:ArticleUpdateInput!){articleUpdate(id:$id,article:$article){article{id title handle isPublished}userErrors{field message}}}"""
    outcome=gql(publish,{"id":created["id"],"article":{"isPublished":True}})["articleUpdate"]
    if outcome["userErrors"] or not outcome["article"]["isPublished"]:
        raise RuntimeError(f"Article {created['id']} remains a draft; publish verification failed: "+json.dumps(outcome["userErrors"]))
    article=outcome["article"]
    log(f"PUBLISHED VERIFIED VIDEO: {article['title']} | /blogs/{BLOG_HANDLE}/{article['handle']}")
    return True

def main():
    blog=guard(); channels=channel_allowlist(); candidates=collect(channels)
    log(f"VERIFIED OFFICIAL VIDEO CANDIDATES: {len(candidates)}")
    count=0
    for video in candidates:
        if count>=MAX_VIDEOS:break
        try:
            if create_draft(blog,video):count+=1
        except Exception as error:log(f"HOLD/FAIL {video.get('title','(untitled)')}: {error}")
    mode="AUTO_PUBLISH" if AUTO_PUBLISH else "DRY_RUN"
    log(f"VIDEO RUN COMPLETE: published={count}; max={MAX_VIDEOS}; mode={mode}; no theme/domain changes.")

if __name__=="__main__":
    try:main()
    except SystemExit:raise
    except Exception as error:
        log("VIDEO WORKFLOW FAILED CLOSED: "+str(error));sys.exit(1)
