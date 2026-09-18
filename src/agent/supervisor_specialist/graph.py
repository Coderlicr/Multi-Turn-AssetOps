"""LangGraph graph definition for the Supervisor-Specialist system.

LangGraph is responsible only for:
  - Storing shared state (GraphState)
  - Running nodes
  - Routing via the next_node field written by Supervisor

Business logic, planning, and specialist selection all live in the agent classes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from langgraph.graph import END, START, StateGraph

from agent.supervisor_specialist._utils import (
    call_llm,
    format_artifacts_summary,
    format_conversation_memory,
)
from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.agents.failure_reasoning import FailureReasoningSpecialist
from agent.supervisor_specialist.agents.maintenance_planning import MaintenancePlanningSpecialist
from agent.supervisor_specialist.agents.supervisor import SupervisorAgent
from agent.supervisor_specialist.agents.time_series_analysis import TimeSeriesAnalysisSpecialist
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.schemas import (
    CaseState,
    ConversationMemory,
    DialogTurnRecord,
    GraphState,
    TimeWindow,
)

_log = logging.getLogger(__name__)

#: Full cross-turn evidence reuse (default system).
REUSE_FULL = "full"
#: Ablation: keep natural-language dialogue memory, drop structured evidence reuse.
REUSE_NONE = "none"
#: Ablation: no cross-turn state at all; every turn starts from scratch.
REUSE_STATELESS = "stateless"

REUSE_MODES = (REUSE_FULL, REUSE_NONE, REUSE_STATELESS)

_FINAL_RESPONSE_PROMPT = """\
You are a senior industrial asset operations expert.
Based on the conversation memory and analysis below, write a clear and structured response to the user's latest question.

Latest user question: {user_goal}

Conversation memory:
{conversation_memory}

Case findings:
{artifacts_summary}

Root cause identified: {root_cause}
Recommended actions: {recommended_actions}

Error note (if any): {error_message}

Write a comprehensive response that:
1. Directly answers the user's question
2. Summarizes key findings and evidence
3. States the most likely root cause with confidence level (if applicable)
4. Lists concrete recommended actions in priority order
5. Notes any remaining uncertainties or next steps

