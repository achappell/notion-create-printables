#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import socket
from datetime import datetime, timezone
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

MAKERWORLD_BASE = "https://makerworld.com"
NOTION_VERSION = "2022-06-28"
NOTION_DATABASE_ID = "30f4fc50af3f80a1a702e7862de7187a"
HTTP_TIMEOUT_SECONDS = 30
HTTP_RETRIES = 3
HTTP_RETRY_BASE_SECONDS = 1.0
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
VALID_CATEGORIES = {
    "Template",
    "Ebook",
    "Preset",
    "Course",
    "Bundle",
    "TKD Belts",
    "Toy",
    "Printer Tools",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def strip_tags(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", unescape(no_tags)).strip()


def is_generic_model_name(value: str) -> bool:
    return bool(re.fullmatch(r"Model\s+\d+", (value or "").strip(), re.IGNORECASE))


def slug_to_title(slug: str) -> str:
    clean = re.sub(r"[-_]+", " ", slug or "").strip()
    return re.sub(r"\s+", " ", clean)


def http_get(url: str, headers=None) -> str:
    last_error = None
    for attempt in range(HTTP_RETRIES):
        try:
            req = Request(url, headers=headers or {})
            with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            if e.code in RETRYABLE_HTTP_STATUS and attempt < HTTP_RETRIES - 1:
                time.sleep(HTTP_RETRY_BASE_SECONDS * (2 ** attempt))
                continue
            raise
        except (URLError, TimeoutError, socket.timeout) as e:
            last_error = e
            if attempt < HTTP_RETRIES - 1:
                time.sleep(HTTP_RETRY_BASE_SECONDS * (2 ** attempt))
                continue
            raise
    raise last_error


def http_post_json(url: str, payload: dict, headers=None) -> dict:
    last_error = None
    body = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    for attempt in range(HTTP_RETRIES):
        try:
            req = Request(url, data=body, headers=req_headers, method="POST")
            with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except HTTPError as e:
            if e.code in RETRYABLE_HTTP_STATUS and attempt < HTTP_RETRIES - 1:
                time.sleep(HTTP_RETRY_BASE_SECONDS * (2 ** attempt))
                continue
            raise
        except (URLError, TimeoutError, socket.timeout) as e:
            last_error = e
            if attempt < HTTP_RETRIES - 1:
                time.sleep(HTTP_RETRY_BASE_SECONDS * (2 ** attempt))
                continue
            raise
    raise last_error


def http_patch_json(url: str, payload: dict, headers=None) -> dict:
    last_error = None
    body = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    for attempt in range(HTTP_RETRIES):
        try:
            req = Request(url, data=body, headers=req_headers, method="PATCH")
            with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except HTTPError as e:
            if e.code in RETRYABLE_HTTP_STATUS and attempt < HTTP_RETRIES - 1:
                time.sleep(HTTP_RETRY_BASE_SECONDS * (2 ** attempt))
                continue
            raise
        except (URLError, TimeoutError, socket.timeout) as e:
            last_error = e
            if attempt < HTTP_RETRIES - 1:
                time.sleep(HTTP_RETRY_BASE_SECONDS * (2 ** attempt))
                continue
            raise
    raise last_error


def parse_likes_html(html: str):
    results = []
    seen = set()
    pattern = re.compile(r'<a[^>]*href="([^"]*/models/(\d+)[^"]*)"[^>]*>([\s\S]*?)</a>', re.IGNORECASE)
    for match in pattern.finditer(html):
        href, model_id, label = match.groups()
        # Use canonical numeric model URL to avoid stale slug 404s.
        model_url = f"{MAKERWORLD_BASE}/en/models/{model_id.strip()}"
        slug_match = re.search(r"/models/\d+-([^/?#]+)", href)
        slug_title = slug_to_title(slug_match.group(1)) if slug_match else ""
        label_title = strip_tags(label)
        model_name = label_title if label_title and not is_generic_model_name(label_title) else slug_title
        if model_url in seen:
            continue
        seen.add(model_url)
        results.append({
            "model_id": model_id.strip(),
            "model_name": model_name or f"Model {model_id}",
            "model_url": model_url,
        })
    return results


def extract_json_ld(html: str):
    out = []
    pattern = re.compile(r'<script[^>]*type="application/ld\\+json"[^>]*>([\\s\\S]*?)</script>', re.IGNORECASE)
    for m in pattern.finditer(html):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except Exception:
            continue
    return out


def flatten_jsonld(obj):
    if isinstance(obj, list):
        items = []
        for x in obj:
            items.extend(flatten_jsonld(x))
        return items
    if isinstance(obj, dict):
        items = [obj]
        graph = obj.get("@graph")
        if isinstance(graph, list):
            items.extend(flatten_jsonld(graph))
        return items
    return []


def read_meta(html: str, prop: str) -> str:
    m = re.search(rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    return strip_tags(m.group(1)) if m else ""


def collect_meta_values(html: str, attr: str, key: str) -> list[str]:
    pattern = re.compile(
        rf'<meta[^>]+{re.escape(attr)}=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    return [strip_tags(m.group(1)) for m in pattern.finditer(html) if strip_tags(m.group(1))]


def choose_best_image_url(candidates: list[str], model_id: str) -> str:
    def score(url: str) -> int:
        u = (url or "").lower()
        s = 0
        if model_id and model_id in u:
            s += 100
        if "model" in u:
            s += 20
        if any(x in u for x in ["cover", "preview", "thumbnail", "thumb", "render"]):
            s += 15
        if any(x in u for x in ["avatar", "profile", "logo", "icon", "user", "banner"]):
            s -= 60
        if "/models/" in u:
            s += 10
        return s

    deduped = []
    seen = set()
    for c in candidates:
        if not c:
            continue
        normalized = urljoin(MAKERWORLD_BASE, c)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    if not deduped:
        return ""
    ranked = sorted(deduped, key=score, reverse=True)
    return ranked[0]


def parse_profile_details(html: str) -> str:
    bits = []
    nozzle_value = ""
    material_value = ""
    nozzle = re.search(r'(?:Nozzle|nozzle)[^\n<]{0,60}(\d(?:\.\d+)?\s*mm)', html)
    layer = re.search(r'(?:Layer\s*Height|layer\s*height)[^\n<]{0,60}(\d(?:\.\d+)?\s*mm)', html)
    material = re.search(r'(?:Material|material)[^\n<]{0,80}(PLA|PETG|ABS|ASA|TPU|PA|PC)', html, re.IGNORECASE)
    if nozzle:
        nozzle_value = re.sub(r"\s+", "", nozzle.group(1))
        bits.append(f"Nozzle {nozzle_value}")
    if layer:
        layer_value = re.sub(r"\s+", "", layer.group(1))
        bits.append(f"Layer {layer_value}")
    if material:
        material_value = material.group(1).upper()
        bits.append(f"Material {material_value}")
    return {
        "text": " | ".join(bits),
        "nozzle": nozzle_value,
        "material": material_value,
    }


def fetch_model_details(model_url: str, request_headers=None):
    try:
        html = http_get(model_url, headers=request_headers or {"User-Agent": "Mozilla/5.0 (makerworld-notion-sync/1.0)"})
    except Exception:
        return {"creator": "", "cover_image_url": "", "tags": "", "print_profile_details": "", "model_title": ""}

    creator = ""
    cover_image_url = ""
    tags = []

    for obj in flatten_jsonld(extract_json_ld(html)):
        if not creator:
            author = obj.get("author")
            if isinstance(author, str):
                creator = author
            elif isinstance(author, dict):
                creator = author.get("name", "")
            elif isinstance(author, list) and author:
                first = author[0]
                if isinstance(first, str):
                    creator = first
                elif isinstance(first, dict):
                    creator = first.get("name", "")
        if not cover_image_url:
            image = obj.get("image")
            if isinstance(image, str):
                cover_image_url = image
            elif isinstance(image, list) and image and isinstance(image[0], str):
                cover_image_url = image[0]
            elif isinstance(image, dict):
                cover_image_url = image.get("url", "")
        if not tags:
            keywords = obj.get("keywords")
            if isinstance(keywords, list):
                tags = [str(t).strip() for t in keywords if str(t).strip()]
            elif isinstance(keywords, str):
                tags = [t.strip() for t in keywords.split(",") if t.strip()]

    if not creator:
        creator = read_meta(html, "og:site_name")
    image_candidates = []
    if cover_image_url:
        image_candidates.append(cover_image_url)
    image_candidates.extend(collect_meta_values(html, "property", "og:image"))
    image_candidates.extend(collect_meta_values(html, "name", "twitter:image"))
    image_candidates.extend(collect_meta_values(html, "property", "twitter:image"))

    model_id_match = re.search(r"/models/(\d+)", model_url)
    model_id = model_id_match.group(1) if model_id_match else ""
    cover_image_url = choose_best_image_url(image_candidates, model_id)
    model_title = read_meta(html, "og:title")
    if model_title:
        model_title = re.sub(r"\s*[-|]\s*MakerWorld\s*$", "", model_title, flags=re.IGNORECASE).strip()

    profile = parse_profile_details(html)

    return {
        "creator": creator,
        "cover_image_url": urljoin(MAKERWORLD_BASE, cover_image_url) if cover_image_url else "",
        "tags": ", ".join(tags[:20]),
        "print_profile_details": profile["text"],
        "parsed_nozzle": profile["nozzle"],
        "parsed_material": profile["material"],
        "model_title": model_title,
    }


def notion_headers(token: str):
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }


def notion_exists_by_url(token: str, model_url: str) -> bool:
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "URL",
            "url": {"equals": model_url},
        },
        "page_size": 1,
    }
    res = http_post_json(url, payload, headers=notion_headers(token))
    return bool(res.get("results"))


def notion_find_by_model_id(token: str, model_id: str):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "Model ID",
            "rich_text": {"equals": model_id},
        },
        "page_size": 1,
    }
    res = http_post_json(url, payload, headers=notion_headers(token))
    results = res.get("results") or []
    return results[0] if results else None


