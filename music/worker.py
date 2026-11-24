#!/usr/bin/env python3
"""VALUTED MUSIC daily publishing worker. Strict store guard; no theme writes."""
import os, re, sys, json, hashlib, html
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse
import requests, feedparser
from bs4 import BeautifulSoup

EXPECTED_NAME = "VALUTED MUSIC"
EXPECTED_HOST = "valutedmusic.site"
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2026-10")
SHOP = os.getenv("SHOPIFY_ADMIN_DOMAIN", "").strip()
TOKEN = os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", "")
MAX_ARTICLES = min(5, max(0, int(os.getenv("MAX_ARTICLES_PER_RUN", "3"))))
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "36"))
AUTO_PUBLISH = os.getenv("AUTO_PUBLISH", "false").lower() == "true"
BLOG_HANDLE = "news"

FEEDS = [
    ("https://www.billboard.com/feed/", "Billboard"),
    ("https://www.rollingstone.com/music/music-news/feed/", "Rolling Stone"),
    ("https://variety.com/v/music/feed/", "Variety"),
    ("https://pitchfork.com/rss/news/", "Pitchfork"),
    ("https://www.npr.org/rss/rss.php?id=1039", "NPR Music"),
    ("https://www.theguardian.com/music/rss", "The Guardian"),
    ("https://www.musicbusinessworldwide.com/feed/", "Music Business Worldwide"),
    ("https://www.arabnews.com/rss/section/4", "Arab News"),
]
ALLOWED_HOSTS = {
    "billboard.com", "www.billboard.com", "rollingstone.com", "www.rollingstone.com",
    "variety.com", "www.variety.com", "pitchfork.com", "www.pitchfork.com",
    "npr.org", "www.npr.org", "theguardian.com", "www.theguardian.com",
    "musicbusinessworldwide.com", "www.musicbusinessworldwide.com",
    "arabnews.com", "www.arabnews.com"
}
GENRES = {
    "arabic-music": ("arab", "egypt", "leban", "morocco", "khaleeji", "mahragan", "amr diab", "elissa", "tamer"),
    "hip-hop": ("hip-hop", "hip hop", "rap", "rapper", "grime"),
    "classical": ("classical", "orchestra", "symphony", "concerto", "opera"),
    "pop": ("pop", "singer", "single", "album"),
    "afrobeats": ("afrobeats", "afrobeat", "afropop", "amapiano"),
    "r-and-b": ("r&b", "rnb", "soul"),
    "rock": ("rock", "metal", "punk", "guitar"),
    "electronic": ("electronic", "dance music", "edm", "techno", "house", "dj")
}

session = requests.Session()
session.headers.update({"User-Agent":"VALUTED-MUSIC-NewsBot/1.0 (+https://valutedmusic.site)"})

def log(msg): print(msg, flush=True)
def norm_host(url):
    try: return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception: return ""

def canonicalize(url):
    p=urlparse(url)
    return urlunparse((p.scheme or "https", p.netloc.lower(), p.path.rstrip("/"), "", "", ""))

def gql(query, variables=None):
    r=session.post(f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json",
        headers={"X-Shopify-Access-Token":TOKEN,"Content-Type":"application/json"},
        json={"query":query,"variables":variables or {}},timeout=35)
    r.raise_for_status()
    data=r.json()
    if data.get("errors"): raise RuntimeError("Shopify GraphQL error: "+json.dumps(data["errors"])[:1200])
    return data["data"]

def shop_guard_and_audit():
    if not TOKEN: raise RuntimeError("Missing VALUTED_MUSIC_SHOPIFY_ADMIN_ACCESS_TOKEN")
    if not SHOP or not SHOP.endswith(".myshopify.com"):
        raise RuntimeError("Missing/invalid VALUTED_MUSIC_SHOPIFY_ADMIN_DOMAIN Actions variable; expected the store-specific .myshopify.com host. No writes.")
    q="""query Guard { shop { name myshopifyDomain primaryDomain { host url } } themes(first:50) { edges { node { id name role } } } }"""
    d=gql(q); s=d["shop"]
    host=(s.get("primaryDomain") or {}).get("host","").lower()
    name=s.get("name","").strip()
    themes=[e["node"] for e in d["themes"]["edges"]]
    main=[t for t in themes if t.get("role")=="MAIN"]
    log(f"SHOP CHECK: name={name!r}; primary_host={host!r}; myshopify={s.get('myshopifyDomain')!r}")
    if name.casefold()!=EXPECTED_NAME.casefold() or host!=EXPECTED_HOST:
        log("WRONG SHOP CONNECTED — NO CHANGES MADE.")
        sys.exit(0)
    if len(main)!=1:
        raise RuntimeError(f"Expected exactly one MAIN theme; found {len(main)}. No article writes.")
    log(f"MAIN THEME: name={main[0]['name']}; id={main[0]['id']}; role={main[0]['role']}")
    blogs=gql("""query Blogs { blogs(first:100) { edges { node { id handle title } } } }""")["blogs"]["edges"]
    target=next((e["node"] for e in blogs if e["node"]["handle"]==BLOG_HANDLE),None)
    if not target: raise RuntimeError("Existing Shopify blog handle 'news' was not found. No writes.")
    log(f"BLOG VERIFIED: title={target['title']!r}; handle={target['handle']}; id={target['id']}")
    return target["id"]

