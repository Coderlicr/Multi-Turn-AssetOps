"""FMSR (Failure Mode and Sensor Reasoning) MCP Server.

Exposes two tools:
  get_failure_modes               – lists failure modes for an asset
  get_failure_mode_sensor_mapping – returns bidirectional FM↔sensor relevancy mapping

For chillers and AHUs get_failure_modes returns a curated hardcoded list.
For any other asset type the LLM is queried as a fallback.

The mapping tool uses a two-tier lookup:
  1. Offline cache (sensor_mappings.yaml) — instant, no LLM call
  2. LLM per-pair fallback for any cache miss — results written back to cache

LLM backend is configured via the FMSR_MODEL_ID environment variable
(default: ``watsonx/meta-llama/llama-3-3-70b-instruct``).  Any model string
supported by litellm works — the provider is encoded in the prefix.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated, Dict, List, Union

import yaml
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

load_dotenv()

_AssetName = Annotated[str, Field(description="Asset name, e.g. 'Chiller 3'. For chillers and AHUs returns a curated list; for other asset types queries the LLM.")]
_FailureModes = Annotated[List[str], Field(description="List of failure mode names from get_failure_modes. Keep ≤5 to avoid long runtimes.")]
_SensorsList = Annotated[List[str], Field(description="List of sensor column names from the sensors() tool. Keep ≤10 to avoid long runtimes.")]

_log_level = getattr(logging, os.environ.get("LOG_LEVEL", "WARNING").upper(), logging.WARNING)
logging.basicConfig(level=_log_level)
logger = logging.getLogger("fmsr-mcp-server")


# ── Hardcoded asset data ──────────────────────────────────────────────────────

_FAILURE_MODES_FILE = Path(__file__).parent / "failure_modes.yaml"
with _FAILURE_MODES_FILE.open() as _f:
    _ASSET_FAILURE_MODES: dict[str, list[str]] = yaml.safe_load(_f)

_SENSOR_MAPPINGS_FILE = Path(__file__).parent / "sensor_mappings.yaml"
_cache_lock = threading.Lock()


def _load_cache() -> dict:
    try:
        with _SENSOR_MAPPINGS_FILE.open() as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load sensor_mappings.yaml: %s", exc)
        return {}


_SENSOR_MAPPING_CACHE: dict = _load_cache()


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _asset_type(asset_name: str) -> str:
    """Normalize asset name to asset type key, e.g. 'Chiller 6' → 'chiller'."""
    return re.sub(r"\d+", "", asset_name).strip().lower()


def _normalize_sensor(asset_name: str, sensor: str) -> str:
    """Strip asset name prefix from sensor for cache lookup.
    e.g. ('Chiller 6', 'Chiller 6 Supply Temperature') → 'Supply Temperature'
    """
    prefix = asset_name.strip() + " "
    return sensor[len(prefix):] if sensor.startswith(prefix) else sensor


def _cache_get(asset_type: str, failure_mode: str, sensor_key: str) -> dict | None:
    return (
        _SENSOR_MAPPING_CACHE
        .get(asset_type, {})
        .get(failure_mode, {})
        .get(sensor_key)
    )


def _cache_set(asset_type: str, failure_mode: str, sensor_key: str, result: dict) -> None:
    """Write one result to in-memory cache and persist to YAML (thread-safe)."""
    with _cache_lock:
        _SENSOR_MAPPING_CACHE \
            .setdefault(asset_type, {}) \
            .setdefault(failure_mode, {})[sensor_key] = result
        try:
            with _SENSOR_MAPPINGS_FILE.open("w") as f:
                yaml.dump(_SENSOR_MAPPING_CACHE, f, allow_unicode=True, default_flow_style=False)
        except Exception as exc:
            logger.warning("Failed to persist sensor_mappings.yaml: %s", exc)


# ── Prompt templates ──────────────────────────────────────────────────────────

_ASSET2FM_PROMPT = (
    "What are different failure modes for asset {asset_name}?\n"
    "Your response should be a numbered list with each failure mode on a new line. "
    "Please only list the failure mode name.\n"
    "For example: \n\n1. foo\n\n2. bar\n\n3. baz"
)

_RELEVANCY_PROMPT = (
    "For the asset {asset_name}, if the failure {failure_mode} occurs, "
    "can sensor {sensor} help monitor or detect the failure for {asset_name}?\n"
    "Provide the answer in the first line and reason in the second line. "
    "If the answer is Yes, provide the temporal behaviour of the sensor "
    "when the failure occurs in the third line."
)


# ── Output parsers ────────────────────────────────────────────────────────────

def _parse_numbered_list(text: str) -> list[str]:
    """Parse a numbered list response into a plain list of strings."""
    items = []
    for line in text.splitlines():
        m = re.match(r"^\d+[\.\)]\s*(.+)", line.strip())
        if m:
            items.append(m.group(1).strip())
    return items


def _parse_relevancy(text: str) -> dict:
    """Parse a 3-line relevancy response into {answer, reason, temporal_behavior}."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith("yes"):
        answer = "Yes"
    elif lines and lines[0].lower().startswith("no"):
        answer = "No"
    else:
        answer = "Unknown"
    reason = lines[1] if len(lines) >= 2 else "Unknown"
    temporal = lines[2] if (answer == "Yes" and len(lines) >= 3) else "Unknown"
    return {"answer": answer, "reason": reason, "temporal_behavior": temporal}


