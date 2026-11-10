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
SHOP = os.getenv("SHOPIFY_SHOP_DOMAIN", "valutedmusic.site")
TOKEN = os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
MAX_ARTICLES = min(5, max(0, int(os.getenv("MAX_ARTICLES_PER_RUN", "5"))))
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "36"))
AUTO_PUBLISH = os.getenv("AUTO_PUBLISH", "true").lower() == "true"
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
    if not TOKEN: raise RuntimeError("Missing SHOPIFY_ADMIN_ACCESS_TOKEN")
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
    if not OPENAI_KEY: raise RuntimeError("Missing OPENAI_API_KEY; refusing to publish unedited feed excerpts")
    prompt = """Create one concise, original English music-news article based ONLY on the supplied live publisher page text. Do not add facts, dates, quotes, chart positions, video IDs, licensing or ownership claims. If a fact is unclear, omit it. Keep clear attribution and a direct source link. No video embed unless one is explicitly verified separately (none is supplied). Return strict JSON keys: title, handle, body_html, seo_title, seo_description, summary, genre_tags. body_html must contain useful h2 headings and a final source attribution link. 250-450 words. Tags must be selected only from: new-releases, artist-news, hip-hop, pop, rock, electronic, arabic-music, classical, afrobeats, r-and-b, tours, industry-news. No invented internal links."""
    payload={"model":os.getenv("OPENAI_MODEL","gpt-4.1-mini"),"temperature":0.2,
        "messages":[{"role":"system","content":prompt},{"role":"user","content":json.dumps(item,ensure_ascii=False)}],
        "response_format":{"type":"json_object"}}
    r=session.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization":f"Bearer {OPENAI_KEY}","Content-Type":"application/json"},
        json=payload,timeout=90)
    r.raise_for_status()
    result=json.loads(r.json()["choices"][0]["message"]["content"])
    title=result.get("title","").strip(); body=result.get("body_html","")
    if not title or len(body.split())<220: raise ValueError("Generated article failed completeness check")
    if item["url"] not in body: raise ValueError("Article body must contain the canonical source URL")
    tags=result.get("genre_tags",[])
    if not isinstance(tags,list): raise ValueError("Invalid tags")
    allowed={"new-releases","artist-news","hip-hop","pop","rock","electronic","arabic-music","classical","afrobeats","r-and-b","tours","industry-news"}
    tags=[t for t in tags if t in allowed]
    text=(title+" "+body).lower()
    for tag,terms in GENRES.items():
        if any(term in text for term in terms) and tag not in tags: tags.append(tag)
    if "artist-news" not in tags and "new-releases" not in tags: tags.append("artist-news")
    handle=re.sub(r"[^a-z0-9-]+","-",result.get("handle") or title.lower()).strip("-")[:180]
    return {"title":title,"handle":handle,"body":body,"seo_title":result.get("seo_title",title)[:70],
        "seo_description":result.get("seo_description",result.get("summary",""))[:320],"tags":sorted(set(tags))}

def existing_source(blog_id, source_url):
    q="""query Existing($id:ID!) { blog(id:$id) { articles(first:100, reverse:true) { edges { node { id handle title body } } } } }"""
    edges=gql(q,{"id":blog_id})["blog"]["articles"]["edges"]
    return any(source_url in (e["node"].get("body") or "") for e in edges)

def publish(blog_id, item, article):
    if existing_source(blog_id,item["url"]):
        log(f"DUPLICATE SKIP: {article['title']}"); return
    if not AUTO_PUBLISH:
        log(f"DRY RUN (AUTO_PUBLISH=false): {article['title']}"); return
    mutation="""mutation CreateArticle($blog:ID!,$article:ArticleCreateInput!) { articleCreate(blogId:$blog,article:$article) { article { id title handle isPublished tags body seo { title description } } userErrors { field message } } }"""
    data={"title":article["title"],"handle":article["handle"],"body":article["body"],
        "tags":article["tags"],"isPublished":True,
        "seo":{"title":article["seo_title"],"description":article["seo_description"]}}
    result=gql(mutation,{"blog":blog_id,"article":data})["articleCreate"]
    if result["userErrors"]: raise RuntimeError("Article write failed: "+json.dumps(result["userErrors"]))
    created=result["article"]
    # Re-query after every write; verify all required fields against Shopify's persisted record.
    verify="""query Verify($id:ID!) { article(id:$id) { id title handle isPublished tags body seo { title description } blog { id handle } } }"""
    saved=gql(verify,{"id":created["id"]})["article"]
    checks={
        "title":saved["title"]==article["title"],
        "handle":saved["handle"]==article["handle"],
        "published":saved["isPublished"] is True,
        "body":item["url"] in (saved.get("body") or ""),
        "tags":set(article["tags"]).issubset(set(saved.get("tags") or [])),
        "source":item["url"] in (saved.get("body") or ""),
        "seo_title":(saved.get("seo") or {}).get("title")==article["seo_title"],
        "seo_description":(saved.get("seo") or {}).get("description")==article["seo_description"],
        "blog":(saved.get("blog") or {}).get("handle")==BLOG_HANDLE
    }
    log("POST-WRITE VERIFY: "+json.dumps(checks))
    if not all(checks.values()): raise RuntimeError("Post-write verification failed; do not retry automatically.")
    log(f"PUBLISHED: {saved['title']} | https://{EXPECTED_HOST}/blogs/{BLOG_HANDLE}/{saved['handle']} | status=published | genres={','.join(saved['tags'])} | embed=none (not verified)")

def main():
    blog_id=shop_guard_and_audit()
    if not OPENAI_KEY: raise RuntimeError("OPENAI_API_KEY is not configured; identity verified, no publishing attempted.")
    candidates=collect()
    log(f"LIVE SOURCE PAGES VERIFIED: {len(candidates)}")
    published=0
    for item in candidates:
        if published>=MAX_ARTICLES: break
        try:
            article=draft_story(item)
            before=existing_source(blog_id,item["url"])
            if before: log(f"DUPLICATE SKIP: {article['title']}"); continue
            publish(blog_id,item,article)
            if AUTO_PUBLISH: published+=1
        except Exception as e: log(f"HOLD/FAIL: {item.get('title','(untitled)')} | {e}")
    log(f"RUN COMPLETE: published={published}; max={MAX_ARTICLES}; verified_candidates={len(candidates)}; no theme/storefront settings modified.")

if __name__=="__main__":
    try: main()
    except SystemExit: raise
    except Exception as e:
        log(f"WORKFLOW FAILED CLOSED: {e}")
        sys.exit(1)
