"""Supervisor agent — sole decision center for the Supervisor-Specialist system."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from agent.supervisor_specialist._utils import (
    call_llm,
    extract_file_paths,
    format_artifacts_summary,
    format_conversation_memory,
    parse_json_from_llm,
)
from agent.supervisor_specialist.agents.base import format_specialist_catalog
from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.agents.failure_reasoning import FailureReasoningSpecialist
from agent.supervisor_specialist.agents.maintenance_planning import MaintenancePlanningSpecialist
from agent.supervisor_specialist.agents.time_series_analysis import TimeSeriesAnalysisSpecialist
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.schemas import (
    CaseState,
    GraphState,
    SupervisorDecision,
)

_log = logging.getLogger(__name__)

_SUPERVISOR_PROMPT = """\
You are the Supervisor agent for an industrial asset operations AI system.
You coordinate specialist agents to answer user questions about industrial assets (chillers).

Today (UTC): {today}

Latest user message:
{current_user_message}

Available specialists (TOOLS is the complete set each one can reach; never ask for
anything under CANNOT — that specialist has no tool for it and will come back empty):
{specialist_catalog}

Specialists that already reported they cannot do a task this turn:
{unmet_reports}

Current case state:
{case_state_json}

Structured conversation memory:
{conversation_memory}

Already collected artifacts:
{artifacts_summary}

Error from previous step (if any): {error_message}

Current step: {step_count} / {max_steps}

Your job: decide the next action. Options:
1. Call a specialist with a new task
2. Go to respond_to_user if enough information is available OR if max steps are near

Decision rules:
- Answer the current user turn only. Do not proactively execute likely future turns such as collecting historical data, fine-tuning, validation, anomaly detection, or work-order planning unless the latest user message explicitly asks for that work
- Use data_collection_specialist when raw facts are needed: asset/sensor inventory, sensor history, current readings, CSV exports, work orders, events, alert rules, or baseline statistics
- Use time_series_analysis_specialist only when the question requires sensor time-series analytics: anomaly detection, forecasting, trend estimation, model fine-tuning, or TSFM capability discovery
- Before using time_series_analysis_specialist for anomaly detection, forecasting, trend analysis, validation, or fine-tuning, ensure a relevant dataset_ref artifact with an existing csv_path already exists and include that artifact ID in input_artifacts; if no such dataset_ref exists for the requested asset/time window, call data_collection_specialist first to retrieve history_csv
- Use failure_reasoning_specialist when the question asks about causes, failure modes, fault hypotheses, sensor-to-failure mappings, or distinguishing competing diagnoses; it may be the first specialist if the user asks for detectable failure modes or known failure-sensor mappings
- Use maintenance_planning_specialist when the question is about work-order history/distribution, failure rate or MTBI from work orders, next-work-order prediction, alert-to-failure analysis, bundling, scheduling, maintenance actions, recovery procedure, or management-ready remediation plans
- For work-order-only planning/review questions, start with maintenance_planning_specialist instead of collecting sensor data
- For alert/event triage questions, start with maintenance_planning_specialist when alert/event records or alert-to-failure probabilities are the primary evidence; collect sensor data later only if validation is requested
- For real-time incident or trip reports (e.g. "tripped", "shut down", "operator just reported", "investigate immediately"), start with data_collection_specialist to collect recent sensor inventory/history and identify unavailable sensors; use time_series_analysis_specialist next for anomalies on available sensor data, then failure_reasoning_specialist for root cause
- For real-time incident or trip reports, do not respond immediately after data collection if a usable dataset_ref/csv_path was collected; first call time_series_analysis_specialist to run anomaly detection on the available recent sensor data
- For sensor/data-quality or raw measurement questions, start with data_collection_specialist and use time_series_analysis_specialist only if statistical/anomaly/trend analysis is requested
- For predictive-maintenance setup, sensor prioritization, and failure detectability questions, start with failure_reasoning_specialist to identify relevant failure modes and sensors before collecting historical data
- For predictive-maintenance setup questions, once failure_reasoning_specialist has produced the relevant failure modes/sensor mapping, go to respond_to_user unless the latest user explicitly asks to collect data, fine-tune, validate, run anomaly detection, forecast, or create a work order
- For follow-up questions, reuse conversation memory and prior artifact IDs instead of restarting from scratch
- If the latest user question can be answered from conversation memory and existing artifacts, go directly to respond_to_user
- Go to respond_to_user when the user's goal is answered or when step_count >= {steps_before_respond}
- Do NOT call the same specialist for the exact same purpose twice
- If a specialist reported it cannot fulfil a task, do NOT send it the same task again.
  Either route the missing piece to a specialist whose TOOLS cover it, or go to
  respond_to_user and answer with the evidence already collected
