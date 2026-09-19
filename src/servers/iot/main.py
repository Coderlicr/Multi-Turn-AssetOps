import csv
import json
import os
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Union
from mcp.server.fastmcp import FastMCP

from servers.paths import datasets_dir
from pydantic import BaseModel, Field

_DatetimeParam = Annotated[str, Field(description="ISO 8601 datetime string, e.g. '2020-06-01T00:00:00'.")]
_DatetimeOpt = Annotated[Optional[str], Field(description="ISO 8601 datetime string, e.g. '2020-06-20T00:00:00'. Omit to query up to the latest data.")]
_SiteName = Annotated[str, Field(description="Site name. The only available site is 'MAIN'.")]
_AssetId = Annotated[str, Field(description="Asset name, e.g. 'Chiller 3', 'Chiller 4', 'Chiller 6', or 'Chiller 9'.")]
import couchdb3
from dotenv import load_dotenv


def _write_couchdb_metric(query: str, latency_s: float, status: str, docs: int = 0) -> None:
    """Append one CouchDB query record to COUCHDB_METRICS_FILE if set."""
    path = os.environ.get("COUCHDB_METRICS_FILE")
    if not path:
        return
    try:
        record = {"server": "iot", "query": query,
                  "latency_s": round(latency_s, 4), "status": status, "docs_returned": docs}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass

load_dotenv()

# Setup logging — default WARNING so stderr stays quiet when used as MCP server;
# set LOG_LEVEL=INFO (or DEBUG) in the environment to see verbose output.
_log_level = getattr(
    logging, os.environ.get("LOG_LEVEL", "WARNING").upper(), logging.WARNING
)
logging.basicConfig(level=_log_level)
logger = logging.getLogger("iot-mcp-server")

# Configuration from environment
COUCHDB_URL = os.environ.get("COUCHDB_URL")
COUCHDB_DBNAME = os.environ.get("IOT_DBNAME")
COUCHDB_USERNAME = os.environ.get("COUCHDB_USERNAME")
COUCHDB_PASSWORD = os.environ.get("COUCHDB_PASSWORD")

# Initialize CouchDB
try:
    db = couchdb3.Database(
        COUCHDB_DBNAME,
        url=COUCHDB_URL,
        user=COUCHDB_USERNAME,
        password=COUCHDB_PASSWORD,
    )
    logger.info(f"Connected to CouchDB: {COUCHDB_DBNAME}")
except Exception as e:
    logger.error(f"Failed to connect to CouchDB: {e}")
    db = None

mcp = FastMCP("iot")

# Static site as per original requirement
SITES = ["MAIN"]


class ErrorResult(BaseModel):
    error: str


class SitesResult(BaseModel):
    sites: List[str]


class AssetsResult(BaseModel):
    site_name: str
    total_assets: int
    assets: List[str]
    message: str


class SensorsResult(BaseModel):
    site_name: str
    asset_id: str
    total_sensors: int
    sensors: List[str]
    message: str


class HistoryResult(BaseModel):
    site_name: str
    asset_id: str
    total_observations: int
    start: str
    final: Optional[str]
    observations: List[Dict[str, Any]]
    message: str


class HistoryCsvResult(BaseModel):
    site_name: str
    asset_id: str
    total_observations: int
    start: str
    final: Optional[str]
    columns: List[str]
    csv_path: str
    message: str


def get_asset_list() -> List[str]:
    """Helper to fetch unique asset IDs from CouchDB."""
    if not db:
        return []

    # Using a mango query to find unique asset_ids might be slow without an index,
    # but for this benchmark we'll query documents and unique them.
    # In a production environment, we'd use a CouchDB view.
    try:
        # We limit the fields to just asset_id to minimize data transfer
        t0 = time.monotonic()
        res = db.find(
            {"asset_id": {"$exists": True}}, fields=["asset_id"], limit=100000
        )
        docs = res["docs"]
        _write_couchdb_metric("get_asset_list", time.monotonic() - t0, "ok", len(docs))
        assets = {doc["asset_id"] for doc in docs if "asset_id" in doc}
        return sorted(list(assets))
    except Exception as e:
        _write_couchdb_metric("get_asset_list", 0, "error")
        logger.error(f"Error fetching assets: {e}")
        return []


def get_sensor_list(asset_id: str) -> List[str]:
    """Helper to fetch sensor names for a given asset from CouchDB."""
    if not db:
        return []

    try:
        # Get one document for the asset to inspect keys
        t0 = time.monotonic()
        res = db.find({"asset_id": asset_id}, limit=1)
        _write_couchdb_metric("get_sensor_list", time.monotonic() - t0, "ok", len(res["docs"]))
        if not res["docs"]:
            return []

        doc = res["docs"][0]
        # Exclude metadata and standard fields
        exclude = {"_id", "_rev", "asset_id", "timestamp"}
        sensors = [key for key in doc.keys() if key not in exclude]
        return sorted(sensors)
    except Exception as e:
        logger.error(f"Error fetching sensors for {asset_id}: {e}")
        return []


@mcp.tool()
def sites() -> SitesResult:
    """Retrieves a list of sites. Each site is represented by a name."""
    return SitesResult(sites=SITES)


@mcp.tool()
def assets(site_name: _SiteName) -> Union[AssetsResult, ErrorResult]:
    """Returns a list of assets for a given site. Each asset includes an id and a name."""
    if site_name not in SITES:
        return ErrorResult(error=f"unknown site {site_name}")

    asset_list = get_asset_list()
    return AssetsResult(
        site_name=site_name,
        total_assets=len(asset_list),
        assets=asset_list,
        message=f"found {len(asset_list)} asset ids for site_name {site_name}: {', '.join(asset_list)}.",
    )


