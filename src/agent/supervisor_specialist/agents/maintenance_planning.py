"""Maintenance Planning Specialist — converts diagnosis into actionable maintenance plans."""

from __future__ import annotations

from agent.supervisor_specialist.agents.base import SpecialistAgent


class MaintenancePlanningSpecialist(SpecialistAgent):
    role = "maintenance_planning_specialist"
    role_prefix = "mp"
    allowed_artifact_types = ("planning_result", "draft_action")
    allowed_tools = {
        "wo.get_work_orders",
        "wo.get_preventive_work_orders",
        "wo.get_corrective_work_orders",
        "wo.get_events",
        "wo.get_work_order_distribution",
        "wo.predict_next_work_order",
        "wo.get_alert_rules",
        "wo.analyze_alert_to_failure",
    }
