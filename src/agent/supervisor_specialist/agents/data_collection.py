"""Data Collection Specialist — gathers IoT data, work orders, and events."""

from __future__ import annotations

from agent.supervisor_specialist.agents.base import SpecialistAgent


class DataCollectionSpecialist(SpecialistAgent):
    role = "data_collection_specialist"
    role_prefix = "dc"
    allowed_artifact_types = ("dataset_ref", "inventory")
    _extra_react_rules = (
        "- If iot.assets returns multiple assets and the goal does not name a specific asset, "
        "collect data for ALL returned assets before marking done — do not stop after the first one\n"
        "- After calling iot.history_csv for an asset, always call utilities.csv_stats on the "
        "returned csv_path to obtain column statistics before moving to the next asset"
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
        "utilities.json_reader",
        "utilities.current_date_time",
        "utilities.current_time_english",
    }
