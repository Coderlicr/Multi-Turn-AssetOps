from __future__ import annotations

import asyncio
import json
import time

import pytest

from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.agents.time_series_analysis import TimeSeriesAnalysisSpecialist
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.runtime.mcp_tools import MCPToolClient
from agent.supervisor_specialist.schemas import (
    ArtifactEnvelope,
    MCPToolResult,
    TaskEnvelope,
    TimeWindow,
    ToolCallRequest,
)


class ParallelMCPToolClient(MCPToolClient):
    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool_name: str, args: dict) -> MCPToolResult:
        self.calls.append((tool_name, args))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            return MCPToolResult(
                status="ok",
                result=json.dumps({"tool": tool_name, "dataset_path": args.get("dataset_path")}),
            )
        finally:
            self.active -= 1


class BatchLLM:
    def __init__(self) -> None:
        self.react_count = 0
        self.artifact_prompt = ""

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        del temperature
        if "Decide the NEXT action." in prompt:
            self.react_count += 1
            if self.react_count > 1:
                return json.dumps({"done": True})
            return json.dumps(
                {
                    "tool_calls": [
                        {
                            "tool_name": "tsfm.run_integrated_tsad",
                            "args": {
                                "dataset_path": f"/tmp/chiller_{asset}.csv",
                                "target_columns": ["supply_temp"],
                            },
                        }
                        for asset in [3, 4, 6, 9]
                    ]
                }
            )
        if "produce structured analysis artifacts" in prompt:
            self.artifact_prompt = prompt
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "artifact_type": "analysis_result",
                            "asset_ids": ["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"],
                            "time_window": {
                                "start": "2020-06-01T00:00:00",
                                "end": "2020-07-01T00:00:00",
                            },
                            "source_artifacts": [],
                            "payload": {
                                "aggregate_summary": "Compared four chiller anomaly results.",
                                "per_asset": {
                                    "Chiller 3": {"status": "ok"},
                                    "Chiller 4": {"status": "failed"},
                                    "Chiller 6": {"status": "ok"},
                                    "Chiller 9": {"status": "ok"},
                                },
                            },
                            "open_questions": [],
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")


class DuplicateRetryLLM:
    def __init__(self) -> None:
        self.react_count = 0
        self.artifact_prompt = ""

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        del temperature
        if "Decide the NEXT action." in prompt:
            self.react_count += 1
            assets = [3, 4, 6, 9] if self.react_count == 1 else [3, 6, 9]
            return json.dumps(
                {
                    "tool_calls": [
                        {
                            "tool_name": "tsfm.run_integrated_tsad",
                            "args": {
                                "dataset_path": f"/tmp/chiller_{asset}.csv",
                                "target_columns": ["supply_temp"],
                            },
                        }
                        for asset in assets
                    ]
                }
            )
        if "produce structured analysis artifacts" in prompt:
            self.artifact_prompt = prompt
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "artifact_type": "analysis_result",
                            "asset_ids": ["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"],
                            "time_window": {},
                            "source_artifacts": [],
                            "payload": {"aggregate_summary": "Done."},
                            "open_questions": [],
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")


class DataCoverageLLM:
    def __init__(self) -> None:
        self.react_count = 0

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        del temperature
        if "Decide the NEXT action." in prompt:
            self.react_count += 1
            if self.react_count > 1:
                return json.dumps({"done": True})
            return json.dumps(
                {
                    "tool_calls": [
                        {"tool_name": "iot.assets", "args": {"site_name": "MAIN"}},
                        {
                            "tool_name": "iot.history_csv",
                            "args": {
                                "site_name": "MAIN",
                                "asset_id": "Chiller 6",
                                "start": "2020-05-21T00:00:00",
                                "final": "2020-06-20T00:00:00",
                            },
                        },
                    ]
                }
            )
        if "produce structured analysis artifacts" in prompt:
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "artifact_type": "dataset_ref",
                            "asset_ids": ["Chiller 6"],
                            "time_window": {},
                            "source_artifacts": [],
                            "payload": {
                                "csv_path": "/tmp/assetops/Chiller_6_20200521T000000_20200620T000000_history.csv"
                            },
                            "open_questions": [],
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")


