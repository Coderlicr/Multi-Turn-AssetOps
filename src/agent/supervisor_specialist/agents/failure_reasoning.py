"""Failure Reasoning Specialist — maps anomaly patterns to failure modes and root causes."""

from __future__ import annotations

from agent.supervisor_specialist.agents.base import SpecialistAgent


class FailureReasoningSpecialist(SpecialistAgent):
    role = "failure_reasoning_specialist"
    role_prefix = "fr"
    allowed_artifact_types = ("reasoning_result",)
    _extra_react_rules = (
        "- When mapping failure modes to sensors and no exact sensor list is available "
        "from input artifacts, call iot.sensors for the asset before "
        "fmsr.get_failure_mode_sensor_mapping"
    )
    _extra_artifact_rules = (
        "- For every reasoning_result payload, include these REQUIRED top-level fields: "
        "operation (root_cause_analysis or failure_mode_comparison), "
        "task_completed (boolean), primary_hypothesis or root_cause, "
        "competing_hypotheses, confidence, evidence, and remaining_uncertainty\n"
        "- Do not put operation, task_completed, primary_hypothesis/root_cause, confidence, "
        "or evidence only under an asset-named nested object; the supervisor reads these "
        "fields from the payload top level\n"
        "- If the summary states a primary hypothesis or root cause, the payload must also "
        "include the same conclusion in primary_hypothesis or root_cause and set "
        "task_completed=true unless the diagnosis is explicitly unresolved\n"
        "- When comparing possible faults, competing_hypotheses must list each candidate "
        "with its confidence and supporting/contradicting evidence\n"
        "- The summary must state the conclusion directly, not only repeat anomaly counts "
        "or list tools used"
    )
    capability_summary = (
        "Relate sensors and failure modes using the FMSR knowledge base: list failure modes for "
        "an asset, map failure modes to sensors, and form root-cause hypotheses over evidence "
        "supplied in input artifacts"
    )
    cannot_do = (
        "run any time-series model or compute anomalies (no tsfm tools)",
        "retrieve sensor history (no iot.history/iot.history_csv) - pass it a dataset_ref artifact",
        "statistically validate causality; its mapping is knowledge-based, not inferred from data",
        "create or rank work orders (no wo tools)",
    )
    allowed_tools = {
        "iot.sensors",
        "fmsr.get_failure_modes",
        "fmsr.get_failure_mode_sensor_mapping",
        "utilities.csv_stats",
        "utilities.json_reader",
    }
