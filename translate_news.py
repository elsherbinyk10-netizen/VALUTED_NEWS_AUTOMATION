"""Register machine translations for Shopify articles and pages.

Uses Google Translate's public web endpoint as a no-key fallback. It is not an SLA-backed
translation API; the script rate-limits requests and logs failures rather than publishing
empty/partial translations. Set TRANSLATION_MAX_RESOURCES_PER_RUN to tune backlog speed.
"""
import html
import json
import logging
import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup, NavigableString
from news_worker import env, shopify_graphql, clean_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOCALES = ["ar", "de", "es", "fr", "it", "ja", "ko", "pt-BR", "ru", "tr", "zh-CN"]
SHOP = env("SHOPIFY_STORE_DOMAIN")
MAX_RESOURCES = max(1, min(10, int(env("TRANSLATION_MAX_RESOURCES_PER_RUN", "2"))))
HEADERS = {"User-Agent": "ValutedNewsTranslationWorker/1.0"}


def graphql(query, variables=None):
    return shopify_graphql(query, variables or {})


def list_resources():
    query = """
    query TranslationQueue {
      blog(id: "gid://shopify/Blog/126010065175") {
        articles(first: 250, reverse: true) { nodes { id title isPublished publishedAt } }
      }
      pages(first: 250) { nodes { id title isPublished } }
    }
    """
    data = graphql(query)
    articles = (data.get("blog") or {}).get("articles", {}).get("nodes", [])
    pages = data.get("pages", {}).get("nodes", [])
    # Published articles first, then published editorial/category pages.
    resources = [{"id": a["id"], "title": a["title"], "kind": "article"} for a in articles if a.get("isPublished")]
    resources += [{"id": p["id"], "title": p["title"], "kind": "page"} for p in pages if p.get("isPublished")]
    return resources


def translate_plain(text, locale):
    if not text or not text.strip():
        return text
    target = locale.replace("-BR", "-BR")
    # Split long content to avoid URL and service limits; keep chunks at sentence/word boundaries.
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= 2200:
            chunks.append(remaining)
            break
        cut = remaining.rfind(" ", 0, 2200)
        if cut < 1000:
            cut = 2200
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    output = []
    for chunk in chunks:
        params = {"client": "gtx", "sl": "en", "tl": target, "dt": "t", "q": chunk}
        response = requests.get("https://translate.googleapis.com/translate_a/single", params=params, headers=HEADERS, timeout=(5, 25))
        response.raise_for_status()
        payload = response.json()
        translated = "".join(part[0] for part in payload[0] if part and part[0])
        if not translated:
            raise RuntimeError("Translation service returned an empty result.")
        output.append(translated)
        time.sleep(0.25)
    return "".join(output)


def translate_html_preserving_tags(markup, locale):
    if not markup:
        return markup
    soup = BeautifulSoup(markup, "html.parser")
    nodes = [n for n in soup.find_all(string=True) if isinstance(n, NavigableString)
             and n.strip() and n.parent and n.parent.name not in ("script", "style", "code", "pre")]
    if not nodes:
        return markup
    # Translate groups of text nodes while preserving original markup structure.
    for start in range(0, len(nodes), 8):
        group = nodes[start:start + 8]
        marker_map = {}
        combined_parts = []
        for i, node in enumerate(group):
            marker = "ZXQMARK" + str(i) + "QXZ"
            marker_map[marker] = node
            combined_parts.append(str(node))
            combined_parts.append(" " + marker + " ")
        translated = translate_plain(" ".join(combined_parts), locale)
        for marker, node in marker_map.items():
            if marker not in translated:
                # Conservative fallback: translate node separately if the service alters markers.
                value = translate_plain(str(node), locale)
            else:
                value = translated.split(marker, 1)[0]
                # Find the next marker's boundary using the original marker ordering.
                idx = list(marker_map).index(marker)
                next_marker = list(marker_map)[idx + 1] if idx + 1 < len(marker_map) else None
                if next_marker and next_marker in translated:
                    segment = translated.split(marker, 1)[1].split(next_marker, 1)[0]
                    value = segment.strip()
                else:
                    value = translated.split(marker, 1)[1].strip() if marker in translated else value
            value = value.strip()
            if value:
                node.replace_with(value)
    return str(soup)


