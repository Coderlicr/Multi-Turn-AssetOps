"""Entry point for the Supervisor-Specialist system."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from agent.supervisor_specialist.schemas import CaseState, GraphState, TimeWindow

_DEFAULT_LOOKBACK_DAYS = 30


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
    ) -> None:
        self._llm = llm
        self._max_steps = max_steps
        self._ref = _resolve_reference_date(reference_date)

        artifact_store = ArtifactStore()
        event_stream = EventStream(quiet=quiet)
        behavior_log = BehaviorLog(log_dir=log_dir)
        mcp_tools = MCPToolClient(server_paths=server_paths or DEFAULT_SERVER_PATHS)

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

        self._graph = build_graph(deps)

    async def run(self, question: str) -> str:
        case_state = self._init_case_state(question)
        initial_state: GraphState = {
            "case_state": case_state,
            "current_task": None,
            "last_artifacts": [],
            "final_response": None,
            "next_node": "supervisor",
            "step_count": 0,
            "max_steps": self._max_steps,
            "error_message": None,
        }
        result = await self._graph.ainvoke(initial_state)
        return result.get("final_response") or "(no response generated)"

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
