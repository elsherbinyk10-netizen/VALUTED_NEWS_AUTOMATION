#!/usr/bin/env python3
"""Read-only technical/content SEO audit for the VALUTED MUSIC Shopify blog.

Does not rewrite articles, change handles, or modify the Shopify theme.
Checks public crawl signals and Shopify SEO metadata; cannot determine Google's
actual indexing status (that requires Search Console access).
"""
import os, re, json, time, html, sys
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

SHOP=os.getenv("SHOPIFY_ADMIN_DOMAIN","").strip().lower()
TOKEN=os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN","").strip()
API_VERSION=os.getenv("SHOPIFY_API_VERSION","2026-10")
EXPECTED_SHOP="0k31v6-th.myshopify.com"
EXPECTED_HOST="valutedmusic.site"
BLOG_HANDLE="news"
OUT=os.getenv("SEO_REPORT_DIR","seo-report")
S=requests.Session()
S.headers.update({"User-Agent":"VALUTED-MUSIC-SEO-Audit/1.0 (+https://valutedmusic.site)"})

def gql(query, variables=None):
    response=S.post(f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json",
        headers={"X-Shopify-Access-Token":TOKEN,"Content-Type":"application/json"},
        json={"query":query,"variables":variables or {}},timeout=40)
    response.raise_for_status()
    data=response.json()
    if data.get("errors"):
        raise RuntimeError("Shopify GraphQL error: "+json.dumps(data["errors"])[:1200])
    return data["data"]

def guard_and_blog():
    if SHOP!=EXPECTED_SHOP or not TOKEN:
        raise RuntimeError("Music-only Shopify credentials/domain missing or incorrect. Audit stopped.")
    data=gql("""query Guard { shop { name myshopifyDomain primaryDomain { host } } blogs(first:100) { edges { node { id handle } } } }""")
    shop=data["shop"]
    if shop["name"].strip().casefold()!="valuted music" or shop["myshopifyDomain"].lower()!=EXPECTED_SHOP or (shop.get("primaryDomain") or {}).get("host","").lower()!=EXPECTED_HOST:
        raise RuntimeError("Exact VALUTED MUSIC store identity check failed. Audit stopped.")
    blog=next((e["node"] for e in data["blogs"]["edges"] if e["node"]["handle"]==BLOG_HANDLE),None)
    if not blog: raise RuntimeError("Existing news blog handle was not found.")
    print(f"STORE VERIFIED: {EXPECTED_HOST}; BLOG VERIFIED: {BLOG_HANDLE}",flush=True)
    return blog["id"]

def get_articles(blog_id):
    query="""query Articles($id:ID!,$after:String){blog(id:$id){articles(first:100,reverse:true,after:$after){edges{node{id title handle body summary isPublished tags publishedAt metafields(first:20,namespace:"global"){edges{node{key value}}}}}pageInfo{hasNextPage endCursor}}}}"""
    cursor=None; articles=[]
    while True:
        page=gql(query,{"id":blog_id,"after":cursor})["blog"]["articles"]
        articles.extend(e["node"] for e in page["edges"])
        info=page["pageInfo"]
        if not info["hasNextPage"]: break
        cursor=info["endCursor"]
    return articles

def fetch_text(url):
    r=S.get(url,timeout=25,allow_redirects=True)
    r.raise_for_status()
    return r.url,r.text

def read_sitemap():
    found=set(); notes=[]
    try:
        final,xml=fetch_text(f"https://{EXPECTED_HOST}/sitemap.xml")
        soup=BeautifulSoup(xml,"xml")
        child=[x.get_text(strip=True) for x in soup.find_all("loc")]
        blog_maps=[u for u in child if "sitemap_blogs_" in u]
        if not blog_maps:
            blog_maps=[f"https://{EXPECTED_HOST}/sitemap_blogs_1.xml"]
        for url in blog_maps:
            try:
                _,body=fetch_text(url)
                for loc in BeautifulSoup(body,"xml").find_all("loc"):
                    found.add(loc.get_text(strip=True).rstrip("/"))
            except Exception as exc: notes.append(f"Blog sitemap unavailable: {exc}")
    except Exception as exc: notes.append(f"Root sitemap unavailable: {exc}")
    return found,notes

