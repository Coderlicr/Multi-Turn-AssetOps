"""Failure Reasoning Specialist — maps anomaly patterns to failure modes and root causes."""

from __future__ import annotations

from agent.supervisor_specialist.agents.base import SpecialistAgent


class FailureReasoningSpecialist(SpecialistAgent):
    role = "failure_reasoning_specialist"
    role_prefix = "fr"
    allowed_artifact_types = ("reasoning_result",)
    allowed_tools = {
        "fmsr.get_failure_modes",
        "fmsr.get_failure_mode_sensor_mapping",
        "utilities.csv_stats",
        "utilities.json_reader",
    }
