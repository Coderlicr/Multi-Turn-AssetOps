"""Parallel tool execution and ordered result aggregation."""

from __future__ import annotations

import json
import time

import pytest

from agent.supervisor_specialist.agents.time_series_analysis import TimeSeriesAnalysisSpecialist
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.schemas import (
    TaskEnvelope,
    TimeWindow,
    ToolCallRequest,
)

from ..parallel_support import (
    _csv_path,
    ParallelMCPToolClient,
    BatchLLM,
    BatchMCPToolClient,
)

pytestmark = pytest.mark.usefixtures("existing_csv_inputs")


@pytest.mark.anyio
async def test_mcp_call_many_parallel_preserves_order_and_runs_concurrently():
    client = ParallelMCPToolClient(delay=0.05)
    calls = [
        ToolCallRequest(tool_name="tsfm.run_integrated_tsad", args={"dataset_path": f"/tmp/{i}.csv"})
        for i in range(4)
    ]

    started = time.perf_counter()
    results = await client.call_many_parallel(calls, max_concurrency=4)
    elapsed = time.perf_counter() - started

    assert [json.loads(result.result)["dataset_path"] for result in results] == [
        "/tmp/0.csv",
        "/tmp/1.csv",
        "/tmp/2.csv",
        "/tmp/3.csv",
    ]
    assert client.max_active == 4
    assert elapsed < 0.18


@pytest.mark.anyio
async def test_specialist_executes_parallel_batch_and_logs_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_SPECIALIST_PARALLELISM", "4")
    llm = BatchLLM()
    mcp_tools = BatchMCPToolClient(delay=0.05)
    specialist = TimeSeriesAnalysisSpecialist(
        llm=llm,
        mcp_tools=mcp_tools,
        artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path),
        event_stream=EventStream(quiet=True),
        enable_parallel=True,
    )
    task = TaskEnvelope(
        case_id="case_parallel",
        task_type="time_series_analysis",
        goal="Analyze four chiller CSV files with TSFM.",
        site="MAIN",
        asset_ids=["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"],
        time_window=TimeWindow(start="2020-06-01T00:00:00", end="2020-07-01T00:00:00"),
        focus_metrics=["temperature"],
        input_artifacts=[],
        constraints={"turn_id": "turn_001"},
    )

    started = time.perf_counter()
    result = await specialist.run(task)
    elapsed = time.perf_counter() - started

    assert mcp_tools.max_active == 4
    assert elapsed < 0.30
    assert [call[1]["dataset_path"] for call in mcp_tools.calls] == [
        _csv_path(3),
        _csv_path(4),
        _csv_path(6),
        _csv_path(9),
    ]
    assert len(result.tool_calls) == 4
    group_ids = {call.parallel_group_id for call in result.tool_calls}
    assert len(group_ids) == 1
    assert None not in group_ids
    assert [call.parallel_index for call in result.tool_calls] == [1, 2, 3, 4]
    assert [call.parallel_size for call in result.tool_calls] == [4, 4, 4, 4]
    assert [call.status for call in result.tool_calls] == ["ok", "failed", "ok", "ok"]
    assert result.artifacts[0].payload["aggregate_summary"] == "Compared four chiller anomaly results."
    assert "parallel_group=" in llm.artifact_prompt

    records = [
        json.loads(line)
        for line in (tmp_path / "case_parallel.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["turn_id"] == "turn_001"
    assert [call["parallel_index"] for call in records[0]["tool_calls"]] == [1, 2, 3, 4]
    assert [call["parallel_size"] for call in records[0]["tool_calls"]] == [4, 4, 4, 4]
    assert {call["parallel_group_id"] for call in records[0]["tool_calls"]} == group_ids
