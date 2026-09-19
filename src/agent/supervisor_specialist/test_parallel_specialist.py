from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
import sys

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
    ToolCallResult,
)


_CSV_ROOT = Path('/tmp')


def _csv_path(asset):
    return str(_CSV_ROOT / f'chiller_{asset}.csv')


@pytest.fixture(autouse=True)
def existing_csv_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], '_CSV_ROOT', tmp_path)
    for asset in (3, 4, 6, 9):
        (tmp_path / f'chiller_{asset}.csv').write_text('timestamp,supply_temp\n2020-06-01,50\n')


@pytest.mark.anyio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("execute_finetuning", [False, True])
async def test_finetuning_respects_done_and_normalizes_actual_results(
    tmp_path, parallel, execute_finetuning,
):
    class FinetuningLLM:
        steps = 0

        def generate(self, prompt, temperature=0.0):
            if "Decide the NEXT action." in prompt:
                self.steps += 1
                if self.steps == 1 and execute_finetuning:
                    return json.dumps({"tool_name": "tsfm.run_tsfm_finetuning", "args": {"dataset_path": _csv_path(6)}})
                return json.dumps({"done": True})
            return json.dumps({"artifacts": [{"artifact_type": "analysis_result", "asset_ids": ["Chiller 6"], "payload": {}}]})

    class FinetuningMCP(BatchMCPToolClient):
        async def call(self, tool_name, args):
            self.calls.append((tool_name, args))
            payload = {"model_checkpoint": "/tmp/trained_checkpoint", "results_file": "/tmp/metrics.csv"} if tool_name == "tsfm.run_tsfm_finetuning" else {"all_columns": []}
            return MCPToolResult(status="ok", result=json.dumps(payload))

    store = ArtifactStore()
    store.save_many([ArtifactEnvelope(
        artifact_id="artifact_dc_001", case_id="case_finetune", producer="data_collection_specialist",
        artifact_type="dataset_ref", asset_ids=["Chiller 6"], time_window=TimeWindow(),
        source_tools=[], source_artifacts=[], payload={"csv_path": _csv_path(6)},
    )])
    mcp = FinetuningMCP()
    specialist = TimeSeriesAnalysisSpecialist(
        llm=FinetuningLLM(), mcp_tools=mcp, artifact_store=store,
        behavior_log=BehaviorLog(log_dir=tmp_path), event_stream=EventStream(quiet=True),
        enable_parallel=parallel,
    )
    task = TaskEnvelope(
        case_id="case_finetune", task_type="fine_tuning", goal="Fine-tune the model",
        site="MAIN", asset_ids=["Chiller 6"], time_window=TimeWindow(),
        focus_metrics=[], input_artifacts=["artifact_dc_001"],
    )
    result = await specialist.run(task)
    assert specialist.llm.steps == (2 if execute_finetuning else 1)
    assert all(call.tool_name != "internal.done_guard" for call in result.tool_calls)
    finetuning_calls = [
        call for call in result.tool_calls
        if call.tool_name == "tsfm.run_tsfm_finetuning"
    ]
    assert len(finetuning_calls) == int(execute_finetuning)
    if execute_finetuning:
        assert finetuning_calls[0].status == "ok"
        assert result.artifacts[0].payload == {
            "task_completed": True, "operation": "fine_tuning",
            "checkpoint_path": "/tmp/trained_checkpoint", "model_checkpoint": "/tmp/trained_checkpoint",
            "metrics_file": "/tmp/metrics.csv", "results_file": "/tmp/metrics.csv",
        }
    else:
        assert result.artifacts[0].payload == {}


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
                                "dataset_path": _csv_path(asset),
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
            if self.react_count > 2:
                return json.dumps({"done": True})
            assets = [3, 4, 6, 9] if self.react_count == 1 else [3, 6, 9]
            return json.dumps(
                {
                    "tool_calls": [
                        {
                            "tool_name": "tsfm.run_integrated_tsad",
                            "args": {
                                "dataset_path": _csv_path(asset),
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


class PartialDataLLM:
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
            if args.get("dataset_path") == _csv_path(4):
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


class MultiAssetMCPToolClient:
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
@pytest.mark.parametrize("parallel", [False, True])
async def test_successful_tool_calls_run_again_when_requested(tmp_path, parallel):
    llm = DuplicateRetryLLM()
    mcp_tools = BatchMCPToolClient(delay=0.01)
    specialist = TimeSeriesAnalysisSpecialist(
        llm=llm,
        mcp_tools=mcp_tools,
        artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path),
        event_stream=EventStream(quiet=True),
        enable_parallel=parallel,
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

    expected_assets = [3, 4, 6, 9, 3, 6, 9] if parallel else [3, 3]
    expected_statuses = ["ok", "failed", "ok", "ok", "ok", "ok", "ok"] if parallel else ["ok", "ok"]
    assert llm.react_count == 3
    assert [args["dataset_path"] for _, args in mcp_tools.calls] == [
        _csv_path(asset) for asset in expected_assets
    ]
    assert [call.status for call in result.tool_calls] == expected_statuses
    records = [
        json.loads(line)
        for line in (tmp_path / "case_duplicate_retry.jsonl").read_text().splitlines()
    ]
    assert len(records[0]["tool_calls"]) == len(expected_assets)


@pytest.mark.anyio
@pytest.mark.parametrize("parallel", [False, True])
async def test_data_collection_does_not_collect_assets_omitted_by_llm(tmp_path, parallel):
    mcp_tools = MultiAssetMCPToolClient()
    specialist = DataCollectionSpecialist(
        llm=PartialDataLLM(),
        mcp_tools=mcp_tools,
        artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path),
        event_stream=EventStream(quiet=True),
        enable_parallel=parallel,
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
    assert history_assets == (["Chiller 6"] if parallel else [])
    assert [tool_name for tool_name, _ in mcp_tools.calls] == (
        ["iot.assets", "iot.history_csv"] if parallel else ["iot.assets"]
    )
    assert specialist.llm.react_count == 2
    assert result.artifacts[0].asset_ids == ["Chiller 6"]
    assert "datasets_by_asset" not in result.artifacts[0].payload
    assert "asset_count" not in result.artifacts[0].payload


@pytest.mark.anyio
@pytest.mark.parametrize("parallel", [False, True])
async def test_time_series_does_not_analyze_csvs_after_llm_is_done(tmp_path, parallel):
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
    mcp_tools = MultiAssetMCPToolClient()
    specialist = TimeSeriesAnalysisSpecialist(
        llm=DoneLLM(),
        mcp_tools=mcp_tools,
        artifact_store=artifact_store,
        behavior_log=BehaviorLog(log_dir=tmp_path),
        event_stream=EventStream(quiet=True),
        enable_parallel=parallel,
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

    assert mcp_tools.calls == []
    assert result.tool_calls == []
    assert len(result.artifacts) == 1
    assert result.artifacts[0].asset_ids == ["Chiller 6"]
    assert result.artifacts[0].payload == {"note": "LLM only mentioned Chiller 6."}


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("artifact_present", [False, True])
@pytest.mark.parametrize("specialist_cls,tool_name,artifact_type", [
    (DataCollectionSpecialist, "iot.history_csv", "dataset_ref"),
    (TimeSeriesAnalysisSpecialist, "tsfm.run_integrated_tsad", "analysis_result"),
])
def test_postprocessing_does_not_add_coverage_or_create_artifacts(
    tmp_path, parallel, artifact_present, specialist_cls, tool_name, artifact_type,
):
    specialist = specialist_cls(
        llm=DoneLLM(), mcp_tools=MultiAssetMCPToolClient(), artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path), event_stream=EventStream(quiet=True),
        enable_parallel=parallel,
    )
    task = TaskEnvelope(
        case_id="case_artifact_selection", task_type="analysis", goal="Analyze data",
        site="MAIN", asset_ids=[], time_window=TimeWindow(), focus_metrics=[],
        input_artifacts=[],
    )
    artifact = ArtifactEnvelope(
        artifact_id="artifact_selected", case_id=task.case_id, producer=specialist.role,
        artifact_type=artifact_type, asset_ids=["Chiller 6"], time_window=TimeWindow(),
        source_tools=[], source_artifacts=[], payload={"note": "LLM selected this result"},
    )
    result = ToolCallResult(
        order=1, tool_name=tool_name,
        args={"asset_id": "Chiller 3", "dataset_path": _csv_path(3)}, status="ok",
        result=json.dumps({"csv_path": _csv_path(3), "results_file": "/tmp/analysis.csv"}),
    )
    artifacts = specialist._postprocess_artifacts(
        task, [], [result], [artifact] if artifact_present else [],
    )
    assert len(artifacts) == int(artifact_present)
    if artifact_present:
        assert artifacts[0].artifact_id == artifact.artifact_id
        assert artifacts[0].asset_ids == ["Chiller 6"]
        assert artifacts[0].payload["note"] == "LLM selected this result"
        assert not {"datasets_by_asset", "asset_count", "analysis_by_asset", "aggregate_summary", "coverage_summary"} & artifacts[0].payload.keys()
