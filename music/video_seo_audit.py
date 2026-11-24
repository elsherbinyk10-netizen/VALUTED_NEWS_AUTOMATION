#!/usr/bin/env python3
"""Retrofit and verify VideoObject SEO for existing VALUTED MUSIC watch pages.

Safe by default: AUTO_PUBLISH=false audits and reports only. When the existing
Music video workflow explicitly enables publishing, valid official-video pages
are upgraded in place without changing handles or publication status.
"""
import os, re, json, html, sys
from urllib.parse import urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

SHOP=os.getenv("SHOPIFY_ADMIN_DOMAIN","").strip()
TOKEN=os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN","").strip()
YOUTUBE_KEY=os.getenv("YOUTUBE_DATA_API_KEY","").strip()
API_VERSION=os.getenv("SHOPIFY_API_VERSION","2026-10")
EXPECTED_SHOP="0k31v6-th.myshopify.com"
EXPECTED_HOST="valutedmusic.site"
BLOG_HANDLE="news"
AUTO_PUBLISH=os.getenv("AUTO_PUBLISH","false").lower()=="true"
S=requests.Session()
S.headers.update({"User-Agent":"VALUTED-MUSIC-Video-SEO-Audit/1.0"})

def gql(query, variables=None):
    r=S.post(f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json",
      headers={"X-Shopify-Access-Token":TOKEN,"Content-Type":"application/json"},
      json={"query":query,"variables":variables or {}},timeout=35)
    r.raise_for_status()
    data=r.json()
    if data.get("errors"): raise RuntimeError(json.dumps(data["errors"])[:1200])
    return data["data"]

def guard():
    if not SHOP or SHOP!=EXPECTED_SHOP or not TOKEN or not YOUTUBE_KEY:
        raise RuntimeError("Music-only credentials unavailable or wrong shop; audit cannot access Shopify/YouTube. No writes.")
    d=gql("query Guard { shop { name primaryDomain { host } } blogs(first:50){edges{node{id handle}}}}")
    shop=d["shop"]
    if shop["name"].strip().casefold()!="valuted music" or (shop.get("primaryDomain") or {}).get("host","").lower()!=EXPECTED_HOST:
        raise RuntimeError("Shop identity mismatch; no changes.")
    blog=next((x["node"] for x in d["blogs"]["edges"] if x["node"]["handle"]==BLOG_HANDLE),None)
    if not blog: raise RuntimeError("VALUTED MUSIC news blog not found.")
    return blog["id"]

def video_id_from_body(body):
    soup=BeautifulSoup(body or "","html.parser")
    for node in soup.find_all(["iframe","a"]):
        for attr in ("src","href"):
            value=node.get(attr,"")
            if not value: continue
            parsed=urlparse(value)
            host=parsed.netloc.lower()
            if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
                match=re.search(r"/embed/([A-Za-z0-9_-]{11})",parsed.path)
                if match:return match.group(1)
                value_id=parse_qs(parsed.query).get("v",[])
                if value_id and re.fullmatch(r"[A-Za-z0-9_-]{11}",value_id[0]):return value_id[0]
            if host=="youtu.be" and re.fullmatch(r"[A-Za-z0-9_-]{11}",parsed.path.strip("/")):
                return parsed.path.strip("/")
    return None

def fetch_video(vid):
    r=S.get("https://www.googleapis.com/youtube/v3/videos",
      params={"part":"snippet,status,contentDetails","id":vid,"key":YOUTUBE_KEY},timeout=30)
    r.raise_for_status()
    items=r.json().get("items",[])
    if not items:return None
    v=items[0]; sn=v.get("snippet") or {}; st=v.get("status") or {}; cd=v.get("contentDetails") or {}
    if st.get("privacyStatus")!="public" or st.get("embeddable") is not True:return None
    title=html.unescape(sn.get("title","")).strip()
    if not re.search(r"official\\s+(music\\s+)?video|official\\s+lyrics?\\s+video|official\\s+audio",title,re.I):return None
    thumbs=sn.get("thumbnails") or {}
    thumb=next((thumbs[k].get("url") for k in ("maxres","standard","high","medium","default") if thumbs.get(k,{}).get("url")),None)
    if not thumb or urlparse(thumb).scheme!="https":return None
    return {"id":vid,"title":title,"description":html.unescape(sn.get("description","")).strip(),
      "channel":sn.get("channelTitle","Official channel"),"published":sn.get("publishedAt"),
      "duration":cd.get("duration"),"thumbnail":thumb,
      "embed":f"https://www.youtube-nocookie.com/embed/{vid}",
      "watch":f"https://www.youtube.com/watch?v={vid}"}

