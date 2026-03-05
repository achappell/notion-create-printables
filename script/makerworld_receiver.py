#!/usr/bin/env python3
import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import makerworld_to_notion as sync


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_env_file(env_file: str):
    if not os.path.exists(env_file):
        return
    with open(env_file, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


def normalize_item(item: dict) -> dict:
    model_id = str(item.get("model_id") or item.get("modelId") or "").strip()
    model_url = str(item.get("model_url") or item.get("modelUrl") or "").strip()
    model_name = str(item.get("model_name") or item.get("modelName") or "").strip()

    if not model_id:
        return {}
    if not model_url:
        model_url = f"{sync.MAKERWORLD_BASE}/en/models/{model_id}"
    if not model_name:
        model_name = f"Model {model_id}"

    return {
        "model_id": model_id,
        "model_url": model_url,
        "model_name": model_name,
        "creator": str(item.get("creator") or "").strip(),
        "cover_image_url": str(item.get("cover_image_url") or item.get("coverImageUrl") or "").strip(),
        "tags": str(item.get("tags") or "").strip(),
        "print_profile_details": str(item.get("print_profile_details") or item.get("printProfileDetails") or "").strip(),
        "parsed_nozzle": str(item.get("parsed_nozzle") or item.get("parsedNozzle") or "").strip(),
        "parsed_material": str(item.get("parsed_material") or item.get("parsedMaterial") or "").strip(),
        "model_title": str(item.get("model_title") or item.get("modelTitle") or "").strip(),
    }


def upsert_items(items: list, notion_token: str, dry_run: bool, verbose: bool, enrich_missing: bool) -> dict:
    created = 0
    updated = 0
    skipped = 0
    errors = 0
    details_log = []

    for raw_item in items:
        item = normalize_item(raw_item)
        if not item:
            skipped += 1
            continue

        try:
            details = {
                "creator": item["creator"],
                "cover_image_url": item["cover_image_url"],
                "tags": item["tags"],
                "print_profile_details": item["print_profile_details"],
                "parsed_nozzle": item["parsed_nozzle"],
                "parsed_material": item["parsed_material"],
                "model_title": item["model_title"],
            }

            if enrich_missing and (not details["creator"] or not details["cover_image_url"] or not details["model_title"]):
                try:
                    fetched = sync.fetch_model_details(item["model_url"])
                    for k, v in fetched.items():
                        if not details.get(k):
                            details[k] = v
                except Exception:
                    pass

            properties = sync.build_notion_properties(item, details)
            existing = sync.notion_find_by_model_id(notion_token, item["model_id"])
            action = "create"
            page_id = None

            if existing:
                action = "update"
                page_id = existing.get("id")
            else:
                existing_by_url = sync.notion_find_by_url(notion_token, item["model_url"])
                if existing_by_url:
                    action = "update"
                    page_id = existing_by_url.get("id")

            if dry_run:
                if action == "create":
                    created += 1
                elif action == "update":
                    updated += 1
                else:
                    skipped += 1
            else:
                if action == "update" and page_id:
                    sync.notion_update_page(notion_token, page_id, properties)
                    updated += 1
                elif action == "create":
                    sync.notion_create_page(notion_token, properties)
                    created += 1
                else:
                    skipped += 1

            if verbose:
                details_log.append({
                    "action": action,
                    "model_id": item["model_id"],
                    "model_url": item["model_url"],
                    "properties": properties,
                })

            time.sleep(0.1)
        except Exception as e:
            errors += 1
            details_log.append({
                "model_id": item.get("model_id", ""),
                "model_url": item.get("model_url", ""),
                "error": str(e),
                "endpoint": getattr(e, "url", ""),
            })

    return {
        "fetched": len(items),
        "createdCount": created,
        "updatedCount": updated,
        "skippedCount": skipped,
        "errorCount": errors,
        "dryRun": dry_run,
        "details": details_log,
    }


class SyncHandler(BaseHTTPRequestHandler):
    server_version = "MakerWorldReceiver/1.0"

    def _write_json(self, status: int, payload: dict):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._write_json(200, {"ok": True, "service": "makerworld_receiver"})
            return
        self._write_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/sync":
            self._write_json(404, {"error": "Not found"})
            return

        content_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._write_json(400, {"error": "Invalid JSON body"})
            return

        items = payload.get("items") or []
        if not isinstance(items, list):
            self._write_json(400, {"error": "items must be an array"})
            return

        notion_token = os.getenv("NOTION_TOKEN", "").strip()
        if not notion_token:
            self._write_json(500, {"error": "Missing NOTION_TOKEN in environment"})
            return

        ok, preflight_error = sync.notion_preflight(notion_token)
        if not ok:
            self._write_json(500, {"error": preflight_error})
            return

        dry_run = bool(payload.get("dryRun", False))
        verbose = bool(payload.get("verbose", False))
        enrich_missing = bool(payload.get("enrichMissing", True))

        result = upsert_items(items, notion_token, dry_run=dry_run, verbose=verbose, enrich_missing=enrich_missing)
        status = 200 if result["errorCount"] == 0 else 207
        self._write_json(status, result)


def main():
    parser = argparse.ArgumentParser(description="Local receiver for MakerWorld Tampermonkey sync.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--env-file", default=os.path.join(os.path.dirname(__file__), ".env"))
    args = parser.parse_args()

    load_env_file(args.env_file)

    server = HTTPServer((args.host, args.port), SyncHandler)
    print(f"Listening on http://{args.host}:{args.port}")
    print("Endpoints: GET /health, POST /sync")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