Response:"""

_ASSET_RE = re.compile(r"\bChiller\s+\d+\b", re.IGNORECASE)
_MONTH_RE = re.compile(
    r"\b("
    r"january|february|march|april|may|june|july|august|september|october|november|december"
    r")\s+(\d{4})\b",
    re.IGNORECASE,
)
_YEAR_RANGE_RE = re.compile(
    r"\b(19\d{2}|20\d{2})\b\s*(?:through|thru|to|[-–—]|until|and)\s*\b(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_SINGLE_YEAR_RE = re.compile(r"\b(?:in|for|during)\s+(19\d{2}|20\d{2})\b", re.IGNORECASE)
_METRIC_KEYWORDS = {
    "temperature": ["temperature", "temp"],
    "efficiency": ["efficiency", "kw/ton", "kW/ton"],
    "power": ["power", "power input"],
    "load": ["load", "loaded", "cooling load"],
    "tonnage": ["tonnage", "tons"],
    "work_order": ["work order", "maintenance history", "corrective", "preventive"],
    "alert": ["alert", "alarm"],
}


@dataclass
class Dependencies:
    supervisor: SupervisorAgent
    data_collection: DataCollectionSpecialist
    time_series_analysis: TimeSeriesAnalysisSpecialist
    failure_reasoning: FailureReasoningSpecialist
    maintenance_planning: MaintenancePlanningSpecialist
    artifact_store: ArtifactStore
    event_stream: EventStream
    behavior_log: BehaviorLog
    llm: object  # LiteLLMBackend
    reuse_mode: str = REUSE_FULL


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_assets(message: str) -> list[str]:
    return _unique(m.group(0).title() for m in _ASSET_RE.finditer(message))


def _parse_site(message: str, memory: ConversationMemory | None) -> str:
    if "MAIN" in message.upper():
        return "MAIN"
    if memory and memory.active_site:
        return memory.active_site
    return "MAIN"


def _parse_time_window(
    message: str,
    memory: ConversationMemory | None,
    current: TimeWindow,
) -> TimeWindow:
    text = message.lower()
    if "same period" in text and memory and memory.active_time_window.start:
        return memory.active_time_window

    year_range_match = _YEAR_RANGE_RE.search(message)
    if year_range_match:
        start_year = int(year_range_match.group(1))
        end_year = int(year_range_match.group(2))
        if start_year > end_year:
            start_year, end_year = end_year, start_year
        return TimeWindow(
            start=f"{start_year:04d}-01-01T00:00:00",
            end=f"{end_year:04d}-12-31T23:59:59",
            mode="year_range",
        )

    single_year_match = _SINGLE_YEAR_RE.search(message)
    if single_year_match:
        year = int(single_year_match.group(1))
        return TimeWindow(
            start=f"{year:04d}-01-01T00:00:00",
            end=f"{year:04d}-12-31T23:59:59",
            mode="calendar_year",
        )

    month_match = _MONTH_RE.search(message)
    if month_match:
        month_name, year_raw = month_match.groups()
        year = int(year_raw)
        month = datetime.strptime(month_name[:3], "%b").month
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        return TimeWindow(start=_format_dt(start), end=_format_dt(end), mode="calendar_month")

    if "last two months" in text or "past two months" in text or "last 2 months" in text:
        end = datetime.fromisoformat(current.end) if current.end else datetime.utcnow()
        return TimeWindow(
            start=_format_dt(end - timedelta(days=60)),
            end=_format_dt(end),
            lookback_days=60,
        )

    if "past month" in text or "last month" in text or "recently" in text:
        end = datetime.fromisoformat(current.end) if current.end else datetime.utcnow()
        return TimeWindow(
            start=_format_dt(end - timedelta(days=30)),
            end=_format_dt(end),
            lookback_days=30,
        )

    if memory and memory.active_time_window.start:
        return memory.active_time_window
    return current


def _parse_focus_metrics(message: str, memory: ConversationMemory | None) -> list[str]:
    text = message.lower()
    metrics = [
        metric
        for metric, keywords in _METRIC_KEYWORDS.items()
        if any(keyword.lower() in text for keyword in keywords)
    ]
    if metrics:
        return metrics
    if memory and memory.focus_metrics:
        return memory.focus_metrics
    return []


def _build_rolling_summary(memory: ConversationMemory) -> str:
    lines = []
    for turn in memory.recent_turns[-5:]:
        answer = turn.assistant_answer.replace("\n", " ")
        lines.append(f"T{turn.turn_index}: {turn.user_message} -> {answer[:300]}")
    if memory.active_asset_ids:
        lines.append(f"Active assets: {', '.join(memory.active_asset_ids)}")
    if memory.focus_metrics:
        lines.append(f"Focus metrics: {', '.join(memory.focus_metrics)}")
    return "\n".join(lines)[-1500:]


def _drop_evidence_carry_over(
    memory: ConversationMemory,
    case_state: CaseState | None,
    reuse_mode: str,
) -> None:
    """Remove every cross-turn reference to structured evidence.

    Used by the reuse ablations. The artifact store itself keeps the data; this
    only clears the reference paths a later turn could otherwise follow, so the
    supervisor neither sees earlier artifacts nor cites IDs it cannot resolve
    (an unresolvable ID would fail decision validation and burn agent steps,
    penalising the ablation for the wrong reason).
    """
    memory.active_artifact_ids = []
    for turn in memory.recent_turns:
        turn.artifact_ids = []
    if case_state is not None:
        case_state.artifact_ids = []
        # root_cause / recommended_actions are promoted from artifact payloads,
        # so they are structured evidence too.
        case_state.root_cause = None
        case_state.recommended_actions = []
        if reuse_mode == REUSE_STATELESS:
            case_state.asset_ids = []
            case_state.focus_metrics = []


def _turn_id(state: GraphState) -> str:
    return f"turn_{state.get('turn_index', 1):03d}"


def build_graph(deps: Dependencies, checkpointer=None):
    """Build and compile the Supervisor-Specialist LangGraph."""

    def route_from_supervisor(state: GraphState) -> str:
        return state.get("next_node", "respond_to_user")

    def _make_specialist_node(specialist):
        async def node(state: GraphState) -> GraphState:
            task = state.get("current_task")
            if task is None:
                _log.error("%s: received None current_task", specialist.role)
                deps.behavior_log.write(
                    case_id=state["case_state"].case_id,
                    agent_role=specialist.role,
                    task_type="error",
                    input_artifact_ids=[],
                    tool_calls=[],
                    output_artifact_ids=[],
                    status="failed",
                    turn_id=_turn_id(state),
                )
                return {
                    **state,
                    "next_node": "supervisor",
                    "error_message": f"{specialist.role}: current_task was None.",
                }

            try:
                task = task.model_copy(
                    update={
                        "input_artifacts": _unique(
                            task.input_artifacts + state["case_state"].artifact_ids
                        ),
                        "constraints": {
                            **task.constraints,
                            "turn_id": _turn_id(state),
                        }
                    }
                )
                result = await specialist.run(task)
                artifacts = result.artifacts
                deps.artifact_store.save_many(artifacts)

                case_state = state["case_state"]
                case_state.artifact_ids.extend(a.artifact_id for a in artifacts)
                case_state.artifact_ids = _unique(case_state.artifact_ids)
                case_state.asset_ids = _unique(
                    case_state.asset_ids
                    + [asset for artifact in artifacts for asset in artifact.asset_ids]
                )
                for artifact in artifacts:
                    if artifact.time_window.start:
                        case_state.time_window = artifact.time_window
                        break
                turn_artifact_ids = state.get("turn_artifact_ids", []) + [
                    a.artifact_id for a in artifacts
                ]
                turn_tool_calls = state.get("turn_tool_calls", []) + result.tool_calls

                return {
                    **state,
                    "case_state": case_state,
                    "last_artifacts": artifacts,
                    "turn_artifact_ids": _unique(turn_artifact_ids),
                    "turn_tool_calls": turn_tool_calls,
                    "current_task": None,
                    "next_node": "supervisor",
                    "error_message": None,
                }
            except Exception as exc:  # noqa: BLE001
                _log.exception("%s: unexpected error: %s", specialist.role, exc)
                deps.behavior_log.write(
                    case_id=state["case_state"].case_id,
                    agent_role=specialist.role,
                    task_type=task.task_type if task else "error",
                    input_artifact_ids=task.input_artifacts if task else [],
                    tool_calls=[],
                    output_artifact_ids=[],
                    status="failed",
                    turn_id=_turn_id(state),
                )
                deps.event_stream.emit(
                    case_id=state["case_state"].case_id,
                    agent_role=specialist.role,
                    task_type=task.task_type if task else "error",
                    status="failed",
                    message=f"Unexpected error: {exc}",
                )
                return {
                    **state,
                    "next_node": "supervisor",
                    "error_message": f"{specialist.role} error: {exc}",
                }

        node.__name__ = f"{specialist.role}_node"
        return node

    async def prepare_turn_node(state: GraphState) -> GraphState:
        current_message = state.get("current_user_message") or (
            state["case_state"].user_goal if state.get("case_state") else ""
        )
        memory = state.get("conversation_memory") or ConversationMemory()
        old_case_state = state.get("case_state")

        # Opening the turn is what makes earlier artifacts invisible when the
        # store is turn-scoped (reuse ablation); under full reuse it is a no-op.
        deps.artifact_store.begin_turn()
        if deps.reuse_mode != REUSE_FULL:
            _drop_evidence_carry_over(memory, old_case_state, deps.reuse_mode)
            if deps.reuse_mode == REUSE_STATELESS:
                memory = ConversationMemory()

        if old_case_state is None:
            case_state = CaseState(
                case_id=f"case_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                user_goal=current_message,
                site="MAIN",
                asset_ids=[],
                time_window=TimeWindow(),
                focus_metrics=[],
                status="collecting_data",
            )
        else:
            case_state = old_case_state

        assets = _parse_assets(current_message) or memory.active_asset_ids or case_state.asset_ids
        site = _parse_site(current_message, memory)
        time_window = _parse_time_window(current_message, memory, case_state.time_window)
        focus_metrics = _parse_focus_metrics(current_message, memory)

        case_state.user_goal = current_message
        case_state.site = site
        case_state.asset_ids = assets
        case_state.time_window = time_window
        case_state.focus_metrics = focus_metrics
        case_state.status = "collecting_data"
        case_state.artifact_ids = _unique(
            case_state.artifact_ids + memory.active_artifact_ids
        )

        memory.active_site = site
        memory.active_asset_ids = assets
        memory.active_time_window = time_window
        memory.focus_metrics = focus_metrics

        return {
            **state,
            "case_state": case_state,
            "conversation_memory": memory,
            "current_user_message": current_message,
            "current_task": None,
            "last_artifacts": [],
            "final_response": None,
            "next_node": "supervisor",
            "step_count": 0,
            "error_message": None,
            "turn_index": state.get("turn_index", 0) + 1,
            "turn_artifact_ids": [],
            "turn_tool_calls": [],
        }

    async def respond_to_user_node(state: GraphState) -> GraphState:
        case_state = state["case_state"]
        artifacts = deps.artifact_store.get_many(case_state.artifact_ids)
        memory = state.get("conversation_memory") or ConversationMemory()
        current_message = state.get("current_user_message") or case_state.user_goal

        deps.event_stream.emit(
            case_id=case_state.case_id,
            agent_role="respond_to_user",
            task_type="final_response",
            status="running",
            message="Building final response.",
        )

        prompt = _FINAL_RESPONSE_PROMPT.format(
            user_goal=current_message,
            conversation_memory=format_conversation_memory(memory),
            artifacts_summary=format_artifacts_summary(artifacts),
            root_cause=case_state.root_cause or "(not identified)",
            recommended_actions=", ".join(case_state.recommended_actions) or "(none)",
            error_message=state.get("error_message") or "none",
        )

        try:
            final_response = await call_llm(deps.llm, prompt)
        except Exception as exc:  # noqa: BLE001
            _log.exception("respond_to_user_node: LLM call failed: %s", exc)
            final_response = (
                f"Analysis complete. Goal: {case_state.user_goal}\n"
                f"Collected {len(artifacts)} artifact(s). "
                f"(Final response generation failed: {exc})"
            )

        if case_state.status != "waiting_for_user":
            case_state.status = "completed"

        turn_artifact_ids = state.get("turn_artifact_ids", [])
        referenced_artifact_ids = turn_artifact_ids or memory.active_artifact_ids[-8:]
        turn_record = DialogTurnRecord(
            turn_index=state.get("turn_index", 1),
            user_message=current_message,
            assistant_answer=final_response,
            artifact_ids=referenced_artifact_ids,
            tool_calls=state.get("turn_tool_calls", []),
            root_cause=case_state.root_cause,
            recommended_actions=case_state.recommended_actions,
        )
        memory.active_site = case_state.site
        memory.active_asset_ids = case_state.asset_ids
        memory.active_time_window = case_state.time_window
        memory.focus_metrics = case_state.focus_metrics
        memory.active_artifact_ids = _unique(
            memory.active_artifact_ids + case_state.artifact_ids
        )
        memory.recent_turns.append(turn_record)
        if len(memory.recent_turns) > memory.max_recent_turns:
            memory.recent_turns = memory.recent_turns[-memory.max_recent_turns :]
        memory.rolling_summary = _build_rolling_summary(memory)

        deps.behavior_log.write(
            case_id=case_state.case_id,
            agent_role="respond_to_user",
            task_type="final_response",
            input_artifact_ids=case_state.artifact_ids,
            tool_calls=[],
            output_artifact_ids=[],
            status="ok",
            turn_id=_turn_id(state),
            final_response=final_response,
        )

        deps.event_stream.emit(
            case_id=case_state.case_id,
            agent_role="respond_to_user",
            task_type="final_response",
            status="completed",
            message="Final response ready.",
        )

        return {
            **state,
            "case_state": case_state,
            "conversation_memory": memory,
            "final_response": final_response,
            "current_task": None,
        }

    # ── Build the graph ────────────────────────────────────────────────────────
    graph = StateGraph(GraphState)

    graph.add_node("prepare_turn", prepare_turn_node)
    graph.add_node("supervisor", deps.supervisor.decide)
    graph.add_node(
        "data_collection_specialist",
        _make_specialist_node(deps.data_collection),
    )
    graph.add_node(
        "time_series_analysis_specialist",
        _make_specialist_node(deps.time_series_analysis),
    )
    graph.add_node(
        "failure_reasoning_specialist",
        _make_specialist_node(deps.failure_reasoning),
    )
    graph.add_node(
        "maintenance_planning_specialist",
        _make_specialist_node(deps.maintenance_planning),
    )
    graph.add_node("respond_to_user", respond_to_user_node)

    graph.add_edge(START, "prepare_turn")
    graph.add_edge("prepare_turn", "supervisor")

    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "data_collection_specialist": "data_collection_specialist",
            "time_series_analysis_specialist": "time_series_analysis_specialist",
            "failure_reasoning_specialist": "failure_reasoning_specialist",
            "maintenance_planning_specialist": "maintenance_planning_specialist",
            "respond_to_user": "respond_to_user",
        },
    )

    graph.add_edge("data_collection_specialist", "supervisor")
    graph.add_edge("time_series_analysis_specialist", "supervisor")
    graph.add_edge("failure_reasoning_specialist", "supervisor")
    graph.add_edge("maintenance_planning_specialist", "supervisor")
    graph.add_edge("respond_to_user", END)

    return graph.compile(checkpointer=checkpointer)
