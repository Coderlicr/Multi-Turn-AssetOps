"""ReAct sequencing, result feedback, and artifact production."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.schemas import (
    ArtifactEnvelope,
    MCPToolResult,
    TaskEnvelope,
    TimeWindow,
    ToolCallResult,
)

from ..parallel_support import _csv_path, DoneLLM, MultiAssetMCPToolClient
from ..specialist_support import _make_task, _make_specialist

pytestmark = pytest.mark.usefixtures("existing_csv_inputs")


@pytest.mark.anyio
async def test_react_tools_executed_in_order():
    """ReAct loop: LLM calls two tools in order then stops; execution order must match."""
    specialist, artifact_store, mock_mcp = _make_specialist()

    # LLM responses (in order):
    # step 1 → call iot.assets
    # step 2 → call iot.sensors
    # step 3 → done
    # step 4 → artifact generation
    llm_responses = [
        '{"tool_name": "iot.assets", "args": {"site_name": "MAIN"}}',
        '{"tool_name": "iot.sensors", "args": {"site_name": "MAIN", "asset_id": "Chiller 6"}}',
        '{"done": true}',
        """{
            "artifacts": [{
                "artifact_type": "dataset_ref",
                "asset_ids": ["Chiller 6"],
                "time_window": {},
                "source_artifacts": [],
                "payload": {"summary": "collected"},
                "open_questions": []
            }]
        }""",
    ]

    call_order: list[str] = []

    async def mock_mcp_call(tool_name, args):
        call_order.append(tool_name)
        return MCPToolResult(status="ok", result=f"result of {tool_name}")

    mock_mcp.get_allowed_tool_schemas = AsyncMock(return_value=[])
    mock_mcp.call = AsyncMock(side_effect=mock_mcp_call)

    with patch(
        "agent.supervisor_specialist.agents.base.call_llm",
        new_callable=AsyncMock,
        side_effect=llm_responses,
    ):
        result = await specialist.run(_make_task())
        artifacts = result.artifacts

    assert call_order == ["iot.assets", "iot.sensors"]
    assert len(artifacts) == 1


@pytest.mark.anyio
async def test_artifact_id_assigned_by_runtime_not_llm():
    """LLM output (ArtifactDraft) must not contain artifact_id; runtime assigns it."""
    specialist, artifact_store, mock_mcp = _make_specialist()

    llm_responses = [
        '{"done": true}',  # no tool calls needed
        """{
            "artifacts": [{
                "artifact_type": "dataset_ref",
                "asset_ids": ["Chiller 6"],
                "time_window": {},
                "source_artifacts": [],
                "payload": {"note": "no tools called"},
                "open_questions": []
            }]
        }""",
    ]

    mock_mcp.get_allowed_tool_schemas = AsyncMock(return_value=[])
    mock_mcp.call = AsyncMock()

    with patch(
        "agent.supervisor_specialist.agents.base.call_llm",
        new_callable=AsyncMock,
        side_effect=llm_responses,
    ):
        result = await specialist.run(_make_task())
        artifacts = result.artifacts

    assert len(artifacts) == 1
    assert artifacts[0].artifact_id == "artifact_dc_001"  # runtime-assigned, not from LLM
    assert artifacts[0].producer == "data_collection_specialist"
    assert artifacts[0].case_id == "case_proto_001"


@pytest.mark.anyio
async def test_artifact_draft_wrapped_to_envelope():
    """ArtifactDraft from LLM must be wrapped into a full ArtifactEnvelope."""
    specialist, artifact_store, mock_mcp = _make_specialist()

    llm_responses = [
        '{"tool_name": "iot.assets", "args": {"site_name": "MAIN"}}',
        '{"done": true}',
        """{
            "artifacts": [{
                "artifact_type": "inventory",
                "asset_ids": ["Chiller 6", "Chiller 9"],
                "time_window": {"start": "2020-05-01T00:00:00"},
                "source_artifacts": [],
                "payload": {"assets": ["Chiller 6", "Chiller 9"]},
                "open_questions": ["Are there other chillers?"]
            }]
        }""",
    ]

    mock_mcp.get_allowed_tool_schemas = AsyncMock(return_value=[])
    mock_mcp.call = AsyncMock(
        return_value=MCPToolResult(
            status="ok", result='{"assets": ["Chiller 6", "Chiller 9"]}'
        )
    )

    with patch(
        "agent.supervisor_specialist.agents.base.call_llm",
        new_callable=AsyncMock,
        side_effect=llm_responses,
    ):
        result = await specialist.run(_make_task())
        artifacts = result.artifacts

    assert len(artifacts) == 1
    env = artifacts[0]
    assert env.artifact_id.startswith("artifact_dc_")
    assert env.case_id == "case_proto_001"
    assert env.artifact_type == "inventory"
    assert env.source_tools == ["iot.assets"]
    assert "Are there other chillers?" in env.open_questions


@pytest.mark.anyio
async def test_react_loop_uses_prior_result_for_next_args():
    """Key ReAct property: LLM receives prior tool result before deciding next tool.

    Simulates the csv_path passing scenario:
      step 1: iot.history_csv → returns a csv_path in result
      step 2: LLM sees csv_path → calls utilities.csv_stats with the correct path
    """
    specialist, artifact_store, mock_mcp = _make_specialist()

    actual_csv_path = "/tmp/assetops/Chiller_6_20200501_20200601_history.csv"

    llm_step1 = '{"tool_name": "iot.history_csv", "args": {"site_name": "MAIN", "asset_id": "Chiller 6", "start": "2020-05-01T00:00:00", "final": "2020-06-01T00:00:00"}}'

    # Step 2: LLM should use the actual csv_path from step 1 result
    captured_prompts: list[str] = []

    async def fake_call_llm(llm, prompt, temperature=0.0):
        captured_prompts.append(prompt)
        idx = len(captured_prompts) - 1
        if idx == 0:
            return llm_step1
        if idx == 1:
            # At this point the prompt must contain the actual csv_path
            return f'{{"tool_name": "utilities.csv_stats", "args": {{"csv_path": "{actual_csv_path}", "columns": null}}}}'
        if idx == 2:
            return '{"done": true}'
        # Artifact generation
        return """{
            "artifacts": [{
                "artifact_type": "dataset_ref",
                "asset_ids": ["Chiller 6"],
                "time_window": {},
                "source_artifacts": [],
                "payload": {"csv_path": "/tmp/assetops/Chiller_6_20200501_20200601_history.csv"},
                "open_questions": []
            }]
        }"""

    mock_mcp.get_allowed_tool_schemas = AsyncMock(return_value=[])
    mock_mcp.call = AsyncMock(
        side_effect=[
            MCPToolResult(
                status="ok",
                result=f'{{"csv_path": "{actual_csv_path}", "total_observations": 100, "message": "Wrote 100 obs to {actual_csv_path}."}}',
            ),
            MCPToolResult(status="ok", result='{"mean": 0.55, "std": 0.03}'),
        ]
    )

    with patch("agent.supervisor_specialist.agents.base.call_llm", side_effect=fake_call_llm):
        result = await specialist.run(_make_task())
        artifacts = result.artifacts

    # The second LLM prompt must contain the actual csv_path from step 1
    assert actual_csv_path in captured_prompts[1], (
        "Step 2 prompt does not contain the csv_path from step 1. "
        "ReAct loop is not passing prior results correctly."
    )
    assert len(artifacts) == 1


@pytest.mark.parametrize("parallel", [False, True])
def test_dataset_paths_normalized_in_both_execution_modes(tmp_path, parallel):
    specialist = DataCollectionSpecialist(
        llm=DoneLLM(), mcp_tools=MultiAssetMCPToolClient(), artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path), event_stream=EventStream(quiet=True),
        enable_parallel=parallel,
    )
    task = TaskEnvelope(
        case_id="case_dataset", task_type="collect", goal="Collect data", site="MAIN",
        asset_ids=["Chiller 6"], time_window=TimeWindow(), focus_metrics=[], input_artifacts=[],
    )
    artifact = ArtifactEnvelope(
        artifact_id="artifact_dc_001", case_id=task.case_id, producer=specialist.role,
        artifact_type="dataset_ref", asset_ids=task.asset_ids, time_window=TimeWindow(),
        source_tools=[], source_artifacts=[], payload={},
    )
    results = [ToolCallResult(order=1, tool_name="iot.history_csv", args={"asset_id": "Chiller 6"}, status="ok", result=json.dumps({"csv_path": _csv_path(6)}))]
    normalized = specialist._postprocess_artifacts(task, [], results, [artifact])
    assert normalized[0].payload["csv_path"] == _csv_path(6)
    assert normalized[0].payload == {"csv_path": _csv_path(6)}