def notion_find_by_url(token: str, model_url: str):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "URL",
            "url": {"equals": model_url},
        },
        "page_size": 1,
    }
    res = http_post_json(url, payload, headers=notion_headers(token))
    results = res.get("results") or []
    return results[0] if results else None


def notion_preflight(token: str) -> tuple[bool, str]:
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"page_size": 1}
    try:
        http_post_json(url, payload, headers=notion_headers(token))
        return True, ""
    except HTTPError as e:
        endpoint = getattr(e, "url", url)
        return False, f"Notion preflight failed: HTTP {e.code} for {endpoint}"
    except Exception as e:
        return False, f"Notion preflight failed: {e}"


def build_notion_properties(item: dict, details: dict):
    resolved_name = item["model_name"]
    if is_generic_model_name(resolved_name) and details.get("model_title"):
        resolved_name = details["model_title"]

    properties = {
        "Name": {
            "title": [{"text": {"content": resolved_name[:1800]}}]
        },
        "Model ID": {
            "rich_text": [{"text": {"content": item["model_id"][:1800]}}]
        },
        "URL": {"url": item["model_url"]},
        "Creator": {
            "rich_text": ([{"text": {"content": details["creator"][:1800]}}] if details["creator"] else [])
        },
        "Cover Image URL": {"url": details["cover_image_url"] or None},
        "Cover Image": {
            "files": (
                [{
                    "name": f"makerworld-{item['model_id']}-cover",
                    "type": "external",
                    "external": {"url": details["cover_image_url"]},
                }]
                if details["cover_image_url"]
                else []
            )
        },
        "Tags": {
            "rich_text": ([{"text": {"content": details["tags"][:1800]}}] if details["tags"] else [])
        },
        "Print Profile Details": {
            "rich_text": ([{"text": {"content": details["print_profile_details"][:1800]}}] if details["print_profile_details"] else [])
        },
        "Scraped At": {"date": {"start": now_iso()}},
    }

    nozzle = (details.get("parsed_nozzle") or "").strip()
    if nozzle in {"0.2mm", "0.4mm"}:
        properties["Nozzle"] = {"select": {"name": nozzle}}

    material = (details.get("parsed_material") or "").strip().upper()
    material_page_id = os.getenv(f"MATERIAL_PAGE_ID_{material}", "").strip()
    if material_page_id:
        properties["Material"] = {"relation": [{"id": material_page_id}]}

    category = os.getenv("MAKERWORLD_CATEGORY", "Printer Tools").strip()
    if category in VALID_CATEGORIES:
        properties["Category"] = {"select": {"name": category}}

    return properties


