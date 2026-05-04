"""Offline pre-computation script for FM↔sensor relevancy cache.

Usage:
    python precompute_cache.py [--asset-type chiller] [--sensors "Supply Temperature,Return Temperature,..."]

Iterates over all (failure_mode, sensor) combinations for the given asset type,
calls the LLM for any cache miss, and writes results to sensor_mappings.yaml.

Run once to warm the cache; subsequent tool calls will be served instantly.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running as a standalone script from fmsr/ directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("precompute_cache")

# Default sensor list for chillers (generic names without asset prefix)
_DEFAULT_CHILLER_SENSORS = [
    "Supply Temperature",
    "Return Temperature",
    "Setpoint Temperature",
    "Condenser Water Flow",
    "Condenser Water Return To Tower Temperature",
    "Condenser Water Supply To Chiller Temperature",
    "Liquid Refrigerant Evaporator Temperature",
    "Power Input",
    "Chiller % Loaded",
    "Chiller Efficiency",
    "Tonnage",
]

_DEFAULT_AHU_SENSORS = [
    "Supply Air Temperature",
    "Return Air Temperature",
    "Supply Air Pressure",
    "Return Air Pressure",
    "Fan Speed",
    "Heating Coil Valve Position",
    "Cooling Coil Valve Position",
    "Outdoor Air Temperature",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-compute FMSR sensor mapping cache.")
    parser.add_argument(
        "--asset-type",
        default="chiller",
        help="Asset type to pre-compute (default: chiller)",
    )
    parser.add_argument(
        "--sensors",
        default=None,
        help="Comma-separated sensor names (without asset prefix). "
             "Defaults to built-in list for the asset type.",
    )
    args = parser.parse_args()

    # Import after path setup
    from servers.fmsr.main import (
        _ASSET_FAILURE_MODES,
        _asset_type,
        _cache_get,
        _cache_set,
        _call_relevancy,
        _llm_available,
    )

    asset_type = args.asset_type.lower()
    failure_modes = _ASSET_FAILURE_MODES.get(asset_type)
    if not failure_modes:
        logger.error("No failure modes found for asset type '%s'. Check failure_modes.yaml.", asset_type)
        sys.exit(1)

    if args.sensors:
        sensors = [s.strip() for s in args.sensors.split(",") if s.strip()]
    elif asset_type == "chiller":
        sensors = _DEFAULT_CHILLER_SENSORS
    elif asset_type == "ahu":
        sensors = _DEFAULT_AHU_SENSORS
    else:
        logger.error("No default sensors for asset type '%s'. Pass --sensors explicitly.", asset_type)
        sys.exit(1)

    if not _llm_available:
        logger.error("LLM is not available. Check environment variables.")
        sys.exit(1)

    pairs = [(fm, s) for fm in failure_modes for s in sensors]
    total = len(pairs)
    hits = sum(1 for fm, s in pairs if _cache_get(asset_type, fm, s) is not None)
    misses = total - hits

    logger.info(
        "Asset type: %s | Failure modes: %d | Sensors: %d | Total pairs: %d",
        asset_type, len(failure_modes), len(sensors), total,
    )
    logger.info("Cache hits: %d | Cache misses to compute: %d", hits, misses)

    if misses == 0:
        logger.info("Cache is already complete. Nothing to do.")
        return

    # Use a dummy asset name with the right prefix for _call_relevancy
    dummy_asset_name = asset_type.capitalize() + " 1"

    computed = 0
    failed = 0
    for fm, sensor_key in pairs:
        if _cache_get(asset_type, fm, sensor_key) is not None:
            continue  # already cached

        # _call_relevancy uses the full sensor name in the prompt, but for generic
        # pre-computation we pass sensor_key directly (no asset prefix needed)
        try:
            result = _call_relevancy(dummy_asset_name, fm, sensor_key)
            _cache_set(asset_type, fm, sensor_key, result)
            computed += 1
            logger.info(
                "[%d/%d] %s | %s → %s",
                computed + failed, misses, fm[:50], sensor_key, result["answer"],
            )
        except Exception as exc:
            failed += 1
            logger.warning("Failed: %s | %s → %s", fm[:50], sensor_key, exc)

    logger.info("Done. Computed: %d | Failed: %d | Cache file: sensor_mappings.yaml", computed, failed)


if __name__ == "__main__":
    main()
