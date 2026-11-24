#!/usr/bin/env python3
"""Daily MusicBrainz catalogue expansion for VALUTED MUSIC.
Creates searchable, crawlable editorial catalogue pages for artists, albums and recordings.
Uses MusicBrainz public search API; does not invent official video URLs.
"""
import os, re, sys, json, time, html, hashlib
from datetime import datetime, timezone
from urllib.parse import quote
import requests

SHOP=os.getenv("SHOPIFY_ADMIN_DOMAIN","").strip()
TOKEN=os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN","")
API_VERSION=os.getenv("SHOPIFY_API_VERSION","2026-10")
MAX_ITEMS=min(30,max(1,int(os.getenv("MAX_CATALOG_ITEMS","15"))))
BLOG_HANDLE="news"
HEADERS={"User-Agent":"VALUTED-MUSIC-Catalogue/1.0 (https://valutedmusic.site; contact: catalog@valutedmusic.site)","Accept":"application/json"}
S=requests.Session(); S.headers.update(HEADERS)

def log(s): print(s,flush=True)
def gql(q,v=None):
 r=S.post(f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json",headers={"X-Shopify-Access-Token":TOKEN,"Content-Type":"application/json"},json={"query":q,"variables":v or {}},timeout=35)
 r.raise_for_status(); d=r.json()
 if d.get("errors"): raise RuntimeError(json.dumps(d["errors"])[:1000])
 return d["data"]

def guard():
 if not TOKEN or not SHOP.endswith(".myshopify.com"): raise RuntimeError("Music Shopify credentials missing; no writes.")
 d=gql("query Guard { shop { name primaryDomain { host } } blogs(first:50){edges{node{id handle}}}}")
 sh=d["shop"]
 if sh["name"].strip().casefold()!="valuted music" or sh["primaryDomain"]["host"].lower()!="valutedmusic.site":
  log("WRONG SHOP CONNECTED — NO CHANGES.");sys.exit(0)
 blog=next((x["node"] for x in d["blogs"]["edges"] if x["node"]["handle"]==BLOG_HANDLE),None)
 if not blog: raise RuntimeError("Expected existing Music catalogue blog is missing.")
 log("Verified VALUTED MUSIC shop.");return blog["id"]

def mb(kind,query,limit=12):
 time.sleep(1.1)
 url=f"https://musicbrainz.org/ws/2/{kind}/"
 # Rotate result windows daily so repeated runs discover new records instead of replaying only the first page.
 offset=(datetime.now(timezone.utc).timetuple().tm_yday * 17) % 100
 r=S.get(url,params={"query":query,"fmt":"json","limit":limit,"offset":offset},timeout=30)
 r.raise_for_status()
 return r.json()

def clean(s):
 return re.sub(r"\s+"," ",html.unescape(str(s or ""))).strip()

def slug(s):
 s=re.sub(r"[^a-z0-9]+","-",clean(s).lower()).strip("-")
 return s[:100] or "music-entry"

def article_exists(blog_id,tag):
 q="""query Existing($id:ID!,$after:String){blog(id:$id){articles(first:100,after:$after){edges{node{id tags}}pageInfo{hasNextPage endCursor}}}}"""
 cursor=None
 while True:
  p=gql(q,{"id":blog_id,"after":cursor})["blog"]["articles"]
  for e in p["edges"]:
   if tag in e["node"]["tags"]: return True
  if not p["pageInfo"]["hasNextPage"]: return False
  cursor=p["pageInfo"]["endCursor"]

def create(blog_id,title,handle,body,tags,summary):
 tag=next(t for t in tags if t.startswith("mbid-"))
 if article_exists(blog_id,tag): log("SKIP existing: "+title);return False
 inp={"title":title,"handle":handle,"body":body,"tags":tags,"isPublished":True,"summary":summary[:240],
      "seo":{"title":(title+" | VALUTED MUSIC")[:70],"description":summary[:300]}}
 d=gql("""mutation Create($blog:ID!,$article:ArticleCreateInput!){articleCreate(blogId:$blog,article:$article){article{id title handle isPublished}userErrors{field message}}}""",{"blog":blog_id,"article":inp})["articleCreate"]
 if d["userErrors"]: raise RuntimeError(json.dumps(d["userErrors"]))
 log("CATALOGUE PAGE: "+d["article"]["title"]+" /blogs/news/"+d["article"]["handle"]);return True

def make_artist(x):
 mbid=x.get("id");name=clean(x.get("name"));area=clean((x.get("area") or {}).get("name"));country=clean((x.get("country") or ""));kind=clean(x.get("type"));life=x.get("life-span") or {}
 born=clean(life.get("begin"));ended=clean(life.get("end"));dis=clean(x.get("disambiguation"))
 if not mbid or not name:return None
 title=f"{name} — Artist Profile"
 facts=[f"<p><strong>Artist:</strong> {html.escape(name)}</p>"]
 if kind:facts.append(f"<p><strong>Type:</strong> {html.escape(kind)}</p>")
 if area or country:facts.append(f"<p><strong>Origin:</strong> {html.escape(', '.join(v for v in [area,country] if v))}</p>")
 if born:facts.append(f"<p><strong>Active since:</strong> {html.escape(born)}</p>")
 if ended:facts.append(f"<p><strong>Ended:</strong> {html.escape(ended)}</p>")
 if dis:facts.append(f"<p>{html.escape(dis)}</p>")
 facts.append(f'<p>Explore this artist’s releases and recordings in the VALUTED MUSIC catalogue. Music metadata source: <a href="https://musicbrainz.org/artist/{mbid}" rel="nofollow noopener" target="_blank">MusicBrainz artist record</a>.</p>')
 summary=f"Artist profile for {name}. Explore music releases, recordings and related catalogue entries."
 return title,slug(name)+"-artist-"+mbid[:8],''.join(facts),["catalog-artist","music-artist","mbid-"+mbid],summary

def make_release(x):
 mbid=x.get("id");title=clean(x.get("title"));artist=clean(x.get("artist-credit-phrase"));date=clean(x.get("first-release-date"));typ=clean(x.get("primary-type"));secondary=", ".join(x.get("secondary-types") or [])
 if not mbid or not title:return None
 heading=f"{title} — Album & Release Guide"
 body=f"<p><strong>Artist:</strong> {html.escape(artist or 'Not listed')}</p><p><strong>Release date:</strong> {html.escape(date or 'Not listed')}</p><p><strong>Release type:</strong> {html.escape(typ or 'Not listed')}{(' · '+html.escape(secondary)) if secondary else ''}</p><p>Explore this release in the VALUTED MUSIC catalogue. Track listings and release details may vary by edition. Metadata source: <a href=\"https://musicbrainz.org/release-group/{mbid}\" rel=\"nofollow noopener\" target=\"_blank\">MusicBrainz release-group record</a>.</p>"
 return heading,slug(title)+"-release-"+mbid[:8],body,["catalog-album","music-album","mbid-"+mbid],f"Album and release guide for {title} by {artist}."

def make_recording(x):
 mbid=x.get("id");title=clean(x.get("title"));artist=clean(x.get("artist-credit-phrase"));length=x.get("length")
 if not mbid or not title:return None
 duration=f"{int(length)//60000}:{(int(length)//1000)%60:02d}" if str(length).isdigit() else ""
 heading=f"{title} — Song & Recording"
 body=f"<p><strong>Artist:</strong> {html.escape(artist or 'Not listed')}</p>"+(f"<p><strong>Duration:</strong> {duration}</p>" if duration else "")+f"<p>Explore this song in the VALUTED MUSIC catalogue. Recording metadata source: <a href=\"https://musicbrainz.org/recording/{mbid}\" rel=\"nofollow noopener\" target=\"_blank\">MusicBrainz recording record</a>.</p>"
 return heading,slug(title)+"-song-"+mbid[:8],body,["catalog-song","music-song","mbid-"+mbid],f"Song and recording details for {title} by {artist}."

def main():
 blog=guard();items=[]
 # Diverse, repeatable discovery across major styles; duplicates are blocked by MusicBrainz IDs.
 searches=[
  ("artist",'tag:pop AND type:Person'),("artist",'tag:rock AND type:Group'),
  ("artist",'tag:hip hop AND type:Person'),("artist",'tag:electronic AND type:Group'),
  ("artist",'tag:arabic music'),("artist",'tag:jazz AND type:Person'),
  ("release-group",'primarytype:Album AND tag:pop'),("release-group",'primarytype:Album AND tag:rock'),
  ("release-group",'primarytype:Album AND tag:hip hop'),("release-group",'primarytype:Album AND tag:arabic music'),
  ("recording",'tag:pop'),("recording",'tag:rock'),("recording",'tag:hip hop'),("recording",'tag:arabic music')
 ]
 for kind,q in searches:
  try:
   key={"artist":"artists","release-group":"release-groups","recording":"recordings"}[kind]
   for x in mb(kind,q,10).get(key,[]):
    maker={"artist":make_artist,"release-group":make_release,"recording":make_recording}[kind]
    entry=maker(x)
    if entry:items.append(entry)
  except Exception as e: log(f"Search skipped ({kind} / {q}): {e}")
 # Prioritize artists, then albums, then recordings, while keeping stable order.
 dedup={x[3][-1]:x for x in items}
 count=0
 for entry in dedup.values():
  if count>=MAX_ITEMS:break
  try:
   if create(blog,*entry):count+=1
  except Exception as e:log("Entry held: "+entry[0]+" — "+str(e))
 log(f"Catalogue run finished. New entries: {count}; cap: {MAX_ITEMS}. No video URL was invented.")

if __name__=="__main__":
 try:main()
 except Exception as e:log("CATALOGUE WORKER FAILED CLOSED: "+str(e));sys.exit(1)
