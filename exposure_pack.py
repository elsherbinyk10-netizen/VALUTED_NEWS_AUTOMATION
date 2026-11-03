import argparse, html, json, re
from html.parser import HTMLParser
from pathlib import Path
from news_worker import shopify_graphql, env
class Text(HTMLParser):
 def __init__(self): super().__init__(); self.parts=[]
 def handle_data(self,d):
  x=re.sub(r"\s+"," ",d).strip()
  if x:self.parts.append(x)
def plain(v):
 p=Text();p.feed(str(v or ""));return re.sub(r"\s+"," ",html.unescape(" ".join(p.parts))).strip()
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--limit",type=int,default=5);a=ap.parse_args()
 q="""query Exposure($id: ID!, $n: Int!) { blog(id:$id) { articles(first:$n, reverse:true) { nodes { title handle summary body isPublished tags image { url } metafields(first:10,namespace:"global") { nodes { key value } } } } } }"""
 data=shopify_graphql(q,{"id":env("SHOPIFY_BLOG_ID"),"n":max(1,min(a.limit,10))})
 packs=[]
 for x in (data.get("blog") or {}).get("articles",{}).get("nodes",[]):
  if not x.get("isPublished") or not x.get("handle"):continue
  title=plain(x.get("title"));url="https://valutednews.com/blogs/news/"+x["handle"];summary=plain(x.get("summary")) or plain(x.get("body"))[:230]
  meta={m.get("key"):m.get("value","") for m in (x.get("metafields") or {}).get("nodes",[])}
  st=meta.get("title_tag") or title;sd=meta.get("description_tag") or summary;image=(x.get("image") or {}).get("url","")
  tags=[]
  for t in list(x.get("tags") or [])+re.findall(r"[A-Za-z0-9]+",title):
   z="".join(w.title() for w in re.findall(r"[A-Za-z0-9]+",str(t)))
   if len(z)>2 and z.lower() not in {"the","and","with","from","news","today"} and "#"+z not in tags:tags.append("#"+z)
  packs.append({"title":title,"url":url,"seo_title":st,"meta_description":sd,"image_url":image,"social":{"facebook":f"{title}\n\n{summary}\n\nRead the full report: {url}","instagram":f"{title}\n\n{summary}\n\nLink in bio.\n{' '.join(tags[:8])}","x":f"{title[:180]}\n{url}","linkedin":f"{title}\n\n{summary}\n\n{url}","pinterest":f"{title} — {summary} {url}"},"audit":{"title_70_or_less":len(st)<=70,"description_110_to_160":110<=len(sd)<=160,"image_present":bool(image),"canonical_url_present":True}})
 Path("exposure_output").mkdir(exist_ok=True);Path("exposure_output/valuted-news-exposure.json").write_text(json.dumps(packs,ensure_ascii=False,indent=2),encoding="utf-8")
 lines=["# Valuted News — exposure pack",""]
 for p in packs:
  lines += [f"## {p['title']}",f"URL: {p['url']}",f"SEO title: {p['seo_title']}",f"Meta description: {p['meta_description']}",f"Image: {p['image_url'] or 'MISSING'}",""]
  for k,v in p["social"].items():lines += [f"### {k.title()}",v,""]
  lines += ["### SEO checks"]+[f"- [{'x' if v else ' '}] {k}" for k,v in p["audit"].items()]+[""]
 Path("exposure_output/valuted-news-exposure.md").write_text("\n".join(lines),encoding="utf-8")
 print(f"Generated exposure packs for {len(packs)} Valuted News articles.")
if __name__=="__main__":main()
