"""Initialize the CouchDB IoT asset database from a JSON sensor data file.

Usage:
    python -m couchdb.init_asset_data [--data-file <path>] [--db <name>] [--drop]
                                     [--asset-id <id> ...]

Environment variables (or .env):
    COUCHDB_URL        e.g. http://localhost:5984
    COUCHDB_USERNAME   admin user
    COUCHDB_PASSWORD   admin password
    IOT_DBNAME         target database (default: chiller)
    ASSET_DATA_FILE    override JSON file path
"""

import argparse
import logging
import os
import sys
from decimal import Decimal
from typing import Iterable, Iterator, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(__file__)
_DEFAULT_DATA_FILE = os.path.join(
    _SCRIPT_DIR, "sample_data", "iot", "chiller6_june2020_sensordata_couchdb.json"
)

COUCHDB_URL = os.environ.get("COUCHDB_URL", "http://localhost:5984")
COUCHDB_USERNAME = os.environ.get("COUCHDB_USERNAME", "admin")
COUCHDB_PASSWORD = os.environ.get("COUCHDB_PASSWORD", "password")
IOT_DBNAME = os.environ.get("IOT_DBNAME", "chiller")
ASSET_DATA_FILE = os.environ.get("ASSET_DATA_FILE", _DEFAULT_DATA_FILE)

_AUTH = (COUCHDB_USERNAME, COUCHDB_PASSWORD)

# Mango index for typical IoT queries
_INDEXES = [
    ["asset_id", "timestamp"],
]

try:
    import ijson
except ImportError:  # pragma: no cover - optional dependency for large JSON files
    ijson = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url(db: str, *parts: str) -> str:
    return "/".join([COUCHDB_URL.rstrip("/"), db] + list(parts))


def _ensure_db(db_name: str, drop: bool) -> None:
    url = _db_url(db_name)
    resp = requests.head(url, auth=_AUTH, timeout=10)
    if resp.status_code == 200:
        if drop:
            logger.info("Dropping existing database '%s'…", db_name)
            requests.delete(url, auth=_AUTH, timeout=10).raise_for_status()
        else:
            logger.info("Database '%s' already exists — appending data.", db_name)
            return
    logger.info("Creating database '%s'…", db_name)
    requests.put(url, auth=_AUTH, timeout=10).raise_for_status()


def _create_indexes(db_name: str) -> None:
    url = _db_url(db_name, "_index")
    for fields in _INDEXES:
        payload = {"index": {"fields": fields}, "type": "json"}
        resp = requests.post(url, json=payload, auth=_AUTH, timeout=10)
        resp.raise_for_status()
        logger.info("Index on %s: %s", fields, resp.json().get("result", "?"))


def _prepare_doc(doc: dict) -> dict:
    """Remove replication metadata that causes conflicts on fresh inserts."""
    cleaned = dict(doc)
    cleaned.pop("_rev", None)
    return _normalise_json_value(cleaned)


def _normalise_json_value(value):
    """Convert parser-specific scalar types into plain JSON-serialisable values."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _normalise_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise_json_value(v) for v in value]
    return value


def _bulk_insert(db_name: str, docs: Iterable[dict], batch_size: int = 500) -> int:
    url = _db_url(db_name, "_bulk_docs")
    batch: list[dict] = []
    inserted = 0
    batch_num = 0
    for doc in docs:
        batch.append(_prepare_doc(doc))
        if len(batch) < batch_size:
            continue
        batch_num += 1
        resp = requests.post(url, json={"docs": batch}, auth=_AUTH, timeout=60)
        resp.raise_for_status()
        errors = [r for r in resp.json() if r.get("error")]
        if errors:
            logger.warning("%d bulk-insert errors in batch %d", len(errors), batch_num)
        inserted += len(batch)
        logger.info("Inserted batch %d (%d docs, %d total)", batch_num, len(batch), inserted)
        batch = []
    if batch:
        batch_num += 1
        resp = requests.post(url, json={"docs": batch}, auth=_AUTH, timeout=60)
        resp.raise_for_status()
        errors = [r for r in resp.json() if r.get("error")]
        if errors:
            logger.warning("%d bulk-insert errors in batch %d", len(errors), batch_num)
        inserted += len(batch)
        logger.info("Inserted batch %d (%d docs, %d total)", batch_num, len(batch), inserted)
    return inserted


def _load_docs_with_json(data_file: str) -> list[dict]:
    import json

    with open(data_file) as f:
        payload = json.load(f)

    if isinstance(payload, list):
        docs = payload
    elif isinstance(payload, dict) and isinstance(payload.get("docs"), list):
        docs = payload["docs"]
    else:
        logger.error("Expected a JSON array or an object containing a 'docs' array in %s", data_file)
        sys.exit(1)

    if not docs:
        logger.error("Expected a non-empty JSON document list in %s", data_file)
        sys.exit(1)
    return docs


def _iter_docs_streaming(data_file: str) -> Iterator[dict]:
    if ijson is None:
        docs = _load_docs_with_json(data_file)
        yield from docs
        return

    with open(data_file, "rb") as f:
        first_non_ws = b""
        while True:
            char = f.read(1)
            if not char:
                break
            if not char.isspace():
                first_non_ws = char
                break
        if not first_non_ws:
            logger.error("Data file is empty: %s", data_file)
            sys.exit(1)
        f.seek(0)
        if first_non_ws == b"[":
            yield from ijson.items(f, "item")
            return
        if first_non_ws == b"{":
            yield from ijson.items(f, "docs.item")
            return
        logger.error("Unsupported JSON structure in %s", data_file)
        sys.exit(1)


def _filter_docs(docs: Iterable[dict], asset_ids: Optional[set[str]]) -> Iterator[dict]:
    if not asset_ids:
        yield from docs
        return

    for doc in docs:
        asset_id = doc.get("asset_id")
        if asset_id in asset_ids:
            yield doc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize CouchDB IoT asset database from JSON.")
    parser.add_argument("--data-file", default=ASSET_DATA_FILE, help="Path to sensor data JSON file")
    parser.add_argument("--db", default=IOT_DBNAME, help="CouchDB database name")
    parser.add_argument("--drop", action="store_true", help="Drop and recreate database if it exists")
    parser.add_argument(
        "--asset-id",
        action="append",
        dest="asset_ids",
        help="Only import documents for this asset_id. Repeat to include multiple assets.",
    )
    args = parser.parse_args()
    selected_asset_ids = set(args.asset_ids or [])

    logger.info("CouchDB URL: %s", COUCHDB_URL)
    logger.info("Database: %s", args.db)
    logger.info("Data file: %s", args.data_file)
    if selected_asset_ids:
        logger.info("Filtering to asset_ids: %s", ", ".join(sorted(selected_asset_ids)))

    if not os.path.exists(args.data_file):
        logger.error("Data file not found: %s", args.data_file)
        sys.exit(1)

    if ijson is None:
        logger.info("Optional dependency 'ijson' not installed; falling back to in-memory JSON load.")
    else:
        logger.info("Using streaming JSON parser for import.")

    _ensure_db(args.db, drop=args.drop)
    filtered_docs = _filter_docs(_iter_docs_streaming(args.data_file), selected_asset_ids)
    inserted = _bulk_insert(args.db, filtered_docs)
    if inserted == 0:
        logger.error("No documents were inserted from %s", args.data_file)
        sys.exit(1)
    logger.info("Inserted %d total documents from '%s'", inserted, args.data_file)
    _create_indexes(args.db)
    logger.info("Done. Database '%s' is ready.", args.db)


if __name__ == "__main__":
    main()
