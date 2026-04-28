"""Supervisor agent — sole decision center for the Supervisor-Specialist system."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from agent.supervisor_specialist._utils import (
    call_llm,
    format_conversation_memory,
    parse_json_from_llm,
)
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
You coordinate specialist agents to answer user questions about industrial assets (chillers, HVAC).

Today (UTC): {today}

Latest user message:
{current_user_message}

Available specialists:
- data_collection_specialist: Collects IoT sensor data, work orders, events, alert rules, asset/sensor inventory
- time_series_analysis_specialist: Performs trend analysis, forecasting, and anomaly detection on time-series data
- failure_reasoning_specialist: Maps sensor anomaly patterns to failure modes and produces root cause hypotheses
- maintenance_planning_specialist: Generates maintenance plans, work order recommendations, and action drafts

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
- Start with data_collection_specialist to gather sensor data and work orders
- Use time_series_analysis_specialist after data collection to detect anomalies/trends
- Use failure_reasoning_specialist after anomaly detection to identify root causes
- Use maintenance_planning_specialist when diagnosis is complete and action plan is needed
- For follow-up questions, reuse conversation memory and prior artifact IDs instead of restarting from scratch
- If the latest user question can be answered from conversation memory and existing artifacts, go directly to respond_to_user
- Go to respond_to_user when the user's goal is answered or when step_count >= {steps_before_respond}
- Do NOT call the same specialist for the exact same purpose twice
- When calling a specialist, include all relevant artifact IDs in input_artifacts

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
    ) -> None:
        self.llm = llm
        self.artifact_store = artifact_store
        self.event_stream = event_stream
        self.behavior_log = behavior_log
        self._reference_date = reference_date

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

        prompt = _SUPERVISOR_PROMPT.format(
            today=today,
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
            prompt, case_state, max_steps
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
            error = self._validate_decision(decision, case_state)
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
        self, decision: SupervisorDecision, case_state: CaseState
    ) -> str | None:
        if decision.next_node not in _VALID_NEXT_NODES:
            return f"Invalid next_node: {decision.next_node}"

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

        # Validate input_artifacts exist in store
        missing = [
            aid for aid in task.input_artifacts
            if not self.artifact_store.has(aid)
        ]
        if missing:
            return f"next_task.input_artifacts references unknown artifact IDs: {missing}"

        return None

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
    def _format_artifacts_summary(artifacts: list) -> str:
        if not artifacts:
            return "(none — no artifacts collected yet)"
        lines = []
        for a in artifacts:
            payload_preview = json.dumps(a.payload, ensure_ascii=False)[:300]
            if len(json.dumps(a.payload, ensure_ascii=False)) > 300:
                payload_preview += "..."
            lines.append(
                f"  [{a.artifact_id}] type={a.artifact_type} producer={a.producer} "
                f"assets={a.asset_ids}\n    preview: {payload_preview}"
            )
        return "\n".join(lines)
