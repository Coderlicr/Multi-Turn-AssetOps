#!/usr/bin/env python3
"""Inspect the local CouchDB sample databases created by docker compose."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter


COUCHDB_URL = os.environ.get("COUCHDB_URL", "http://localhost:5984").rstrip("/")
COUCHDB_USERNAME = os.environ.get("COUCHDB_USERNAME", "admin")
COUCHDB_PASSWORD = os.environ.get("COUCHDB_PASSWORD", "password")
IOT_DBNAME = os.environ.get("IOT_DBNAME", "chiller")
WO_DBNAME = os.environ.get("WO_DBNAME", "workorder")
VIBRATION_DBNAME = os.environ.get("VIBRATION_DBNAME", "vibration")


def _request_json(path: str, payload: dict | None = None) -> dict | list:
    url = f"{COUCHDB_URL}{path}"
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=headers)
    auth = f"{COUCHDB_USERNAME}:{COUCHDB_PASSWORD}".encode("utf-8")
    request.add_header("Authorization", f"Basic {base64.b64encode(auth).decode('ascii')}")

    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def get_db_info(db_name: str) -> dict:
    return _request_json(f"/{urllib.parse.quote(db_name)}")


def get_asset_counts(db_name: str) -> Counter:
    counts: Counter = Counter()
    bookmark = None
    while True:
        payload = {
            "selector": {"asset_id": {"$exists": True}},
            "fields": ["asset_id"],
            "limit": 50_000,
        }
        if bookmark:
            payload["bookmark"] = bookmark
        data = _request_json(f"/{urllib.parse.quote(db_name)}/_find", payload=payload)
        docs = data.get("docs", [])
        if not docs:
            break
        for doc in docs:
            asset_id = doc.get("asset_id")
            if asset_id:
                counts[asset_id] += 1
        new_bookmark = data.get("bookmark")
        if not new_bookmark or new_bookmark == bookmark:
            break
        bookmark = new_bookmark
    return counts


def main() -> int:
    try:
        databases = {
            IOT_DBNAME: get_db_info(IOT_DBNAME),
            WO_DBNAME: get_db_info(WO_DBNAME),
            VIBRATION_DBNAME: get_db_info(VIBRATION_DBNAME),
        }
        asset_counts = get_asset_counts(IOT_DBNAME)
    except urllib.error.HTTPError as exc:
        print(f"CouchDB returned HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Failed to reach CouchDB at {COUCHDB_URL}: {exc}", file=sys.stderr)
        return 1

    print("Database counts")
    for db_name, info in databases.items():
        print(f"{db_name}\t{info['doc_count']}")

    print("\nChiller asset counts")
    for asset_id, count in sorted(asset_counts.items()):
        print(f"{asset_id}\t{count}")

    total_docs = sum(asset_counts.values())
    print(f"\nChiller business docs\t{total_docs}")
    print(f"Chiller reported doc_count\t{databases[IOT_DBNAME]['doc_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