- Check the requested work against that specialist's TOOLS before dispatching. If no
  specialist owns a tool for it, the work cannot be produced by dispatch at all —
  go to respond_to_user and reason over the existing artifacts instead
- When calling a specialist, include all relevant artifact IDs in input_artifacts
- Artifact IDs such as "artifact_dc_001" are references, not file paths; specialists must use concrete file paths from artifact payloads such as csv_path
- If the user does not name a specific asset, write the goal to explicitly cover ALL assets at the site (e.g. "all chillers at site MAIN") and leave asset_ids as [] so the specialist discovers them via iot.assets

Time window rules (CRITICAL):
- The case_state.time_window already contains concrete ISO 8601 start/end strings — copy them exactly into next_task.time_window
- NEVER compute or invent dates; NEVER use expressions like {{"$subtract": ...}} or function calls
- If the user did not specify a time period, use the time_window from case_state as-is

YOUR RESPONSE MUST BE A SINGLE RAW JSON OBJECT AND NOTHING ELSE.
Do not write any explanation. Output only valid JSON matching this exact schema:
{{
  "next_node": "<one of: data_collection_specialist | time_series_analysis_specialist | failure_reasoning_specialist | maintenance_planning_specialist | respond_to_user>",
  "next_task": {{
    "case_id": "{case_id}",
    "task_type": "<short_snake_case_label>",
    "goal": "<specific goal for the specialist>",
    "site": "<site name>",
    "asset_ids": [...],
    "time_window": {{"start": "...", "end": "...", "lookback_days": null}},
    "focus_metrics": [...],
    "input_artifacts": [...],
    "constraints": {{}}
  }},
  "case_status": "<one of: collecting_data | analyzing | reasoning | planning | waiting_for_user | completed>",
  "next_step": "<one sentence describing what happens next>"
}}

Note: set next_task to null (JSON null) if next_node is "respond_to_user".
All input_artifacts IDs must be from the already collected artifacts list above.