class DoneLLM:
    def __init__(self) -> None:
        self.artifact_prompt = ""

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        del temperature
        if "Decide the NEXT action." in prompt:
            return json.dumps({"done": True})
        if "produce structured analysis artifacts" in prompt:
            self.artifact_prompt = prompt
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "artifact_type": "analysis_result",
                            "asset_ids": ["Chiller 6"],
                            "time_window": {},
                            "source_artifacts": ["artifact_dc_001"],
                            "payload": {"note": "LLM only mentioned Chiller 6."},
                            "open_questions": [],
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")


class BatchMCPToolClient:
    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.calls: list[tuple[str, dict]] = []

    async def get_allowed_tool_schemas(self, allowed_tools: set[str]) -> list[dict]:
        return [
            {
                "name": name,
                "description": f"fake {name}",
                "input_schema": {"type": "object", "properties": {}},
            }
            for name in sorted(allowed_tools)
        ]

    async def call(self, tool_name: str, args: dict) -> MCPToolResult:
        self.calls.append((tool_name, args))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            if args.get("dataset_path") == "/tmp/chiller_4.csv":
                return MCPToolResult(status="failed", error="synthetic TSFM failure")
            return MCPToolResult(
                status="ok",
                result=json.dumps(
                    {
                        "tool": tool_name,
                        "dataset_path": args.get("dataset_path"),
                        "anomaly_count": 2,
                    }
                ),
            )
        finally:
            self.active -= 1


class CoverageMCPToolClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get_allowed_tool_schemas(self, allowed_tools: set[str]) -> list[dict]:
        return [
            {
                "name": name,
                "description": f"fake {name}",
                "input_schema": {"type": "object", "properties": {}},
            }
            for name in sorted(allowed_tools)
        ]

    async def call(self, tool_name: str, args: dict) -> MCPToolResult:
        self.calls.append((tool_name, args))
        if tool_name == "iot.assets":
            return MCPToolResult(
                status="ok",
                result=json.dumps(
                    {
                        "site_name": "MAIN",
                        "assets": ["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"],
                    }
                ),
            )
        if tool_name == "iot.history_csv":
            asset = args["asset_id"]
            stem = asset.replace(" ", "_")
            return MCPToolResult(
                status="ok",
                result=json.dumps(
                    {
                        "site_name": args["site_name"],
                        "asset_id": asset,
                        "start": args["start"],
                        "final": args["final"],
                        "columns": [
                            "timestamp",
                            "asset_id",
                            f"{asset} Return Temperature",
                            f"{asset} Supply Temperature",
                        ],
                        "csv_path": f"/tmp/assetops/{stem}_20200521T000000_20200620T000000_history.csv",
                        "total_observations": 100,
                    }
                ),
            )
        if tool_name == "utilities.csv_stats":
            asset = args["csv_path"].split("/")[-1].split("_2020")[0].replace("_", " ")
            return MCPToolResult(
                status="ok",
                result=json.dumps(
                    {
                        "csv_path": args["csv_path"],
                        "all_columns": [
                            "timestamp",
                            "asset_id",
                            f"{asset} Return Temperature",
                            f"{asset} Supply Temperature",
                            f"{asset} Setpoint Temperature",
                        ],
                        "stats": {},
                    }
                ),
            )
        if tool_name == "tsfm.run_integrated_tsad":
            return MCPToolResult(
                status="ok",
                result=json.dumps(
                    {
                        "status": "success",
                        "results_file": args["dataset_path"].replace("_history.csv", "_tsad.csv"),
                        "anomaly_count": 3,
                        "total_records": 200,
                    }
                ),
            )
        return MCPToolResult(status="failed", error=f"Unexpected tool: {tool_name}")


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
        "/tmp/chiller_3.csv",
        "/tmp/chiller_4.csv",
        "/tmp/chiller_6.csv",
        "/tmp/chiller_9.csv",
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


