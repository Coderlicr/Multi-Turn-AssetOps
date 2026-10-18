"""Respect agent decisions without implicit tool execution or synthetic coverage."""

from __future__ import annotations

import json

import pytest

from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.agents.time_series_analysis import TimeSeriesAnalysisSpecialist
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

from .parallel_support import (
    _csv_path,
    DuplicateRetryLLM,
    PartialDataLLM,
    DoneLLM,
    BatchMCPToolClient,
    MultiAssetMCPToolClient,
)

pytestmark = pytest.mark.usefixtures("existing_csv_inputs")


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