@mcp.tool()
def sensors(site_name: _SiteName, asset_id: _AssetId) -> Union[SensorsResult, ErrorResult]:
    """Lists the sensors available for a specified asset at a given site."""
    if site_name not in SITES:
        return ErrorResult(error=f"unknown site {site_name}")

    sensor_list = get_sensor_list(asset_id)
    if not sensor_list:
        return ErrorResult(error=f"unknown asset_id {asset_id} or no sensors found")

    return SensorsResult(
        site_name=site_name,
        asset_id=asset_id,
        total_sensors=len(sensor_list),
        sensors=sensor_list,
        message=f"found {len(sensor_list)} sensors for asset_id {asset_id} and site_name {site_name}: {', '.join(sensor_list)}.",
    )


@mcp.tool()
def history(
    site_name: _SiteName, asset_id: _AssetId, start: _DatetimeParam, final: _DatetimeOpt = None
) -> Union[HistoryResult, ErrorResult]:
    """Returns a list of historical sensor values for the specified asset(s) at a site within a given time range (start to final)."""
    try:
        start_iso = datetime.fromisoformat(start).isoformat()
        if final:
            datetime.fromisoformat(final)
            if start >= final:
                return ErrorResult(error="start >= final")
    except ValueError as e:
        return ErrorResult(error=f"Invalid date format: {e}")

    if not db:
        return ErrorResult(error="CouchDB not connected")

    selector = {
        "asset_id": asset_id,
        "timestamp": {"$gte": start_iso},
    }
    if final:
        selector["timestamp"]["$lt"] = datetime.fromisoformat(final).isoformat()

    logger.info(f"Querying CouchDB with selector: {selector}")
    try:
        t0 = time.monotonic()
        res = db.find(
            selector, limit=1000, sort=[{"asset_id": "asc"}, {"timestamp": "asc"}]
        )
        docs = res["docs"]
        _write_couchdb_metric("history", time.monotonic() - t0, "ok", len(docs))
        return HistoryResult(
            site_name=site_name,
            asset_id=asset_id,
            total_observations=len(docs),
            start=start,
            final=final,
            observations=docs,
            message=f"found {len(docs)} observations for asset_id {asset_id} from {start} to {final or 'now'}.",
        )
    except Exception as e:
        _write_couchdb_metric("history", 0, "error")
        logger.error(f"CouchDB query failed: {e}")
        return ErrorResult(error=str(e))


@mcp.tool()
def history_csv(
    site_name: _SiteName,
    asset_id: _AssetId,
    start: _DatetimeParam,
    final: _DatetimeOpt = None,
) -> Union[HistoryCsvResult, ErrorResult]:
    """Returns historical sensor data for an asset as a CSV file path.

    Identical to `history` but writes the observations to a temporary CSV file
    and returns the file path instead of raw JSON.  Use this tool when the next
    step requires a CSV dataset (e.g. TSFM anomaly detection or forecasting).

    The CSV has columns: timestamp, asset_id, <sensor1>, <sensor2>, ...
    """
    try:
        start_iso = datetime.fromisoformat(start).isoformat()
        if final:
            datetime.fromisoformat(final)
            if start >= final:
                return ErrorResult(error="start >= final")
    except ValueError as e:
        return ErrorResult(error=f"Invalid date format: {e}")

    if not db:
        return ErrorResult(error="CouchDB not connected")

    selector = {
        "asset_id": asset_id,
        "timestamp": {"$gte": start_iso},
    }
    if final:
        selector["timestamp"]["$lt"] = datetime.fromisoformat(final).isoformat()

    try:
        t0 = time.monotonic()
        res = db.find(
            selector, limit=5000, sort=[{"asset_id": "asc"}, {"timestamp": "asc"}]
        )
        docs = res["docs"]
        _write_couchdb_metric("history_csv", time.monotonic() - t0, "ok", len(docs))
    except Exception as e:
        _write_couchdb_metric("history_csv", 0, "error")
        logger.error(f"CouchDB query failed: {e}")
        return ErrorResult(error=str(e))

    if not docs:
        return ErrorResult(
            error=f"No observations found for {asset_id} from {start} to {final or 'now'}."
        )

    # Determine column order: timestamp first, then asset_id, then sensors sorted
    exclude = {"_id", "_rev"}
    meta_cols = ["timestamp", "asset_id"]
    sensor_cols = sorted(
        k for k in docs[0].keys() if k not in exclude and k not in meta_cols
    )
    columns = meta_cols + sensor_cols

    # Write to a named temp file that persists after close (delete_on_close=False)
    safe_asset = asset_id.replace(" ", "_").replace("/", "-")
    safe_start = start.replace(":", "").replace("-", "")
    safe_final = (final or "now").replace(":", "").replace("-", "")
    csv_path = datasets_dir() / f"{safe_asset}_{safe_start}_{safe_final}_history.csv"

    try:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=columns, extrasaction="ignore", restval=""
            )
            writer.writeheader()
            writer.writerows(docs)
    except OSError as e:
        return ErrorResult(error=f"Failed to write CSV: {e}")

    return HistoryCsvResult(
        site_name=site_name,
        asset_id=asset_id,
        total_observations=len(docs),
        start=start,
        final=final,
        columns=columns,
        csv_path=str(csv_path),
        message=(
            f"Wrote {len(docs)} observations for {asset_id} "
            f"({start} to {final or 'now'}) to {csv_path}. "
            f"Sensor columns: {', '.join(sensor_cols)}."
        ),
    )


def main():
    # Initialize and run the server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
