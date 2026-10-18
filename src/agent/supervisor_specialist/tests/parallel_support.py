"""Shared scripted LLMs and fake MCP clients for specialist tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path


from agent.supervisor_specialist.agents.data_collection import DataCollectionSpecialist
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.runtime.mcp_tools import MCPToolClient
from agent.supervisor_specialist.schemas import MCPToolResult, TaskEnvelope, TimeWindow


_CSV_ROOT = Path('/tmp')


def _csv_path(asset):
    return str(_CSV_ROOT / f'chiller_{asset}.csv')


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


def _scripted_execution(tmp_path, decisions, mcp_tools):
    class ScriptedLLM:
        def __init__(self):
            self.decisions = iter(decisions)
            self.react_count = 0
            self.artifact_count = 0

        def generate(self, prompt, temperature=0.0):
            if "Decide the NEXT action." in prompt:
                self.react_count += 1
                return json.dumps(next(self.decisions))
            if "produce structured analysis artifacts" in prompt:
                self.artifact_count += 1
                return '{"artifacts": []}'
            raise AssertionError(f"Unexpected prompt: {prompt[:200]}")

    specialist = DataCollectionSpecialist(
        llm=ScriptedLLM(), mcp_tools=mcp_tools, artifact_store=ArtifactStore(),
        behavior_log=BehaviorLog(log_dir=tmp_path), event_stream=EventStream(quiet=True),
        enable_parallel=True,
    )
    task = TaskEnvelope(
        case_id="case_execution_constraints", task_type="collect", goal="Collect inventory",
        site="MAIN", asset_ids=[], time_window=TimeWindow(), focus_metrics=[], input_artifacts=[],
    )
    return specialist, task