def robots_check():
    try:
        _,body=fetch_text(f"https://{EXPECTED_HOST}/robots.txt")
        disallow_all=bool(re.search(r"(?im)^\s*Disallow:\s*/\s*$",body))
        return {"reachable":True,"disallow_all":disallow_all,"excerpt":body[:1600]}
    except Exception as exc:
        return {"reachable":False,"error":str(exc)}

def audit_article(article,sitemap_urls):
    handle=article["handle"]
    url=f"https://{EXPECTED_HOST}/blogs/{BLOG_HANDLE}/{handle}"
    checks={}; warnings=[]
    body=article.get("body") or ""
    text=BeautifulSoup(body,"html.parser").get_text(" ",strip=True)
    words=len(re.findall(r"\b[\w'-]+\b",text))
    metafields={e["node"]["key"]:e["node"]["value"] for e in (article.get("metafields") or {}).get("edges",[])}
    checks["published"]=bool(article.get("isPublished"))
    checks["shopify_seo_title"]=bool(metafields.get("title_tag"))
    checks["shopify_meta_description"]=bool(metafields.get("description_tag"))
    if not checks["shopify_seo_title"]: warnings.append("Missing global.title_tag SEO metafield")
    if not checks["shopify_meta_description"]: warnings.append("Missing global.description_tag SEO metafield")
    if len(metafields.get("title_tag",""))>70: warnings.append("SEO title exceeds 70 characters")
    desc=metafields.get("description_tag","")
    if desc and not (50<=len(desc)<=160): warnings.append(f"SEO description length is {len(desc)} characters; target 50–160")
    checks["sitemap_present"]=url.rstrip("/") in sitemap_urls
    if not checks["sitemap_present"]: warnings.append("URL not found in the Shopify blog sitemap")
    page_status=None; page={}
    try:
        final,markup=fetch_text(url)
        soup=BeautifulSoup(markup,"html.parser")
        page_status=200
        canonical=soup.find("link",rel=lambda v:v and "canonical" in v)
        canonical_url=(canonical.get("href") or "").rstrip("/") if canonical else ""
        checks["canonical_matches"]=canonical_url==url.rstrip("/")
        if not checks["canonical_matches"]: warnings.append("Canonical missing or does not match the article URL")
        title=soup.title.get_text(" ",strip=True) if soup.title else ""
        meta=soup.find("meta",attrs={"name":re.compile("^description$",re.I)})
        meta_desc=(meta.get("content") or "").strip() if meta else ""
        checks["html_title_present"]=bool(title)
        checks["html_description_present"]=bool(meta_desc)
        if not title: warnings.append("Rendered HTML title is missing")
        if not meta_desc: warnings.append("Rendered meta description is missing")
        robots=soup.find("meta",attrs={"name":re.compile("^robots$",re.I)})
        robots_value=(robots.get("content") or "").lower() if robots else ""
        checks["not_noindex"]="noindex" not in robots_value
        if not checks["not_noindex"]: warnings.append("Rendered page has noindex directive")
        h1=soup.find_all("h1")
        checks["single_h1"]=len(h1)==1
        if not checks["single_h1"]: warnings.append(f"Expected one H1; found {len(h1)}")
        images=soup.find_all("img")
        missing_alt=sum(1 for img in images if not (img.get("alt") or "").strip())
        checks["images_have_alt"]=missing_alt==0
        if missing_alt: warnings.append(f"{missing_alt} image(s) missing descriptive alt text")
        iframes=soup.find_all("iframe")
        video_embeds=[f for f in iframes if any(x in (f.get("src") or "") for x in ("youtube.com","youtube-nocookie.com"))]
        schema_types=[]
        for node in soup.find_all("script",type="application/ld+json"):
            try:
                obj=json.loads(node.string or node.get_text())
                stack=obj if isinstance(obj,list) else [obj]
                while stack:
                    item=stack.pop()
                    if isinstance(item,dict):
                        typ=item.get("@type")
                        schema_types.extend(typ if isinstance(typ,list) else [typ] if typ else [])
                        graph=item.get("@graph")
                        if isinstance(graph,list): stack.extend(graph)
            except Exception: warnings.append("Invalid JSON-LD block")
        has_video="VideoObject" in schema_types
        checks["videoobject_when_embedded"]=(not video_embeds) or has_video
        if video_embeds and not has_video: warnings.append("YouTube embed has no VideoObject structured data")
        checks["page_reachable"]=True
        page={"html_title":title,"html_description_length":len(meta_desc),"h1_count":len(h1),"word_count_rendered":words,"image_count":len(images),"missing_image_alt":missing_alt,"video_embed_count":len(video_embeds),"schema_types":schema_types,"robots":robots_value,"final_url":final}
    except Exception as exc:
        checks["page_reachable"]=False
        warnings.append(f"Public page fetch failed: {exc}")
    checks["body_word_count"]=words
    # Editorial news pages need substantial original value; catalogue profiles may be concise by design.
    is_catalog=any(t.startswith("catalog-") for t in article.get("tags",[]))
    if not is_catalog and words<250: warnings.append(f"Thin editorial content warning: {words} words (target at least 250 words of useful original context)")
    if is_catalog and words<80: warnings.append(f"Thin catalogue entry warning: {words} words")
    score_checks=[v for v in checks.values() if isinstance(v,bool)]
    score=round(100*sum(score_checks)/max(1,len(score_checks)))
    return {"id":article["id"],"title":article["title"],"handle":handle,"url":url,"published":article.get("isPublished"),"word_count":words,"score":score,"checks":checks,"warnings":warnings,"page":page}

