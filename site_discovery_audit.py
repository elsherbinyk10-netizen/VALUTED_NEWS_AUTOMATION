import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

BASE = os.environ["SITE_URL"].rstrip("/")
ROBOTS_URL = BASE + "/robots.txt"
SITEMAP_URL = os.environ.get("SITEMAP_URL", BASE + "/sitemap.xml")
OUT = Path("exposure_output")
OUT.mkdir(exist_ok=True)

class PageMeta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts, self.meta, self.canonicals, self.jsonld = [], {}, [], []
        self.in_title = False
        self.in_jsonld = False
        self.jsonld_parts = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title": self.in_title = True
        if tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key in ("description", "robots", "og:title", "og:description"):
                self.meta[key] = a.get("content", "")
        if tag == "link" and "canonical" in (a.get("rel") or "").lower().split():
            self.canonicals.append(a.get("href", ""))
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.in_jsonld = True
            self.jsonld_parts = []
    def handle_endtag(self, tag):
        if tag == "title": self.in_title = False
        if tag == "script" and self.in_jsonld:
            self.jsonld.append("".join(self.jsonld_parts))
            self.in_jsonld = False
    def handle_data(self, data):
        if self.in_title: self.title_parts.append(data)
        if self.in_jsonld: self.jsonld_parts.append(data)

def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent":"ValutedNetworkExplorer/1.0 (+SEO audit)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), r.read(4_000_000).decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.geturl(), e.read(500_000).decode("utf-8", "replace"), dict(e.headers)
    except Exception as e:
        return 0, url, "", {"error": str(e)}

def sitemap_locs(xml_text):
    try:
        root = ET.fromstring(xml_text)
        locs = [x.text.strip() for x in root.iter() if x.tag.split("}")[-1] == "loc" and x.text]
        return root.tag.split("}")[-1], locs
    except Exception:
        return "invalid_xml", []

def main():
    report = {"site": BASE, "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "robots": {}, "sitemaps": [], "pages_checked": [], "issues": []}
    robots_status, robots_final, body, _ = get(ROBOTS_URL)
    report["robots"] = {"url": ROBOTS_URL, "http_status": robots_status, "final_url": robots_final, "has_sitemap_directive": bool(re.search(r"(?im)^\s*sitemap\s*:, body)), "body_excerpt": body[:6000]}
    if robots_status != 200: report["issues"].append("robots_txt_not_200")
    if not report["robots"]["has_sitemap_directive"]: report["issues"].append("robots_txt_missing_sitemap_directive")
    sitemap_status, sitemap_final, xml, _ = get(SITEMAP_URL)
    kind, locs = sitemap_locs(xml) if sitemap_status == 200 else ("unavailable", [])
    report["sitemaps"].append({"url": SITEMAP_URL, "http_status": sitemap_status, "final_url": sitemap_final, "type": kind, "entries": len(locs)})
    if sitemap_status != 200 or not locs: report["issues"].append("sitemap_unavailable_or_empty")
    urls = []
    if kind == "sitemapindex":
        for child in locs[:30]:
            cs, _, cx, _ = get(child)
            ck, cl = sitemap_locs(cx) if cs == 200 else ("unavailable", [])
            report["sitemaps"].append({"url": child, "http_status": cs, "type": ck, "entries": len(cl)})
            urls.extend(cl[:500])
    else:
        urls = locs
    report["total_sitemap_urls"] = len(urls)
    sample = urls[:min(25, len(urls))]
    for url in sample:
        ps, pf, html, _ = get(url)
        meta = PageMeta()
        if ps == 200: meta.feed(html)
        title = " ".join(" ".join(meta.title_parts).split())
        robots = meta.meta.get("robots", "")
        item = {"url": url, "http_status": ps, "final_url": pf, "title": title, "title_chars": len(title), "meta_description": meta.meta.get("description", ""), "canonical": meta.canonicals[0] if meta.canonicals else "", "canonical_count": len(meta.canonicals), "robots_meta": robots, "jsonld_blocks": len(meta.jsonld)}
        try:
            item["jsonld_valid"] = all(json.loads(x) is not None for x in meta.jsonld)
        except Exception:
            item["jsonld_valid"] = False
        if ps != 200: report["issues"].append("sitemap_page_not_200:" + url)
        if not title: report["issues"].append("missing_title:" + url)
        if not item["meta_description"]: report["issues"].append("missing_meta_description:" + url)
        if not item["canonical"]: report["issues"].append("missing_canonical:" + url)
        if item["canonical_count"] > 1: report["issues"].append("multiple_canonicals:" + url)
        if "noindex" in robots.lower(): report["issues"].append("noindex_meta:" + url)
        if meta.jsonld and not item["jsonld_valid"]: report["issues"].append("invalid_jsonld:" + url)
        report["pages_checked"].append(item)
    report["sample_size"] = len(sample)
    report["note"] = "A sampled technical audit only; it does not guarantee Google indexing or ranking. Search Console remains the source of truth for indexed status."
    (OUT / "site-discovery-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# Site discovery audit — {BASE}", "", f"- Robots HTTP: {robots_status}", f"- Sitemap URLs discovered: {len(urls)}", f"- Pages sampled: {len(sample)}", f"- Flags: {len(report['issues'])}", "", "## Issues"]
    lines += ["- " + x for x in report["issues"]] or ["- No sampled technical issues detected."]
    lines += ["", "## Sitemap summary"] + [f"- {x['url']}: HTTP {x['http_status']}, {x['entries']} entries ({x['type']})" for x in report["sitemaps"]]
    (OUT / "site-discovery-audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Audited {len(sample)} sitemap pages on {BASE}; {len(report['issues'])} flags.")
if __name__ == "__main__": main()
