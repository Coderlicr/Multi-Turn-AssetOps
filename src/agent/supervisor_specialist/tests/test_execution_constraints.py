"""Tool permissions, file arguments, call budgets, batch deduplication, and concurrency limits."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.supervisor_specialist.agents.time_series_analysis import TimeSeriesAnalysisSpecialist
from agent.supervisor_specialist.agents.supervisor import SupervisorAgent
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.runtime.mcp_tools import MCPToolClient
from agent.supervisor_specialist.schemas import (
    MCPToolResult,
    TaskEnvelope,
    TimeWindow,
    CaseState,
    GraphState,
)

from .parallel_support import (
    _csv_path,
    BatchLLM,
    BatchMCPToolClient,
    _scripted_execution,
)
from .specialist_support import _make_task, _make_specialist

pytestmark = pytest.mark.usefixtures("existing_csv_inputs")


def _make_state(step_count: int, max_steps: int) -> GraphState:
    return {
        "case_state": CaseState(
            case_id="case_max_steps",
            user_goal="test",
            site="MAIN",
            asset_ids=[],
            time_window=TimeWindow(),
            focus_metrics=[],
            status="collecting_data",
        ),
        "current_task": None,
        "last_artifacts": [],
        "final_response": None,
        "next_node": "supervisor",
        "step_count": step_count,
        "max_steps": max_steps,
        "error_message": None,
    }


@pytest.mark.anyio
async def test_max_steps_triggers_respond_to_user():
    """When step_count > max_steps, Supervisor must go to respond_to_user."""
    mock_llm = MagicMock()
    artifact_store = ArtifactStore()
    event_stream = EventStream(quiet=True)
    behavior_log = MagicMock()
    behavior_log.write = MagicMock()

    supervisor = SupervisorAgent(
        llm=mock_llm,
        artifact_store=artifact_store,
        event_stream=event_stream,
        behavior_log=behavior_log,
    )

    # step_count=12, max_steps=12 → next step would be 13 > 12
    state = _make_state(step_count=12, max_steps=12)
    result = await supervisor.decide(state)

    assert result["next_node"] == "respond_to_user"
    assert result["current_task"] is None
    assert "Maximum" in (result.get("error_message") or "")
    assert result["case_state"].status == "waiting_for_user"


@pytest.mark.anyio
async def test_max_steps_not_triggered_when_under_limit():
    """Under max_steps, Supervisor should proceed normally via LLM."""
    mock_llm = MagicMock()
    artifact_store = ArtifactStore()
    event_stream = EventStream(quiet=True)
    behavior_log = MagicMock()
    behavior_log.write = MagicMock()

    supervisor = SupervisorAgent(
        llm=mock_llm,
        artifact_store=artifact_store,
        event_stream=event_stream,
        behavior_log=behavior_log,
    )

    decision_json = """{
      "next_node": "respond_to_user",
      "next_task": null,
      "case_status": "completed",
      "next_step": "done"
    }"""

    with patch(
        "agent.supervisor_specialist.agents.supervisor.call_llm",
        new_callable=AsyncMock,
        return_value=decision_json,
    ):
        # step_count=5, max_steps=12 → step becomes 6, not exceeding 12
        state = _make_state(step_count=5, max_steps=12)
        result = await supervisor.decide(state)

    assert result["next_node"] == "respond_to_user"
    assert result.get("error_message") is None


@pytest.mark.anyio
async def test_unauthorized_tool_blocked_and_logged():
    """Unauthorized tools must be blocked (not executed) and logged as failed."""
    specialist, artifact_store, mock_mcp = _make_specialist()

    # LLM first requests an unauthorized tool, then an authorized one, then stops
    llm_responses = [
        '{"tool_name": "tsfm.run_integrated_tsad", "args": {}}',  # not in DC allowed_tools
        '{"tool_name": "iot.assets", "args": {"site_name": "MAIN"}}',
        '{"done": true}',
        """{
            "artifacts": [{
                "artifact_type": "dataset_ref",
                "asset_ids": ["Chiller 6"],
                "time_window": {},
                "source_artifacts": [],
                "payload": {"summary": "partial"},
                "open_questions": []
            }]
        }""",
    ]

    mock_mcp.get_allowed_tool_schemas = AsyncMock(return_value=[])
    mock_mcp.call = AsyncMock(return_value=MCPToolResult(status="ok", result="ok"))

    with patch(
        "agent.supervisor_specialist.agents.base.call_llm",
        new_callable=AsyncMock,
        side_effect=llm_responses,
    ):
        result = await specialist.run(_make_task())
        artifacts = result.artifacts

    # tsfm.run_integrated_tsad is not in DataCollectionSpecialist.allowed_tools →
    # MCPToolClient.call must NOT be called for it
    assert mock_mcp.call.call_count == 1  # only iot.assets was actually called

    # Behavior log must contain the blocked tool as failed
    log_call = specialist.logger.write.call_args
    tool_calls = log_call.kwargs["tool_calls"]
    failed = [tc for tc in tool_calls if tc.status == "failed"]
    assert len(failed) == 1
    assert failed[0].tool_name == "tsfm.run_integrated_tsad"


@pytest.mark.anyio
async def test_react_loop_stops_at_max_tool_calls():
    """ReAct loop must stop after MAX_TOOL_CALLS even if LLM never outputs done=true."""
    from agent.supervisor_specialist.agents import base as base_mod

    specialist, artifact_store, mock_mcp = _make_specialist()

    # LLM always requests another tool — should stop at the limit
    always_call = '{"tool_name": "iot.assets", "args": {"site_name": "MAIN"}}'
    artifact_response = """{
        "artifacts": [{
            "artifact_type": "dataset_ref",
            "asset_ids": [],
            "time_window": {},
            "source_artifacts": [],
            "payload": {"note": "stopped at limit"},
            "open_questions": []
        }]
    }"""

    call_count = [0]

    async def fake_call_llm(llm, prompt, temperature=0.0):
        call_count[0] += 1
        # After max tool calls, the loop should stop and call artifact LLM
        if call_count[0] > base_mod._MAX_TOOL_CALLS_PER_SPECIALIST:
            return artifact_response
        return always_call

    mock_mcp.get_allowed_tool_schemas = AsyncMock(return_value=[])
    mock_mcp.call = AsyncMock(return_value=MCPToolResult(status="ok", result="{}"))

    with patch("agent.supervisor_specialist.agents.base.call_llm", side_effect=fake_call_llm):
        result = await specialist.run(_make_task())
        artifacts = result.artifacts

    assert mock_mcp.call.call_count == base_mod._MAX_TOOL_CALLS_PER_SPECIALIST
    assert len(artifacts) == 1


@pytest.mark.anyio
async def test_parallel_batch_validates_each_file_argument(tmp_path):
    class InvalidBatchLLM(BatchLLM):
        def generate(self, prompt, temperature=0.0):
            response = json.loads(super().generate(prompt, temperature))
            if "tool_calls" in response:
                response["tool_calls"][1]["args"]["dataset_path"] = "artifact_dc_001"
            return json.dumps(response)

    mcp = BatchMCPToolClient(delay=0)
    specialist = TimeSeriesAnalysisSpecialist(
        llm=InvalidBatchLLM(), mcp_tools=mcp, artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path), event_stream=EventStream(quiet=True),
        enable_parallel=True,
    )
    task = TaskEnvelope(
        case_id="case_guard", task_type="anomaly_detection", goal="Analyze CSVs",
        site="MAIN", asset_ids=[], time_window=TimeWindow(), focus_metrics=[], input_artifacts=[],
    )
    result = await specialist.run(task)
    assert len(mcp.calls) == 3
    assert result.tool_calls[1].status == "failed"
    assert "artifact ID" in result.tool_calls[1].error
    assert [r.parallel_index for r in result.tool_calls] == [1, 2, 3, 4]


@pytest.mark.anyio
async def test_parallel_disabled_runs_only_one_tool_call_from_batch(tmp_path):
    llm = BatchLLM()
    mcp_tools = BatchMCPToolClient(delay=0.01)
    specialist = TimeSeriesAnalysisSpecialist(
        llm=llm,
        mcp_tools=mcp_tools,
        artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path),
        event_stream=EventStream(quiet=True),
    )
    task = TaskEnvelope(
        case_id="case_parallel_disabled",
        task_type="time_series_analysis",
        goal="Analyze four chiller CSV files with TSFM.",
        site="MAIN",
        asset_ids=["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"],
        time_window=TimeWindow(start="2020-06-01T00:00:00", end="2020-07-01T00:00:00"),
        focus_metrics=["temperature"],
        input_artifacts=[],
    )

    result = await specialist.run(task)

    assert [call[1]["dataset_path"] for call in mcp_tools.calls] == [_csv_path(3)]
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].parallel_group_id is None


@pytest.mark.anyio
async def test_parallel_batch_deduplicates_only_identical_requests_within_that_batch(tmp_path):
    request = {"tool_name": "iot.sensors", "args": {"site_name": "MAIN", "asset_id": "Chiller 6"}}
    other_asset = {"tool_name": "iot.sensors", "args": {"site_name": "MAIN", "asset_id": "Chiller 9"}}
    clock_calls = [
        {"tool_name": name, "args": {}}
        for name in ("utilities.current_date_time", "utilities.current_time_english")
    ]
    mcp = BatchMCPToolClient(delay=0)
    specialist, task = _scripted_execution(tmp_path, [
        {"tool_calls": [
            request,
            {"tool_name": "iot.sensors", "args": {"asset_id": "Chiller 6", "site_name": "MAIN"}},
            other_asset,
            *clock_calls,
        ]},
        request,
        {"done": True},
    ], mcp)

    result = await specialist.run(task)

    # Argument key order does not create a distinct request. Different arguments
    # or tool names do, and an explicit repeat in the next step still executes.
    expected = [request, other_asset, *clock_calls, request]
    assert mcp.calls == [(call["tool_name"], call["args"]) for call in expected]
    assert [(call.tool_name, call.args) for call in result.tool_calls] == mcp.calls
    assert [call.order for call in result.tool_calls] == list(range(1, 6))
    assert all(call.status == "ok" for call in result.tool_calls)
    assert specialist.llm.react_count == 3


@pytest.mark.anyio
@pytest.mark.parametrize("prior_calls", [0, 17], ids=["oversized-first-batch", "remaining-budget"])
async def test_parallel_batch_is_truncated_to_remaining_tool_call_budget(tmp_path, prior_calls):
    requests = [
        {"tool_name": "iot.assets", "args": {"site_name": f"SITE_{index}"}}
        for index in range(25)
    ]
    decisions = ([{"tool_calls": requests[:prior_calls]}] if prior_calls else [])
    decisions.append({"tool_calls": requests[prior_calls:]})
    mcp = BatchMCPToolClient(delay=0)
    specialist, task = _scripted_execution(tmp_path, decisions, mcp)

    result = await specialist.run(task)

    assert mcp.calls == [(call["tool_name"], call["args"]) for call in requests[:20]]
    assert len(result.tool_calls) == 20
    assert [call.order for call in result.tool_calls] == list(range(1, 21))
    assert result.tool_calls[-1].parallel_size == 20 - prior_calls
    # Exhausting the budget proceeds directly to artifact generation, without
    # asking the LLM for another tool decision.
    assert specialist.llm.react_count == (2 if prior_calls else 1)
    assert specialist.llm.artifact_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize("native_batch", [False, True], ids=["specialist-semaphore", "mcp-semaphore"])
async def test_parallel_calls_above_concurrency_limit_wait_and_all_complete(
    tmp_path, monkeypatch, native_batch,
):
    monkeypatch.setenv("SUPERVISOR_SPECIALIST_PARALLELISM", "2")
    release = asyncio.Event()
    full = asyncio.Event()

    class GatedMCP(BatchMCPToolClient):
        async def call(self, tool_name, args):
            self.calls.append((tool_name, args))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active == 2:
                full.set()
            try:
                await release.wait()
                return MCPToolResult(status="ok", result=json.dumps(args))
            finally:
                self.active -= 1

    class NativeBatchMCP(GatedMCP):
        call_many_parallel = MCPToolClient.call_many_parallel

    mcp = NativeBatchMCP(delay=0) if native_batch else GatedMCP(delay=0)
    requests = [
        {"tool_name": "iot.assets", "args": {"site_name": f"SITE_{index}"}}
        for index in range(7)
    ]
    specialist, task = _scripted_execution(
        tmp_path, [{"tool_calls": requests}, {"done": True}], mcp,
    )
    running = asyncio.create_task(specialist.run(task))
    try:
        await asyncio.wait_for(full.wait(), timeout=5)
        # Keep the first two calls blocked while checking that the other five
        # have not started. No elapsed-time threshold is needed for this check.
        assert mcp.active == 2
        assert len(mcp.calls) == 2
        release.set()
        result = await asyncio.wait_for(running, timeout=5)
    finally:
        release.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)

    assert mcp.max_active == 2
    assert mcp.active == 0
    assert len(mcp.calls) == 7
    assert [call.args for call in result.tool_calls] == [call["args"] for call in requests]
    assert all(call.status == "ok" for call in result.tool_calls)
