"""Tests for LangGraph routing logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.schemas import (
    ArtifactEnvelope,
    CaseState,
    GraphState,
    SpecialistResult,
    TaskEnvelope,
    TimeWindow,
)


def _make_case_state(status="collecting_data") -> CaseState:
    return CaseState(
        case_id="case_test_001",
        user_goal="Check Chiller 6 temperature",
        site="MAIN",
        asset_ids=[],
        time_window=TimeWindow(),
        focus_metrics=[],
        status=status,
    )


def _make_initial_state(case_state: CaseState) -> GraphState:
    return {
        "case_state": case_state,
        "current_task": None,
        "last_artifacts": [],
        "final_response": None,
        "next_node": "supervisor",
        "step_count": 0,
        "max_steps": 12,
        "error_message": None,
    }


@pytest.mark.anyio
async def test_supervisor_routes_to_data_collection():
    """Supervisor should set next_node=data_collection_specialist on first step."""
    from agent.supervisor_specialist.agents.supervisor import SupervisorAgent

    mock_llm = MagicMock()
    artifact_store = ArtifactStore()
    event_stream = EventStream(quiet=True)
    behavior_log = MagicMock()
    behavior_log.write = MagicMock()

    decision_json = """{
      "next_node": "data_collection_specialist",
      "next_task": {
        "case_id": "case_test_001",
        "task_type": "collect_sensor_data",
        "goal": "Collect Chiller 6 sensor data",
        "site": "MAIN",
        "asset_ids": ["Chiller 6"],
        "time_window": {},
        "focus_metrics": [],
        "input_artifacts": [],
        "constraints": {}
      },
      "case_status": "collecting_data",
      "next_step": "Collecting IoT data for Chiller 6"
    }"""

    with patch(
        "agent.supervisor_specialist.agents.supervisor.call_llm",
        new_callable=AsyncMock,
        return_value=decision_json,
    ):
        supervisor = SupervisorAgent(
            llm=mock_llm,
            artifact_store=artifact_store,
            event_stream=event_stream,
            behavior_log=behavior_log,
        )
        case_state = _make_case_state()
        state = _make_initial_state(case_state)
        result = await supervisor.decide(state)

    assert result["next_node"] == "data_collection_specialist"
    assert result["current_task"] is not None
    assert result["current_task"].case_id == "case_test_001"
    assert result["step_count"] == 1


@pytest.mark.anyio
async def test_supervisor_routes_to_respond_to_user():
    """Supervisor should route to respond_to_user when work is done."""
    from agent.supervisor_specialist.agents.supervisor import SupervisorAgent

    mock_llm = MagicMock()
    artifact_store = ArtifactStore()
    event_stream = EventStream(quiet=True)
    behavior_log = MagicMock()
    behavior_log.write = MagicMock()

    decision_json = """{
      "next_node": "respond_to_user",
      "next_task": null,
      "case_status": "completed",
      "next_step": "Generating final answer"
    }"""

    with patch(
        "agent.supervisor_specialist.agents.supervisor.call_llm",
        new_callable=AsyncMock,
        return_value=decision_json,
    ):
        supervisor = SupervisorAgent(
            llm=mock_llm,
            artifact_store=artifact_store,
            event_stream=event_stream,
            behavior_log=behavior_log,
        )
        case_state = _make_case_state()
        state = _make_initial_state(case_state)
        result = await supervisor.decide(state)

    assert result["next_node"] == "respond_to_user"
    assert result["current_task"] is None


@pytest.mark.anyio
async def test_specialist_returns_to_supervisor():
    """Run the compiled graph and inspect the supervisor's second invocation."""
    from agent.supervisor_specialist.graph import Dependencies, build_graph

    artifact_store = ArtifactStore()
    artifact = ArtifactEnvelope(
        artifact_id="artifact_dc_001",
        case_id="case_test_001",
        producer="data_collection_specialist",
        artifact_type="dataset_ref",
        asset_ids=["Chiller 6"],
        time_window=TimeWindow(),
        source_tools=["iot.assets"],
        source_artifacts=[],
        payload={"summary": "data collected"},
    )
    task = TaskEnvelope(
        case_id="case_test_001",
        task_type="collect",
        goal="collect data",
        site="MAIN",
        asset_ids=["Chiller 6"],
        time_window=TimeWindow(),
        focus_metrics=[],
        input_artifacts=[],
    )
    visits = []

    async def decide(state):
        visits.append(state)
        if len(visits) == 1:
            return {**state, "next_node": "data_collection_specialist", "current_task": task}
        return {**state, "next_node": "respond_to_user", "current_task": None}

    supervisor = MagicMock()
    supervisor.decide = AsyncMock(side_effect=decide)
    specialist = MagicMock(role="data_collection_specialist")
    specialist.run = AsyncMock(return_value=SpecialistResult(artifacts=[artifact]))
    other_specialists = []
    for role in ("time_series_analysis_specialist", "failure_reasoning_specialist",
                 "maintenance_planning_specialist"):
        other = MagicMock(role=role)
        other.run = AsyncMock()
        other_specialists.append(other)
    deps = Dependencies(
        supervisor=supervisor,
        data_collection=specialist,
        time_series_analysis=other_specialists[0],
        failure_reasoning=other_specialists[1],
        maintenance_planning=other_specialists[2],
        artifact_store=artifact_store,
        event_stream=EventStream(quiet=True),
        behavior_log=MagicMock(),
        llm=MagicMock(),
    )
    graph = build_graph(deps)
    with patch("agent.supervisor_specialist.graph.call_llm", new_callable=AsyncMock,
               return_value="Here is the inventory."):
        result = await graph.ainvoke(_make_initial_state(_make_case_state()))

    assert len(visits) == 2
    returned = visits[1]
    assert returned["next_node"] == "supervisor"
    assert returned["current_task"] is None
    assert returned["error_message"] is None
    assert returned["last_artifacts"] == [artifact]
    assert returned["turn_artifact_ids"] == ["artifact_dc_001"]
    assert artifact_store.get("artifact_dc_001") == artifact
    specialist.run.assert_awaited_once()
    dispatched_task = specialist.run.await_args.args[0]
    assert dispatched_task.goal == task.goal
    assert dispatched_task.constraints["turn_id"] == "turn_001"
    for other in other_specialists:
        other.run.assert_not_awaited()
    assert result["final_response"] == "Here is the inventory."