def get_page(url):
    r=session.get(url,timeout=25,allow_redirects=True)
    r.raise_for_status()
    if norm_host(r.url) not in ALLOWED_HOSTS: raise ValueError("Redirected outside approved publisher domain")
    soup=BeautifulSoup(r.text,"html.parser")
    canonical=soup.find("link",rel="canonical")
    canon=canonical.get("href") if canonical and canonical.get("href") else r.url
    if norm_host(canon) not in ALLOWED_HOSTS: raise ValueError("Canonical URL outside approved publisher domain")
    for x in soup(["script","style","nav","footer","header","aside","noscript"]): x.decompose()
    title=(soup.find("meta",property="og:title") or {}).get("content") or (soup.title.get_text(" ",strip=True) if soup.title else "")
    desc=(soup.find("meta",property="og:description") or {}).get("content") or ""
    body=soup.find("article") or soup.find("main") or soup.body
    text=re.sub(r"\s+"," ",body.get_text(" ",strip=True)) if body else ""
    text=text[:16000]
    if len(text.split())<180: raise ValueError("Underlying publisher page has insufficient readable article text")
    pub=soup.find("meta",property="article:published_time")
    published=pub.get("content") if pub else ""
    return {"url":canonicalize(canon),"title":html.unescape(title).strip(),"description":desc.strip(),"text":text,"published":published}

def collect():
    now=datetime.now(timezone.utc); seen=set(); items=[]
    for feed_url,publisher in FEEDS:
        try:
            parsed=feedparser.parse(feed_url)
            for entry in parsed.entries[:25]:
                link=entry.get("link","")
                if not link or norm_host(link) not in ALLOWED_HOSTS: continue
                key=canonicalize(link)
                if key in seen: continue
                seen.add(key)
                raw=entry.get("published_parsed") or entry.get("updated_parsed")
                if raw:
                    from time import mktime
                    dt=datetime.fromtimestamp(mktime(raw),timezone.utc)
                    if now-dt>timedelta(hours=MAX_AGE_HOURS) or dt>now+timedelta(hours=2): continue
                try:
                    page=get_page(link)
                    if page["published"]:
                        dt=datetime.fromisoformat(page["published"].replace("Z","+00:00"))
                        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
                        if now-dt>timedelta(hours=MAX_AGE_HOURS) or dt>now+timedelta(hours=2): continue
                    page["publisher"]=publisher
                    items.append(page)
                except Exception as e: log(f"HOLD source {link}: {e}")
        except Exception as e: log(f"FEED ERROR {feed_url}: {e}")
    return sorted(items,key=lambda x:x.get("published",""),reverse=True)

def draft_story(item):
    """Build a concise, source-attributed news brief without a generative API."""
    source_text=BeautifulSoup(item.get("text",""),"html.parser").get_text(" ",strip=True)
    source_text=re.sub(r"\s+"," ",source_text).strip()
    # Keep only a short factual excerpt and link readers to the original publisher.
    sentences=re.split(r"(?<=[.!?])\s+",source_text)
    excerpt=" ".join(s for s in sentences if len(s.split())>=8)[:900]
    excerpt=" ".join(excerpt.split()[:125])
    if len(excerpt.split())<35:
        excerpt=(item.get("description") or "").strip()
    if len(excerpt.split())<20:
        raise ValueError("Source page has too little usable text for a safe news brief")
    title=html.unescape(item.get("title","")).strip()
    if not title:
        raise ValueError("Source headline is missing")
    publisher=html.escape(item.get("publisher","Original publisher"))
    safe_title=html.escape(title)
    source=html.escape(item["url"],quote=True)
    body=(f"<p>{html.escape(excerpt)}</p>"
          f"<p>This brief is based on reporting by {publisher}. "
          f"Read the original report for full details and context: "
          f"<a href=\"{source}\" rel=\"nofollow noopener\" target=\"_blank\">{publisher}</a>.</p>")
    tags=["artist-news"]
    text=(title+" "+excerpt).lower()
    for tag,terms in GENRES.items():
        if any(term in text for term in terms) and tag not in tags: tags.append(tag)
    if any(term in text for term in ("new single","new album","new release","releases")):
        tags.append("new-releases")
    handle=re.sub(r"[^a-z0-9-]+","-",title.lower()).strip("-")[:180]
    summary=(item.get("description") or excerpt)[:240]
    seo_description=(f"{title} — music news from {publisher}. "+summary)[:320]
    return {"title":title,"handle":handle,"body":body,"summary":summary,
        "seo_title":title[:70],"seo_description":seo_description,"tags":sorted(set(tags))}