def page_seo(article, video):
    title=video["title"]
    low=title.lower()
    if "lyric" in low: kind="official lyrics video"; heading="Watch the official lyrics video"
    elif "audio" in low: kind="official audio"; heading="Listen to the official audio"
    else: kind="official music video"; heading="Watch the official music video"
    description=BeautifulSoup(video["description"],"html.parser").get_text(" ",strip=True)
    description=re.sub(r"\\s+"," ",description).strip()
    if len(description)<40: description=f"{title} — {kind} from {video['channel']}. Watch the official release on VALUTED MUSIC."
    description=description[:1000]
    canonical=f"https://{EXPECTED_HOST}/blogs/{BLOG_HANDLE}/{article['handle']}"
    schema={"@context":"https://schema.org","@type":"VideoObject","name":title,
      "description":description,"thumbnailUrl":[video["thumbnail"]],
      "uploadDate":video["published"],"duration":video["duration"],
      "embedUrl":video["embed"],"contentUrl":video["watch"],
      "publisher":{"@type":"Organization","name":video["channel"]},
      "mainEntityOfPage":canonical}
    schema_html='<script type="application/ld+json">'+json.dumps(schema,ensure_ascii=False,separators=(",",":")).replace("<","\\u003c")+'</script>'
    soup=BeautifulSoup(article.get("body","") or "","html.parser")
    for old in soup.find_all("script",type="application/ld+json"):
        try:
            if json.loads(old.string or old.get_text()).get("@type")=="VideoObject":old.decompose()
        except Exception: old.decompose()
    iframe=soup.find("iframe")
    if not iframe:
        wrapper=soup.new_tag("div",attrs={"class":"vm-official-video","style":"position:relative;aspect-ratio:16/9;max-width:100%"})
        iframe=soup.new_tag("iframe",src=video["embed"],title=title,loading="eager",allowfullscreen=True)
        wrapper.append(iframe);soup.append(wrapper)
    else:
        iframe["src"]=video["embed"];iframe["title"]=title;iframe["loading"]="eager"
    h2=soup.new_tag("h2");h2.string=heading
    if not soup.find("h2",string=re.compile("official (music|lyrics) video|official audio",re.I)):
        iframe.parent.insert_before(h2) if iframe.parent else soup.append(h2)
    soup.append(BeautifulSoup(schema_html,"html.parser"))
    seo_title=(f"Watch {title} | VALUTED MUSIC")[:70]
    seo_description=(f"{title} — {kind} from {video['channel']}. Watch on VALUTED MUSIC. "+description)[:320]
    metafields=[
      {"namespace":"global","key":"title_tag","type":"single_line_text_field","value":seo_title},
      {"namespace":"global","key":"description_tag","type":"single_line_text_field","value":seo_description},
      {"namespace":"custom","key":"video_id","type":"single_line_text_field","value":video["id"]},
      {"namespace":"custom","key":"video_embed_url","type":"url","value":video["embed"]},
      {"namespace":"custom","key":"video_thumbnail","type":"url","value":video["thumbnail"]},
      {"namespace":"custom","key":"video_channel","type":"single_line_text_field","value":video["channel"][:255]},
      {"namespace":"custom","key":"video_upload_date","type":"date_time","value":video["published"]},
      {"namespace":"custom","key":"video_duration","type":"single_line_text_field","value":video["duration"]}]
    return str(soup),metafields

def main():
    blog_id=guard(); cursor=None; audited=updated=skipped=0
    query="""query Pages($id:ID!,$after:String){blog(id:$id){articles(first:100,after:$after){edges{node{id title handle body tags isPublished}}pageInfo{hasNextPage endCursor}}}}"""
    while True:
        page=gql(query,{"id":blog_id,"after":cursor})["blog"]["articles"]
        for edge in page["edges"]:
            article=edge["node"]
            vid=video_id_from_body(article.get("body"))
            tags=article.get("tags") or []
            if not vid and not any(t in tags for t in ("music-video","official-music-video","official-lyrics-video","official-audio")):continue
            if not vid:
                log("HOLD no embedded YouTube ID: "+article["title"]);skipped+=1;continue
            video=fetch_video(vid)
            if not video:
                log("HOLD official/public/embeddable video could not be verified: "+article["title"]);skipped+=1;continue
            body,metafields=page_seo(article,video);audited+=1
            log(f"SEO READY: {article['title']} | video={vid} | published={article['isPublished']}")
            if not AUTO_PUBLISH:
                continue
            mutation="""mutation Retrofit($id:ID!,$article:ArticleUpdateInput!){articleUpdate(id:$id,article:$article){article{id title handle isPublished}userErrors{field message}}}"""
            result=gql(mutation,{"id":article["id"],"article":{"body":body,"metafields":metafields}})["articleUpdate"]
            if result["userErrors"]:raise RuntimeError(f"SEO update failed for {article['title']}: "+json.dumps(result["userErrors"]))
            verify=gql("""query Verify($id:ID!){article(id:$id){id handle body isPublished metafields(first:20){edges{node{namespace key value}}}}}""",{"id":article["id"]})["article"]
            keys={x["node"]["key"] for x in verify["metafields"]["edges"]}
            valid=verify["handle"]==article["handle"] and verify["isPublished"]==article["isPublished"] and "VideoObject" in (verify.get("body") or "") and {"title_tag","description_tag","video_id","video_thumbnail","video_upload_date","video_duration"}.issubset(keys)
            if not valid:raise RuntimeError("Post-update SEO verification failed for "+article["title"])
            updated+=1
        info=page["pageInfo"]
        if not info["hasNextPage"]:break
        cursor=info["endCursor"]
    log(f"VIDEO SEO AUDIT COMPLETE: eligible={audited}; upgraded={updated}; held={skipped}; mode={'UPDATE' if AUTO_PUBLISH else 'DRY RUN'}")

if __name__=="__main__":
    try:main()
    except Exception as e:
        log("VIDEO SEO AUDIT FAILED CLOSED: "+str(e));sys.exit(1)