# ── LLM backend (lazy init; graceful degradation if creds are absent) ─────────

_DEFAULT_MODEL_ID = "watsonx/meta-llama/llama-3-3-70b-instruct"
_MAX_RETRIES = 3


def _build_llm():
    from llm import LiteLLMBackend

m    model_id = os.environ.get("DEFAULT_MODEL_ID", _DEFAULT_MODEL_ID)
    if model_id.startswith("watsonx/"):
        missing = [v for v in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID") if not os.environ.get(v)]
        if missing:
            raise RuntimeError(f"Missing env vars for WatsonX: {missing}")
    else:
        missing = [v for v in ("LITELLM_API_KEY", "LITELLM_BASE_URL") if not os.environ.get(v)]
        if missing:
            raise RuntimeError(f"Missing env vars for LiteLLM: {missing}")
    return LiteLLMBackend(model_id)


try:
    _llm = _build_llm()
    _llm_available = True
except Exception as _e:
    logger.warning("LLM unavailable (FMSR will use curated data only): %s", _e)
    _llm = None
    _llm_available = False


# ── LLM call helpers with retry ───────────────────────────────────────────────

def _call_asset2fm(asset_name: str) -> list[str]:
    """Query the LLM for failure modes of an asset. Retries up to _MAX_RETRIES times."""
    prompt = _ASSET2FM_PROMPT.format(asset_name=asset_name)
    last_exc: Exception | None = None
    for _ in range(_MAX_RETRIES):
        try:
            return _parse_numbered_list(_llm.generate(prompt))
        except Exception as exc:
            last_exc = exc
    raise last_exc


def _call_relevancy(asset_name: str, failure_mode: str, sensor: str) -> dict:
    """Query the LLM for FM↔sensor relevancy. Retries up to _MAX_RETRIES times."""
    prompt = _RELEVANCY_PROMPT.format(
        asset_name=asset_name, failure_mode=failure_mode, sensor=sensor
    )
    last_exc: Exception | None = None
    for _ in range(_MAX_RETRIES):
        try:
            return _parse_relevancy(_llm.generate(prompt))
        except Exception as exc:
            last_exc = exc
    raise last_exc


# ── Result models ─────────────────────────────────────────────────────────────

class ErrorResult(BaseModel):
    error: str


class FailureModesResult(BaseModel):
    asset_name: str
    failure_modes: List[str]


class RelevancyEntry(BaseModel):
    asset_name: str
    failure_mode: str
    sensor: str
    relevancy_answer: str
    relevancy_reason: str
    temporal_behavior: str


class MappingMetadata(BaseModel):
    asset_name: str
    failure_modes: List[str]
    sensors: List[str]


class FailureModeSensorMappingResult(BaseModel):
    metadata: MappingMetadata
    fm2sensor: Dict[str, List[str]]
    sensor2fm: Dict[str, List[str]]
    full_relevancy: List[RelevancyEntry]


# ── FastMCP server ────────────────────────────────────────────────────────────

mcp = FastMCP("fmsr")


@mcp.tool()
def get_failure_modes(
    asset_name: _AssetName,
) -> Union[FailureModesResult, ErrorResult]:
    """Returns a list of known failure modes for the given asset.
    For chillers and AHUs returns a curated list. For other assets queries the LLM."""
    asset_key = _asset_type(asset_name)
    if not asset_key or asset_key == "none":
        return ErrorResult(error="asset_name is required")

    if asset_key in _ASSET_FAILURE_MODES:
        return FailureModesResult(
            asset_name=asset_name,
            failure_modes=_ASSET_FAILURE_MODES[asset_key],
        )

    if not _llm_available:
        return ErrorResult(error="LLM unavailable and asset not in local database")

    try:
        result = _call_asset2fm(asset_name)
        return FailureModesResult(asset_name=asset_name, failure_modes=result)
    except Exception as exc:
        logger.error("_call_asset2fm failed: %s", exc)
        return ErrorResult(error=str(exc))


@mcp.tool()
def get_failure_mode_sensor_mapping(
    asset_name: _AssetName,
    failure_modes: _FailureModes,
    sensors: _SensorsList,
) -> Union[FailureModeSensorMappingResult, ErrorResult]:
    """For each (failure_mode, sensor) pair determines whether the sensor can detect
    the failure. Returns a bidirectional mapping (fm→sensors, sensor→fms) plus
    the full per-pair relevancy details.

    Results are cached in sensor_mappings.yaml — cache hits are instant.
    Cache misses fall back to parallel LLM calls and are written back to cache.
    Keep both lists small (e.g. ≤5 failure modes, ≤10 sensors) for best results."""
    if not asset_name:
        return ErrorResult(error="asset_name is required")
    if not failure_modes:
        return ErrorResult(error="failure_modes list is required")
    if not sensors:
        return ErrorResult(error="sensors list is required")

    atype = _asset_type(asset_name)
    pairs = [(fm, s) for fm in failure_modes for s in sensors]

    full_relevancy: List[RelevancyEntry] = []
    fm2sensor: Dict[str, List[str]] = {}
    sensor2fm: Dict[str, List[str]] = {}
    missing_pairs: list[tuple[str, str]] = []

    # ── Pass 1: serve from cache ──────────────────────────────────────────────
    for fm, s in pairs:
        sensor_key = _normalize_sensor(asset_name, s)
        cached = _cache_get(atype, fm, sensor_key)
        if cached:
            entry = RelevancyEntry(
                asset_name=asset_name,
                failure_mode=fm,
                sensor=s,
                relevancy_answer=cached["answer"],
                relevancy_reason=cached["reason"],
                temporal_behavior=cached["temporal_behavior"],
            )
            full_relevancy.append(entry)
            if "yes" in cached["answer"].lower():
                fm2sensor.setdefault(fm, []).append(s)
                sensor2fm.setdefault(s, []).append(fm)
        else:
            missing_pairs.append((fm, s))

    cache_hits = len(pairs) - len(missing_pairs)
    logger.info(
        "get_failure_mode_sensor_mapping: %d/%d pairs from cache, %d need LLM",
        cache_hits, len(pairs), len(missing_pairs),
    )

    # ── Pass 2: LLM for cache misses ─────────────────────────────────────────
    if missing_pairs:
        if not _llm_available:
            return ErrorResult(error="LLM unavailable and some pairs not in cache")

        try:
            with ThreadPoolExecutor(max_workers=min(len(missing_pairs), 8)) as pool:
                future_to_pair = {
                    pool.submit(_call_relevancy, asset_name, fm, s): (fm, s)
                    for fm, s in missing_pairs
                }
                for future in as_completed(future_to_pair):
                    fm, s = future_to_pair[future]
                    gen = future.result()
                    # Write to cache
                    sensor_key = _normalize_sensor(asset_name, s)
                    _cache_set(atype, fm, sensor_key, gen)
                    entry = RelevancyEntry(
                        asset_name=asset_name,
                        failure_mode=fm,
                        sensor=s,
                        relevancy_answer=gen["answer"],
                        relevancy_reason=gen["reason"],
                        temporal_behavior=gen["temporal_behavior"],
                    )
                    full_relevancy.append(entry)
                    if "yes" in gen["answer"].lower():
                        fm2sensor.setdefault(fm, []).append(s)
                        sensor2fm.setdefault(s, []).append(fm)
        except Exception as exc:
            logger.error("LLM relevancy call failed: %s", exc)
            return ErrorResult(error=str(exc))

    return FailureModeSensorMappingResult(
        metadata=MappingMetadata(
            asset_name=asset_name,
            failure_modes=failure_modes,
            sensors=sensors,
        ),
        fm2sensor=fm2sensor,
        sensor2fm=sensor2fm,
        full_relevancy=full_relevancy,
    )


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