def existing_source(blog_id, source_url, handle=None):
    # Walk every page so older stories cannot be duplicated after the newest 100.
    q="""query Existing($id:ID!,$after:String) {
      blog(id:$id) { articles(first:250, reverse:true, after:$after) {
        edges { node { id handle body } }
        pageInfo { hasNextPage endCursor }
      } }
    }"""
    cursor=None
    while True:
        page=gql(q,{"id":blog_id,"after":cursor})["blog"]["articles"]
        for edge in page["edges"]:
            node=edge["node"]
            if source_url in (node.get("body") or "") or (handle and node.get("handle")==handle):
                return True
        info=page["pageInfo"]
        if not info["hasNextPage"]: return False

def publish(blog_id, item, article):
    if existing_source(blog_id,item["url"],article["handle"]):
        log(f"DUPLICATE SKIP: {article['title']}"); return False
    if not AUTO_PUBLISH:
        log(f"DRY RUN (AUTO_PUBLISH=false): {article['title']}"); return False
    metafields=[
      {"namespace":"global","key":"title_tag","type":"single_line_text_field","value":article["seo_title"][:70]},
      {"namespace":"global","key":"description_tag","type":"single_line_text_field","value":article["seo_description"][:320]}]
    data={"author":{"name":"VALUTED MUSIC Editorial Desk"},"blogId":blog_id,
      "title":article["title"],"handle":article["handle"],"body":article["body"],
      "tags":article["tags"],"summary":article.get("summary","")[:240],
      "metafields":metafields,"isPublished":True}
    mutation="""mutation CreateArticle($article:ArticleCreateInput!) { articleCreate(article:$article) { article { id title handle isPublished tags body metafields(first:10,namespace:"global"){edges{node{key value}}} } userErrors { field message } } }"""
    result=gql(mutation,{"article":data})["articleCreate"]
    if result["userErrors"]: raise RuntimeError("Article write failed: "+json.dumps(result["userErrors"]))
    created=result["article"]
    saved=gql("""query Verify($id:ID!) { article(id:$id) { id title handle isPublished tags body blog { id handle } metafields(first:10,namespace:"global"){edges{node{key value}}} } }""",{"id":created["id"]})["article"]
    seo={e["node"]["key"]:e["node"]["value"] for e in saved["metafields"]["edges"]}
    checks={"title":saved["title"]==article["title"],"handle":saved["handle"]==article["handle"],
      "published":saved["isPublished"] is True,"source":item["url"] in (saved.get("body") or ""),
      "tags":set(article["tags"]).issubset(set(saved.get("tags") or [])),
      "seo_title":seo.get("title_tag")==article["seo_title"][:70],
      "seo_description":seo.get("description_tag")==article["seo_description"][:320],
      "blog":(saved.get("blog") or {}).get("handle")==BLOG_HANDLE}
    log("POST-WRITE VERIFY: "+json.dumps(checks))
    if not all(checks.values()): raise RuntimeError("Post-write verification failed; do not retry automatically.")
    log("PUBLISHED: https://{}/blogs/{}/{} | SEO verified".format(EXPECTED_HOST,BLOG_HANDLE,saved["handle"]))
    return True

def main():
    blog_id=shop_guard_and_audit()
        candidates=collect()
    log(f"LIVE SOURCE PAGES VERIFIED: {len(candidates)}")
    published=0
    for item in candidates:
        if published>=MAX_ARTICLES: break
        try:
            article=draft_story(item)
            before=existing_source(blog_id,item["url"])
            if before: log(f"DUPLICATE SKIP: {article['title']}"); continue
            if publish(blog_id,item,article): published+=1
        except Exception as e: log(f"HOLD/FAIL: {item.get('title','(untitled)')} | {e}")
    log(f"RUN COMPLETE: published={published}; max={MAX_ARTICLES}; verified_candidates={len(candidates)}; no theme/storefront settings modified.")

if __name__=="__main__":
    try: main()
    except SystemExit: raise
    except Exception as e:
        log(f"WORKFLOW FAILED CLOSED: {e}")
        sys.exit(1)