@pytest.mark.anyio
async def test_duplicate_successful_batch_members_are_skipped_not_logged_as_failures(tmp_path):
    llm = DuplicateRetryLLM()
    mcp_tools = BatchMCPToolClient(delay=0.01)
    specialist = TimeSeriesAnalysisSpecialist(
        llm=llm,
        mcp_tools=mcp_tools,
        artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path),
        event_stream=EventStream(quiet=True),
    )
    task = TaskEnvelope(
        case_id="case_duplicate_retry",
        task_type="time_series_analysis",
        goal="Analyze four chiller CSV files with TSFM.",
        site="MAIN",
        asset_ids=["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"],
        time_window=TimeWindow(),
        focus_metrics=["temperature"],
        input_artifacts=[],
        constraints={},
    )

    result = await specialist.run(task)

    assert llm.react_count == 2
    assert [call[1]["dataset_path"] for call in mcp_tools.calls] == [
        "/tmp/chiller_3.csv",
        "/tmp/chiller_4.csv",
        "/tmp/chiller_6.csv",
        "/tmp/chiller_9.csv",
    ]
    assert len(result.tool_calls) == 4
    assert [call.status for call in result.tool_calls] == ["ok", "failed", "ok", "ok"]
    assert "Duplicate successful tool call blocked" not in llm.artifact_prompt

    records = [
        json.loads(line)
        for line in (tmp_path / "case_duplicate_retry.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records[0]["tool_calls"]) == 4
    assert "Duplicate successful tool call blocked" not in json.dumps(records[0]["tool_calls"])


@pytest.mark.anyio
async def test_data_collection_completes_history_csv_for_all_discovered_assets(tmp_path):
    mcp_tools = CoverageMCPToolClient()
    specialist = DataCollectionSpecialist(
        llm=DataCoverageLLM(),
        mcp_tools=mcp_tools,
        artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path),
        event_stream=EventStream(quiet=True),
    )
    task = TaskEnvelope(
        case_id="case_data_coverage",
        task_type="collect_chiller_data",
        goal="Collect chiller data at MAIN.",
        site="MAIN",
        asset_ids=[],
        time_window=TimeWindow(start="2020-05-21T00:00:00", end="2020-06-20T00:00:00"),
        focus_metrics=["temperature"],
        input_artifacts=[],
    )

    result = await specialist.run(task)

    history_assets = [
        args["asset_id"]
        for tool_name, args in mcp_tools.calls
        if tool_name == "iot.history_csv"
    ]
    assert history_assets == ["Chiller 6", "Chiller 3", "Chiller 4", "Chiller 9"]
    dataset_artifact = result.artifacts[0]
    assert set(dataset_artifact.asset_ids) == {"Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"}
    assert set(dataset_artifact.payload["datasets_by_asset"]) == {
        "Chiller 3",
        "Chiller 4",
        "Chiller 6",
        "Chiller 9",
    }


@pytest.mark.anyio
async def test_time_series_completes_tsfm_for_all_dataset_artifact_csvs(tmp_path):
    artifact_store = ArtifactStore()
    artifact_store.save_many(
        [
            ArtifactEnvelope(
                artifact_id="artifact_dc_001",
                case_id="case_ts_coverage",
                producer="data_collection_specialist",
                artifact_type="dataset_ref",
                asset_ids=["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"],
                time_window=TimeWindow(
                    start="2020-05-21T00:00:00",
                    end="2020-06-20T00:00:00",
                ),
                source_tools=["iot.history_csv"],
                source_artifacts=[],
                payload={
                    "datasets_by_asset": {
                        asset: {
                            "csv_path": f"/tmp/assetops/{asset.replace(' ', '_')}_20200521T000000_20200620T000000_history.csv"
                        }
                        for asset in ["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"]
                    }
                },
                open_questions=[],
            )
        ]
    )
    mcp_tools = CoverageMCPToolClient()
    specialist = TimeSeriesAnalysisSpecialist(
        llm=DoneLLM(),
        mcp_tools=mcp_tools,
        artifact_store=artifact_store,
        behavior_log=BehaviorLog(log_dir=tmp_path),
        event_stream=EventStream(quiet=True),
    )
    task = TaskEnvelope(
        case_id="case_ts_coverage",
        task_type="anomaly_detection",
        goal="Analyze all chiller CSV files.",
        site="MAIN",
        asset_ids=["Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"],
        time_window=TimeWindow(start="2020-05-21T00:00:00", end="2020-06-20T00:00:00"),
        focus_metrics=["temperature"],
        input_artifacts=["artifact_dc_001"],
    )

    result = await specialist.run(task)

    tsfm_paths = [
        args["dataset_path"]
        for tool_name, args in mcp_tools.calls
        if tool_name == "tsfm.run_integrated_tsad"
    ]
    assert len(tsfm_paths) == 4
    assert all(f"Chiller_{n}" in " ".join(tsfm_paths) for n in [3, 4, 6, 9])
    analysis_artifact = result.artifacts[0]
    assert set(analysis_artifact.asset_ids) == {"Chiller 3", "Chiller 4", "Chiller 6", "Chiller 9"}
    assert set(analysis_artifact.payload["analysis_by_asset"]) == {
        "Chiller 3",
        "Chiller 4",
        "Chiller 6",
        "Chiller 9",
    }
