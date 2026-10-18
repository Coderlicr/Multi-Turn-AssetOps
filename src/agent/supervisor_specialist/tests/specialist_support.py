"""Factories for isolated ReAct specialist tests."""

from __future__ import annotations

from unittest.mock import MagicMock


from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.schemas import TaskEnvelope, TimeWindow


def _make_task() -> TaskEnvelope:
    return TaskEnvelope(
        case_id="case_proto_001",
        task_type="collect_sensor_data",
        goal="Collect Chiller 6 sensor data for analysis",
        site="MAIN",
        asset_ids=["Chiller 6"],
        time_window=TimeWindow(start="2020-05-01T00:00:00", end="2020-06-01T00:00:00"),
        focus_metrics=["Chiller Efficiency"],
        input_artifacts=[],
    )


def _make_specialist():
    mock_llm = MagicMock()
    artifact_store = ArtifactStore()
    behavior_log = MagicMock()
    behavior_log.write = MagicMock()
    event_stream = EventStream(quiet=True)
    mock_mcp = MagicMock()

    specialist = DataCollectionSpecialist(
        llm=mock_llm,
        mcp_tools=mock_mcp,
        artifact_store=artifact_store,
        behavior_log=behavior_log,
        event_stream=event_stream,
    )
    return specialist, artifact_store, mock_mcp