def main():
    blog_id=guard_and_blog()
    articles=get_articles(blog_id)
    sitemap_urls,sitemap_notes=read_sitemap()
    robots=robots_check()
    results=[audit_article(a,sitemap_urls) for a in articles if a.get("isPublished")]
    summary={
      "site":f"https://{EXPECTED_HOST}","generated_at":datetime.now(timezone.utc).isoformat(),
      "scope":"Read-only Shopify article and public technical SEO audit; no theme/content writes",
      "articles_checked":len(results),"average_score":round(sum(x["score"] for x in results)/max(1,len(results)),1),
      "warning_count":sum(len(x["warnings"]) for x in results),
      "robots":robots,"sitemap_notes":sitemap_notes,"articles":results
    }
    os.makedirs(OUT,exist_ok=True)
    with open(os.path.join(OUT,"seo-audit.json"),"w",encoding="utf-8") as f: json.dump(summary,f,ensure_ascii=False,indent=2)
    lines=["# VALUTED MUSIC — SEO audit", "",f"- Generated: {summary['generated_at']}",f"- Published articles checked: {summary['articles_checked']}",f"- Average technical/content score: {summary['average_score']}/100",f"- Total warnings: {summary['warning_count']}","- Scope: read-only; no Shopify content, URLs, or themes changed.","- Google indexing status: not available from this audit; verify in Google Search Console.","", "## Site-wide checks",f"- robots.txt reachable: {robots.get('reachable')}",f"- robots.txt disallows all: {robots.get('disallow_all')}",f"- Blog sitemap notes: {'; '.join(sitemap_notes) or 'none'}",""]
    for item in results:
        lines += [f"## {item['title']}",f"- URL: {item['url']}",f"- Score: {item['score']}/100",f"- Words: {item['word_count']}"]
        lines += [f"- Warning: {w}" for w in item["warnings"]] or ["- No warnings from configured checks."]
        lines.append("")
    with open(os.path.join(OUT,"seo-audit.md"),"w",encoding="utf-8") as f:f.write("\n".join(lines))
    print(f"SEO AUDIT COMPLETE: articles={len(results)}; average_score={summary['average_score']}; warnings={summary['warning_count']}; read_only=true",flush=True)
    if not robots.get("reachable") or robots.get("disallow_all"):
        print("SITE-WIDE WARNING: robots.txt unavailable or appears to disallow all crawlers.",flush=True)

if __name__=="__main__":
    try: main()
    except Exception as exc:
        print("SEO AUDIT FAILED CLOSED: "+str(exc),flush=True);sys.exit(1)
