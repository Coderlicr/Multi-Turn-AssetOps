"""Entry point for the Supervisor-Specialist system."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.agents.failure_reasoning import FailureReasoningSpecialist
from agent.supervisor_specialist.agents.maintenance_planning import MaintenancePlanningSpecialist
from agent.supervisor_specialist.agents.supervisor import SupervisorAgent
from agent.supervisor_specialist.agents.time_series_analysis import TimeSeriesAnalysisSpecialist
from agent.supervisor_specialist.graph import Dependencies, build_graph
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.runtime.mcp_tools import DEFAULT_SERVER_PATHS, MCPToolClient
from agent.supervisor_specialist.schemas import (
    ArtifactEnvelope,
    CaseState,
    ConversationMemory,
    DialogTurnRecord,
    GraphState,
    TimeWindow,
    ToolCallSummary,
)

_DEFAULT_LOOKBACK_DAYS = 30

_CHECKPOINT_TYPES = (
    ArtifactEnvelope,
    CaseState,
    ConversationMemory,
    DialogTurnRecord,
    TimeWindow,
    ToolCallSummary,
)


def _make_case_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"case_{ts}_{short}"


def _detect_site(question: str) -> str:
    if "MAIN" in question.upper():
        return "MAIN"
    return "MAIN"


def _resolve_reference_date(reference_date: str | None) -> datetime:
    """Return a datetime from an ISO date string, or UTC now if not provided."""
    if reference_date:
        return datetime.strptime(reference_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _build_time_window(ref: datetime, lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> TimeWindow:
    start = ref - timedelta(days=lookback_days)
    return TimeWindow(
        start=start.strftime("%Y-%m-%dT%H:%M:%S"),
        end=ref.strftime("%Y-%m-%dT%H:%M:%S"),
        lookback_days=lookback_days,
    )


class SupervisorSpecialistRunner:
    def __init__(
        self,
        llm,
        server_paths: dict | None = None,
        max_steps: int = 12,
        quiet: bool = False,
        log_dir: Path | None = None,
        reference_date: str | None = None,
        mcp_tools: MCPToolClient | None = None,
        parallel: bool = False,
    ) -> None:
        self._llm = llm
        self._max_steps = max_steps
        self._parallel = parallel
        self._ref = _resolve_reference_date(reference_date)
        self._dialog_thread_id = f"dialog_{uuid.uuid4().hex}"
        self._dialog_started = False
        self._last_dialog_state: GraphState | None = None

        artifact_store = ArtifactStore()
        event_stream = EventStream(quiet=quiet)
        behavior_log = BehaviorLog(log_dir=log_dir)
        self._behavior_log = behavior_log
        mcp_tools = mcp_tools or MCPToolClient(server_paths=server_paths or DEFAULT_SERVER_PATHS)

        supervisor = SupervisorAgent(
            llm=llm,
            artifact_store=artifact_store,
            event_stream=event_stream,
            behavior_log=behavior_log,
            reference_date=self._ref,
        )

        def _make_specialist(cls):
            return cls(
                llm=llm,
                mcp_tools=mcp_tools,
                artifact_store=artifact_store,
                behavior_log=behavior_log,
                event_stream=event_stream,
                enable_parallel=parallel,
            )

        deps = Dependencies(
            supervisor=supervisor,
            data_collection=_make_specialist(DataCollectionSpecialist),
            time_series_analysis=_make_specialist(TimeSeriesAnalysisSpecialist),
            failure_reasoning=_make_specialist(FailureReasoningSpecialist),
            maintenance_planning=_make_specialist(MaintenancePlanningSpecialist),
            artifact_store=artifact_store,
            event_stream=event_stream,
            behavior_log=behavior_log,
            llm=llm,
        )

        serde = JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES)
        self._graph = build_graph(deps, checkpointer=MemorySaver(serde=serde))

    async def run(self, question: str) -> str:
        case_state = self._init_case_state(question)
        self._behavior_log.write(
            case_id=case_state.case_id,
            agent_role="user",
            task_type="user_question",
            input_artifact_ids=[],
            tool_calls=[],
            output_artifact_ids=[],
            status="ok",
            turn_id="turn_001",
            user_message=question,
        )
        initial_state = self._initial_state(question, case_state)
        config = {"configurable": {"thread_id": case_state.case_id}}
        result = await self._graph.ainvoke(initial_state, config=config)
        return result.get("final_response") or "(no response generated)"

    async def run_turn(self, question: str) -> str:
        """Run one turn in the runner's in-memory multi-turn dialog session."""
        config = {"configurable": {"thread_id": self._dialog_thread_id}}
        if self._dialog_started:
            case_id = self._last_dialog_state["case_state"].case_id
            input_state: GraphState = {
                "current_user_message": question,
                "max_steps": self._max_steps,
            }
        else:
            case_state = self._init_case_state(question)
            case_id = case_state.case_id
            input_state = self._initial_state(question, case_state)

        next_turn_index = (
            self._last_dialog_state.get("turn_index", 0) + 1
            if self._dialog_started and self._last_dialog_state
            else 1
        )

        self._behavior_log.write(
            case_id=case_id,
            agent_role="user",
            task_type="user_question",
            input_artifact_ids=[],
            tool_calls=[],
            output_artifact_ids=[],
            status="ok",
            turn_id=f"turn_{next_turn_index:03d}",
            user_message=question,
        )
        result = await self._graph.ainvoke(input_state, config=config)
        self._dialog_started = True
        self._last_dialog_state = result
        return result.get("final_response") or "(no response generated)"

    @property
    def last_dialog_state(self) -> GraphState | None:
        return self._last_dialog_state

    def _initial_state(self, question: str, case_state: CaseState) -> GraphState:
        return {
            "case_state": case_state,
            "current_user_message": question,
            "conversation_memory": ConversationMemory(
                active_site=case_state.site,
                active_asset_ids=case_state.asset_ids,
                active_time_window=case_state.time_window,
                focus_metrics=case_state.focus_metrics,
            ),
            "current_task": None,
            "last_artifacts": [],
            "final_response": None,
            "next_node": "supervisor",
            "step_count": 0,
            "max_steps": self._max_steps,
            "error_message": None,
            "turn_index": 0,
            "turn_artifact_ids": [],
            "turn_tool_calls": [],
        }

    def _init_case_state(self, question: str) -> CaseState:
        return CaseState(
            case_id=_make_case_id(),
            user_goal=question,
            site=_detect_site(question),
            asset_ids=[],
            time_window=_build_time_window(self._ref),
            focus_metrics=[],
            status="collecting_data",
            artifact_ids=[],
        )
