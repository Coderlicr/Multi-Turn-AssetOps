"""Maintenance Planning Specialist — converts diagnosis into actionable maintenance plans."""

from __future__ import annotations

from agent.supervisor_specialist.agents.base import SpecialistAgent


class MaintenancePlanningSpecialist(SpecialistAgent):
    role = "maintenance_planning_specialist"
    role_prefix = "mp"
    allowed_artifact_types = ("planning_result", "draft_action")
    _extra_artifact_rules = (
        "- For planning_result artifacts about failure rate, MTBI, corrective work-order "
        "frequency, or acceleration, include top-level fields: operation, task_completed, "
        "failure_rate_trend, is_accelerating (boolean or unresolved), evidence, "
        "counts_by_period when available, and remaining_uncertainty\n"
        "- The summary must directly answer whether the failure rate is accelerating, "
        "not only report work-order counts or distribution\n"
        "- For planning_result or draft_action artifacts about recovery procedure, "
        "restart procedure, post-trip recovery, or operating-normal verification, include "
        "top-level fields: operation, task_completed, recommended_actions, safety_checks, "
        "restart_or_verification_steps, monitoring_plan, evidence, and remaining_uncertainty\n"
        "- The summary must directly state the recommended recovery or verification plan, "
        "not only report events, alerts, work orders, or sensor statistics"
    )
    capability_summary = (
        "Work-order domain: retrieve work orders/events/alert rules, compute work-order "
        "distribution, predict the next work order, analyse alert-to-failure probability, and "
        "recommend actions grounded in those retrieved records"
    )
    cannot_do = (
        "run any time-series model or compute anomalies (no tsfm tools) - pass anomaly findings "
        "in as input artifacts instead of asking it to analyse sensor data",
        "retrieve sensor inventory or history (no iot tools)",
        "diagnose failure modes from sensor patterns (no fmsr tools)",
    )
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