def get_resource(resource_id):
    query = """
    query GetTranslatableResource($id: ID!) {
      translatableResource(resourceId: $id) {
        resourceId
        translatableContent { key value digest type }
        translations(locale: "ar") { key value outdated }
        translationsDe: translations(locale: "de") { key value outdated }
        translationsEs: translations(locale: "es") { key value outdated }
        translationsFr: translations(locale: "fr") { key value outdated }
        translationsIt: translations(locale: "it") { key value outdated }
        translationsJa: translations(locale: "ja") { key value outdated }
        translationsKo: translations(locale: "ko") { key value outdated }
        translationsPt: translations(locale: "pt-BR") { key value outdated }
        translationsRu: translations(locale: "ru") { key value outdated }
        translationsTr: translations(locale: "tr") { key value outdated }
        translationsZh: translations(locale: "zh-CN") { key value outdated }
      }
    }
    """
    data = graphql(query, {"id": resource_id})
    return data.get("translatableResource")


def register_translations(resource_id, translations):
    mutation = """
    mutation RegisterNewsTranslations($resourceId: ID!, $translations: [TranslationInput!]!) {
      translationsRegister(resourceId: $resourceId, translations: $translations) {
        translations { locale key value }
        userErrors { field message }
      }
    }
    """
    data = graphql(mutation, {"resourceId": resource_id, "translations": translations})
    result = data.get("translationsRegister") or {}
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError("Shopify rejected translations: " + json.dumps(errors, ensure_ascii=False))
    return result.get("translations") or []


def main():
    if not SHOP:
        raise RuntimeError("Missing SHOPIFY_STORE_DOMAIN.")
    resources = list_resources()
    # Persist queue progress across runs. New/updated resources are rechecked every run.
    from pathlib import Path
    state_path = Path(__file__).resolve().parent / "data" / "translation_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"done": {}}
    except Exception:
        state = {"done": {}}
    done = state.setdefault("done", {})
    todo = [r for r in resources if not done.get(r["id"])]
    if not todo:
        logging.info("No unprocessed resources found; checking first %d resources for missing locale coverage.", MAX_RESOURCES)
        todo = resources[:MAX_RESOURCES]
    selected = todo[:MAX_RESOURCES]
    logging.info("Translation queue resources=%d pending=%d selected=%d locales=%d", len(resources), len(todo), len(selected), len(LOCALES))
    failures = 0
    for resource in selected:
        try:
            translatable = get_resource(resource["id"])
            if not translatable:
                logging.warning("No translatable resource for %s", resource["title"])
                continue
            contents = translatable.get("translatableContent") or []
            existing_by_locale = {}
            for alias, locale in zip(["translations","translationsDe","translationsEs","translationsFr","translationsIt","translationsJa","translationsKo","translationsPt","translationsRu","translationsTr","translationsZh"], LOCALES):
                existing_by_locale[locale] = {t["key"]: t for t in (translatable.get(alias) or [])}
            inputs = []
            for locale in LOCALES:
                existing = existing_by_locale.get(locale, {})
                for item in contents:
                    key, value, digest = item.get("key"), item.get("value", ""), item.get("digest")
                    if not key or not digest or not value or key.lower() in ("handle", "url"):
                        continue
                    if key in existing and existing[key].get("value") and not existing[key].get("outdated"):
                        continue
                    if key not in ("title", "body", "summary", "meta_title", "meta_description", "seo.title", "seo.description"):
                        continue
                    if key in ("body",) or re.search(r"<[a-z][^>]*>", value, re.I):
                        translated = translate_html_preserving_tags(value, locale)
                    else:
                        translated = translate_plain(value, locale)
                    if not translated or translated.strip() == value.strip():
                        logging.warning("Translation unchanged/empty; skipping %s %s %s", resource["title"], locale, key)
                        continue
                    inputs.append({"locale": locale, "key": key, "value": translated, "translatableContentDigest": digest})
                    time.sleep(0.3)
            if inputs:
                registered = register_translations(resource["id"], inputs)
                logging.info("Registered %d translations for %s (%s)", len(registered), resource["title"], resource["kind"])
            else:
                logging.info("No missing translations to register for %s", resource["title"])
            done[resource["id"]] = {"title": resource["title"], "processed_at": time.time()}
        except Exception:
            failures += 1
            logging.exception("Translation failed for %s", resource["title"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
