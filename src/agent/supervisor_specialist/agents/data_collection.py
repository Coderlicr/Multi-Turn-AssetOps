"""Data Collection Specialist — gathers IoT data, work orders, and events."""

from __future__ import annotations

import json

from agent.supervisor_specialist.agents.base import SpecialistAgent


class DataCollectionSpecialist(SpecialistAgent):
    role = "data_collection_specialist"
    role_prefix = "dc"
    allowed_artifact_types = ("dataset_ref", "inventory")
    _extra_react_rules = (
        "- If iot.assets returns multiple assets and the goal does not name a specific asset, "
        "collect data for ALL returned assets before marking done — do not stop after the first one\n"
        "- After calling iot.history_csv for an asset, always call utilities.csv_stats on the "
        "returned csv_path to obtain column statistics before moving to the next asset\n"
        "- For real-time incident or trip reports, first call iot.sensors for the asset, "
        "then retrieve recent iot.history or iot.history_csv for the requested/recent window; "
        "note any failed or unavailable sensor retrievals so downstream analysis can use "
        "the remaining available signals"
    )
    capability_summary = (
        "Retrieve raw facts: site/asset/sensor inventory, sensor history (incl. CSV export), "
        "work orders, events, alert rules, and descriptive statistics over a CSV"
    )
    cannot_do = (
        "run any time-series model (no tsfm tools): no anomaly detection, forecasting or fine-tuning",
        "map anomalies to failure modes or produce root-cause hypotheses (no fmsr tools)",
        "rank, recommend or schedule maintenance actions",
    )
    allowed_tools = {
        "iot.sites",
        "iot.assets",
        "iot.sensors",
        "iot.history",
        "iot.history_csv",
        "wo.get_work_orders",
        "wo.get_preventive_work_orders",
        "wo.get_corrective_work_orders",
        "wo.get_events",
        "wo.get_failure_codes",
        "wo.get_alert_rules",
        "utilities.csv_stats",
        "utilities.csv_query",
        "utilities.json_reader",
        "utilities.current_date_time",
        "utilities.current_time_english",
    }

    def _postprocess_artifacts(self, task, artifacts, results) -> None:
        del task
        csv_paths: list[str] = []
        for result in results:
            if result.status != "ok":
                continue
            parsed = self._parse_tool_result(result.result)
            if not isinstance(parsed, dict):
                continue
            csv_path = parsed.get("csv_path")
            if isinstance(csv_path, str) and csv_path not in csv_paths:
                csv_paths.append(csv_path)

        if not csv_paths:
            return

        for artifact in artifacts:
            if artifact.artifact_type != "dataset_ref":
                continue
            artifact.payload.setdefault("csv_path", csv_paths[0])
            if len(csv_paths) > 1:
                artifact.payload.setdefault("csv_paths", csv_paths)

    @staticmethod
    def _parse_tool_result(value):
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