JSON:"""


#: Rendered from the specialist classes so the supervisor sees the real tool lists.
_SPECIALIST_CATALOG = format_specialist_catalog([
    DataCollectionSpecialist,
    TimeSeriesAnalysisSpecialist,
    FailureReasoningSpecialist,
    MaintenancePlanningSpecialist,
])


def _goal_signature(goal: str) -> frozenset[str]:
    """Bag of meaningful words, for judging whether two goals ask the same thing."""
    stop = {"the", "a", "an", "for", "and", "to", "of", "in", "on", "at", "by", "with",
            "using", "from", "is", "are", "be", "any", "all", "this", "that", "site"}
    words = {w.strip(".,;:()[]\"'").lower() for w in goal.split()}
    return frozenset(w for w in words if w and w not in stop and not w.isdigit())


def _goals_match(a: str, b: str, threshold: float = 0.6) -> bool:
    """Whether two goals are the same ask reworded.

    Uses the overlap coefficient rather than Jaccard: a rephrasing often adds
    qualifiers ("using historical sensor data"), which inflates the union and
    would push a genuine repeat below a Jaccard threshold. Observed pair from the
    logs — "Validate the causal links between anomalies for Chiller 3" vs
    "Validate the causal links using historical sensor data for Chiller 3" —
    scores 0.44 by Jaccard but 0.67 here.
    """
    sa, sb = _goal_signature(a), _goal_signature(b)
    if len(sa) < 3 or len(sb) < 3:  # too short to judge; do not block on it
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= threshold


_VALID_STATUSES = {
    "collecting_data",
    "analyzing",
    "reasoning",
    "planning",
    "waiting_for_user",
    "completed",
}

_VALID_NEXT_NODES = {
    "data_collection_specialist",
    "time_series_analysis_specialist",
    "failure_reasoning_specialist",
    "maintenance_planning_specialist",
    "respond_to_user",
}


def _turn_id(state: GraphState) -> str:
    return f"turn_{state.get('turn_index', 1):03d}"


class SupervisorAgent:
    role = "supervisor"

    def __init__(
        self,
        llm,
        artifact_store: ArtifactStore,
        event_stream: EventStream,
        behavior_log: BehaviorLog,
        reference_date: datetime | None = None,
        max_repeat_dispatch: int = 0,
    ) -> None:
        self.llm = llm
        self.artifact_store = artifact_store
        self.event_stream = event_stream
        self.behavior_log = behavior_log
        self._reference_date = reference_date
        # 0 disables the guard. The prompt already says not to call the same
        # specialist twice for the same purpose, but that is advisory only: a
        # model can reword task_type each time and loop indefinitely, burning
        # the step budget and inflating tool-call and latency metrics.
        self._max_repeat_dispatch = max_repeat_dispatch
        self._dispatch_history: dict[str, list[str]] = {}
        # (role, goal) pairs a specialist declared outside its tools, per turn.
        self._unmet: dict[str, list[tuple[str, str, str]]] = {}

    def record_unmet(self, turn_key: str, role: str, goal: str, reason: str) -> None:
        """Remember that *role* reported it cannot do *goal* during this turn."""
        entries = self._unmet.setdefault(turn_key, [])
        if not any(r == role and g == goal for r, g, _ in entries):
            entries.append((role, goal, reason))

    def _format_unmet(self, turn_key: str) -> str:
        entries = self._unmet.get(turn_key, [])
        if not entries:
            return "(none)"
        return "\n".join(
            f"- {role} cannot do: {goal}\n    reason: {reason}"
            for role, goal, reason in entries
        )

    async def decide(self, state: GraphState) -> GraphState:
        case_state: CaseState = state["case_state"]
        step_count = state.get("step_count", 0) + 1
        max_steps = state.get("max_steps", 12)

        # Hard stop: too many steps
        if step_count > max_steps:
            case_state.status = "waiting_for_user"
            self.behavior_log.write(
                case_id=case_state.case_id,
                agent_role=self.role,
                task_type="max_steps_exceeded",
                input_artifact_ids=case_state.artifact_ids,
                tool_calls=[],
                output_artifact_ids=[],
                status="ok",
                turn_id=_turn_id(state),
            )
            return {
                **state,
                "case_state": case_state,
                "current_task": None,
                "next_node": "respond_to_user",
                "step_count": step_count,
                "error_message": "Maximum agent step count reached.",
            }

        self.event_stream.emit(
            case_id=case_state.case_id,
            agent_role=self.role,
            task_type="supervisor_decision",
            status="running",
            message=f"Supervisor deciding next step (step {step_count}/{max_steps}).",
        )

        # Build artifacts summary for prompt
        existing_artifacts = self.artifact_store.get_many(case_state.artifact_ids)
        artifacts_summary = self._format_artifacts_summary(existing_artifacts)
        conversation_memory = state.get("conversation_memory")
        current_user_message = state.get("current_user_message") or case_state.user_goal

        error_msg = state.get("error_message") or "none"
        steps_before_respond = max(max_steps - 2, 1)

        from datetime import timezone
        ref = self._reference_date or datetime.now(timezone.utc)
        today = ref.strftime("%Y-%m-%dT%H:%M:%S")

        turn_key = f"{case_state.case_id}:{_turn_id(state)}"
        prompt = _SUPERVISOR_PROMPT.format(
            today=today,
            specialist_catalog=_SPECIALIST_CATALOG,
            unmet_reports=self._format_unmet(turn_key),
            current_user_message=current_user_message,
            case_state_json=case_state.model_dump_json(indent=2),
            conversation_memory=format_conversation_memory(conversation_memory),
            artifacts_summary=artifacts_summary,
            error_message=error_msg,
            step_count=step_count,
            max_steps=max_steps,
            steps_before_respond=steps_before_respond,
            case_id=case_state.case_id,
        )

        decision, validation_error = await self._call_and_validate(
            prompt, case_state, max_steps, turn_key
        )

        if decision is None:
            # Both attempts failed: go to respond_to_user
            case_state.status = "waiting_for_user"
            self.behavior_log.write(
                case_id=case_state.case_id,
                agent_role=self.role,
                task_type="supervisor_decision",
                input_artifact_ids=case_state.artifact_ids,
                tool_calls=[],
                output_artifact_ids=[],
                status="failed",
                turn_id=_turn_id(state),
            )
            return {
                **state,
                "case_state": case_state,
                "current_task": None,
                "next_node": "respond_to_user",
                "step_count": step_count,
                "error_message": validation_error or "Supervisor LLM failed to produce a valid decision.",
            }

        if decision.next_node != "respond_to_user":
            self._dispatch_history.setdefault(turn_key, []).append(decision.next_node)

        # Apply decision to case state
        case_state = self._apply_decision(case_state, decision)

        self.behavior_log.write(
            case_id=case_state.case_id,
            agent_role=self.role,
            task_type="supervisor_decision",
            input_artifact_ids=case_state.artifact_ids,
            tool_calls=[],
            output_artifact_ids=[],
            status="ok",
            turn_id=_turn_id(state),
        )

        self.event_stream.emit(
            case_id=case_state.case_id,
            agent_role=self.role,
            task_type="supervisor_decision",
            status="completed",
            message=f"-> {decision.next_node} | {decision.next_step or ''}",
        )

        return {
            **state,
            "case_state": case_state,
            "current_task": decision.next_task,
            "next_node": decision.next_node,
            "step_count": step_count,
            "error_message": None,
        }

    async def _call_and_validate(
        self,
        prompt: str,
        case_state: CaseState,
        max_steps: int,
        turn_key: str = "",
    ) -> tuple[SupervisorDecision | None, str | None]:
        retry_prompt = prompt
        last_error: str | None = None

        for attempt in range(2):
            raw = await call_llm(self.llm, retry_prompt)
            parsed = parse_json_from_llm(raw)

            if parsed is None:
                last_error = "LLM response was not valid JSON."
                retry_prompt = prompt + f"\n\nAttempt {attempt+1} failed: {last_error}\nOutput ONLY a raw JSON object."
                continue

            try:
                decision = SupervisorDecision.model_validate(parsed)
            except Exception as exc:  # noqa: BLE001
                last_error = f"SupervisorDecision validation failed: {exc}"
                retry_prompt = prompt + f"\n\nAttempt {attempt+1} failed: {last_error}\nOutput ONLY a raw JSON object."
                continue

            # Business rule validation (§13.1)
            error = self._validate_decision(decision, case_state, turn_key)
            if error:
                last_error = error
                retry_prompt = (
                    prompt
                    + f"\n\nAttempt {attempt+1} failed business validation: {error}\n"
                    "Fix the issue and output ONLY a corrected raw JSON object."
                )
                continue

            return decision, None

        return None, last_error

    def _validate_decision(
        self, decision: SupervisorDecision, case_state: CaseState, turn_key: str = ""
    ) -> str | None:
        if decision.next_node not in _VALID_NEXT_NODES:
            return f"Invalid next_node: {decision.next_node}"

        repeat_error = self._check_repeat_dispatch(decision, turn_key)
        if repeat_error:
            return repeat_error

        unmet_error = self._check_unmet_dispatch(decision, turn_key)
        if unmet_error:
            return unmet_error

        if decision.case_status not in _VALID_STATUSES:
            return f"Invalid case_status: {decision.case_status}"

        if decision.next_node == "respond_to_user":
            if decision.next_task is not None:
                return "next_task must be null when next_node is respond_to_user"
            return None

        # Specialist node — next_task must be present
        if decision.next_task is None:
            return f"next_task must not be null when next_node is {decision.next_node}"

        task = decision.next_task
        if task.case_id != case_state.case_id:
            return (
                f"next_task.case_id '{task.case_id}' != case_state.case_id '{case_state.case_id}'"
            )

        if not self._same_time_window(task.time_window, case_state.time_window):
            return (
                "next_task.time_window must match case_state.time_window exactly. "
                "Do not invent a different time window; copy the current case_state "
                "start/end values unless the latest user message explicitly changed "
                "the period and case_state already reflects that change."
            )

        # Validate input_artifacts exist in store
        missing = [
            aid for aid in task.input_artifacts
            if not self.artifact_store.has(aid)
        ]
        if missing:
            return f"next_task.input_artifacts references unknown artifact IDs: {missing}"

        if (
            decision.next_node == "time_series_analysis_specialist"
            and self._task_requires_time_series_data(task.task_type, task.goal)
            and not self._has_csv_input_artifact(task.input_artifacts)
        ):
            return (
                "time_series_analysis_specialist was selected for an analysis task "
                "that requires raw time-series data, but next_task.input_artifacts "
                "does not include any artifact with a concrete .csv file path. "
                "If no suitable CSV artifact exists, route to data_collection_specialist "
                "first to retrieve history_csv for the requested asset/time window."
            )

        return None

    def _check_unmet_dispatch(
        self, decision: SupervisorDecision, turn_key: str
    ) -> str | None:
        """Refuse to re-send a task a specialist already declared out of reach."""
        if decision.next_node == "respond_to_user" or decision.next_task is None:
            return None
        for role, goal, reason in self._unmet.get(turn_key, []):
            if role == decision.next_node and _goals_match(goal, decision.next_task.goal):
                return (
                    f"{role} already reported it cannot do this task ({reason}). "
                    f"Re-sending it will return nothing. Route the missing piece to a "
                    f"specialist whose TOOLS cover it, or set next_node to "
                    f"'respond_to_user' and answer from the evidence already collected."
                )
        return None

    def _check_repeat_dispatch(
        self, decision: SupervisorDecision, turn_key: str
    ) -> str | None:
        """Reject a specialist that has already been dispatched N times this turn.

        Guards against the supervisor looping on one specialist by rewording
        task_type, which the prompt-level rule cannot catch. Rejection sends the
        decision back for a retry; if the retry loops too, the caller falls
        through to respond_to_user, which is the desired escape.
        """
        limit = self._max_repeat_dispatch
        if limit <= 0 or not turn_key or decision.next_node == "respond_to_user":
            return None

        history = self._dispatch_history.get(turn_key, [])
        consecutive = 0
        for role in reversed(history):
            if role != decision.next_node:
                break
            consecutive += 1
        if consecutive < limit:
            return None
        return (
            f"{decision.next_node} has already been dispatched {consecutive} times "
            f"in a row during this turn, which indicates a loop. Either choose a "
            f"different specialist, or set next_node to 'respond_to_user' and answer "
            f"with the evidence already collected."
        )

    def _apply_decision(
        self, case_state: CaseState, decision: SupervisorDecision
    ) -> CaseState:
        if decision.case_status in _VALID_STATUSES:
            case_state.status = decision.case_status  # type: ignore[assignment]
        case_state.next_step = decision.next_step

        # Check if we now have reasoning / planning artifacts to promote
        existing = self.artifact_store.get_many(case_state.artifact_ids)
        for art in existing:
            if art.artifact_type == "reasoning_result" and case_state.root_cause is None:
                rc = art.payload.get("primary_hypothesis") or art.payload.get("root_cause")
                if rc:
                    case_state.root_cause = str(rc)
            if art.artifact_type in ("planning_result", "draft_action"):
                actions = art.payload.get("recommended_actions") or art.payload.get("actions")
                if isinstance(actions, list) and actions:
                    case_state.recommended_actions = actions
        return case_state

    @staticmethod
    def _task_requires_time_series_data(task_type: str, goal: str) -> bool:
        text = f"{task_type} {goal}".lower()
        data_required_markers = (
            "anomaly",
            "detect",
            "detection",
            "forecast",
            "trend",
            "validate",
            "validation",
            "fine-tun",
            "finetun",
            "model",
            "tsad",
        )
        capability_markers = (
            "capability",
            "capabilities",
            "supported analyses",
            "available analyses",
            "ai tasks",
            "models",
        )
        return any(m in text for m in data_required_markers) and not any(
            m in text for m in capability_markers
        )

    def _has_csv_input_artifact(self, artifact_ids: list[str]) -> bool:
        artifacts = self.artifact_store.get_many(artifact_ids)
        for artifact in artifacts:
            if artifact.artifact_type != "dataset_ref":
                continue
            for path in extract_file_paths(artifact.payload):
                if path.lower().endswith(".csv") and Path(path).is_file():
                    return True
        return False

    @classmethod
    def _same_time_window(cls, left, right) -> bool:
        if not (left.start or left.end or right.start or right.end):
            return True
        return (
            cls._normalize_dt(left.start) == cls._normalize_dt(right.start)
            and cls._normalize_dt(left.end) == cls._normalize_dt(right.end)
        )

    @staticmethod
    def _normalize_dt(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None).isoformat()
        except ValueError:
            return value

    @staticmethod
    def _format_artifacts_summary(artifacts: list) -> str:
        if not artifacts:
            return "(none — no artifacts collected yet)"
        return format_artifacts_summary(artifacts)