def notion_create_page(token: str, properties: dict):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }
    return http_post_json(url, payload, headers=notion_headers(token))


def notion_update_page(token: str, page_id: str, properties: dict):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": properties,
    }
    return http_patch_json(url, payload, headers=notion_headers(token))


def main():
    parser = argparse.ArgumentParser(description="Sync MakerWorld likes into Notion Printables.")
    parser.add_argument("--dry-run", action="store_true", help="Compute actions and print them without writing to Notion.")
    parser.add_argument("--verbose", action="store_true", help="Print per-item action details.")
    parser.add_argument("--model-id", type=str, default="", help="Sync only a single MakerWorld model ID.")
    args = parser.parse_args()

    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    likes_url = os.getenv("MAKERWORLD_LIKES_URL", "").strip()
    makerworld_cookie = os.getenv("MAKERWORLD_COOKIE", "").strip()

    if not notion_token:
        print("Missing NOTION_TOKEN")
        return 2
    if not likes_url and not args.model_id:
        print("Missing MAKERWORLD_LIKES_URL")
        return 2

    ok, preflight_error = notion_preflight(notion_token)
    if not ok:
        print(preflight_error)
        print("Make sure your Notion integration is shared with the Printables database.")
        return 1

    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://makerworld.com/",
    }
    if makerworld_cookie:
        browser_headers["Cookie"] = makerworld_cookie

    if args.model_id:
        single_id = re.sub(r"\D+", "", args.model_id.strip())
        if not single_id:
            print("Invalid --model-id. Use numeric ID, e.g. --model-id 123456")
            return 2
        models = [{
            "model_id": single_id,
            "model_name": f"Model {single_id}",
            "model_url": f"{MAKERWORLD_BASE}/en/models/{single_id}",
        }]
    else:
        try:
            likes_html = http_get(likes_url, headers=browser_headers)
            models = parse_likes_html(likes_html)
        except (HTTPError, URLError) as e:
            print(f"Failed to fetch likes page: {e}")
            print("If this is 403, set MAKERWORLD_COOKIE in script/.env from your browser session.")
            return 1

    if not models:
        print("No models found. Check your likes URL and page visibility.")
        return 1

    created = 0
    updated = 0
    skipped = 0
    errors = 0

    for item in models:
        try:
            # Detail enrichment is best-effort; do not fail row creation.
            try:
                details = fetch_model_details(item["model_url"], request_headers=browser_headers)
            except Exception:
                details = {
                    "creator": "",
                    "cover_image_url": "",
                    "tags": "",
                    "print_profile_details": "",
                    "parsed_nozzle": "",
                    "parsed_material": "",
                    "model_title": "",
                }

            properties = build_notion_properties(item, details)
            existing = notion_find_by_model_id(notion_token, item["model_id"])
            action = "create"
            page_id = None

            if existing:
                action = "update"
                page_id = existing.get("id")
            else:
                existing_by_url = notion_find_by_url(notion_token, item["model_url"])
                if existing_by_url:
                    action = "update"
                    page_id = existing_by_url.get("id")

            if args.verbose:
                print(json.dumps({
                    "action": action,
                    "model_id": item["model_id"],
                    "model_url": item["model_url"],
                    "properties": properties,
                }, indent=2))

            if args.dry_run:
                if action == "create":
                    created += 1
                elif action == "update":
                    updated += 1
                else:
                    skipped += 1
                continue

            if action == "update" and page_id:
                notion_update_page(notion_token, page_id, properties)
                updated += 1
            elif action == "create":
                notion_create_page(notion_token, properties)
                created += 1
            else:
                skipped += 1

            time.sleep(0.2)
        except Exception as e:
            errors += 1
            endpoint = getattr(e, "url", "")
            if endpoint:
                print(f"Error for {item['model_url']}: {e} (endpoint: {endpoint})")
            else:
                print(f"Error for {item['model_url']}: {e}")

    print(json.dumps({
        "timestamp": now_iso(),
        "fetched": len(models),
        "createdCount": created,
        "updatedCount": updated,
        "skippedCount": skipped,
        "errorCount": errors,
        "dryRun": args.dry_run,
    }, indent=2))

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
