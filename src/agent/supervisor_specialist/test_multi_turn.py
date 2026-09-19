from __future__ import annotations

import argparse
import json
import re

import pytest

from agent.supervisor_specialist.runner import SupervisorSpecialistRunner
from agent.supervisor_specialist.schemas import MCPToolResult


class FakeLLM:
    def __init__(self) -> None:
        self.react_counts: dict[str, int] = {}

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        del temperature
        if "Your job: decide the next action" in prompt:
            return self._supervisor_decision(prompt)
        if "Decide the NEXT action." in prompt:
            return self._react_step(prompt)
        if "produce structured analysis artifacts" in prompt:
            return self._artifact_response(prompt)
        if "write a clear and structured response" in prompt:
            return self._final_response(prompt)
        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")

    def _case_id(self, prompt: str) -> str:
        match = re.search(r'"case_id":\s*"([^"]+)"', prompt)
        assert match, prompt
        return match.group(1)

    def _supervisor_decision(self, prompt: str) -> str:
        case_id = self._case_id(prompt)
        window = {
            "start": "2020-05-21T00:00:00",
            "end": "2020-06-20T00:00:00",
            "lookback_days": 30,
        }
        if "Latest user message:\nWhat did you find?" in prompt:
            return json.dumps(
                {
                    "next_node": "respond_to_user",
                    "next_task": None,
                    "case_status": "completed",
                    "next_step": "Answer from conversation memory.",
                }
            )
        if "Latest user message:\nWhat could be causing this during the same period?" in prompt:
            if "[artifact_fr_001]" in prompt:
                return json.dumps(
                    {
                        "next_node": "respond_to_user",
                        "next_task": None,
                        "case_status": "completed",
                        "next_step": "Explain likely cause.",
                    }
                )
            return json.dumps(
                {
                    "next_node": "failure_reasoning_specialist",
                    "next_task": {
                        "case_id": case_id,
                        "task_type": "failure_reasoning",
                        "goal": "Use prior temperature artifact to identify likely causes.",
                        "site": "MAIN",
                        "asset_ids": ["Chiller 6"],
                        "time_window": window,
                        "focus_metrics": ["temperature"],
                        "input_artifacts": ["artifact_dc_001"],
                        "constraints": {},
                    },
                    "case_status": "reasoning",
                    "next_step": "Map anomaly patterns to failure modes.",
                }
            )

        if "[artifact_dc_001]" in prompt:
            return json.dumps(
                {
                    "next_node": "respond_to_user",
                    "next_task": None,
                    "case_status": "completed",
                    "next_step": "Summarize collected temperature data.",
                }
            )
        return json.dumps(
            {
                "next_node": "data_collection_specialist",
                "next_task": {
                    "case_id": case_id,
                    "task_type": "collect_temperature_data",
                    "goal": "Collect temperature data for Chiller 6 at MAIN.",
                    "site": "MAIN",
                    "asset_ids": ["Chiller 6"],
                    "time_window": window,
                    "focus_metrics": ["temperature"],
                    "input_artifacts": [],
                    "constraints": {},
                },
                "case_status": "collecting_data",
                "next_step": "Collect relevant IoT data.",
            }
        )

    def _react_step(self, prompt: str) -> str:
        role = "failure" if "Failure Reasoning Specialist" in prompt else "data"
        count = self.react_counts.get(role, 0)
        self.react_counts[role] = count + 1
        if count > 0:
            return json.dumps({"done": True})
        if role == "failure":
            return json.dumps(
                {
                    "tool_name": "fmsr.get_failure_modes",
                    "args": {"asset_name": "Chiller 6"},
                }
            )
        return json.dumps(
            {
                "tool_name": "iot.sensors",
                "args": {"site_name": "MAIN", "asset_id": "Chiller 6"},
            }
        )

    def _artifact_response(self, prompt: str) -> str:
        if "Failure Reasoning Specialist" in prompt:
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "artifact_type": "reasoning_result",
                            "asset_ids": ["Chiller 6"],
                            "time_window": {
                                "start": "2020-05-21T00:00:00",
                                "end": "2020-06-20T00:00:00",
                            },
                            "source_artifacts": ["artifact_dc_001"],
                            "payload": {
                                "primary_hypothesis": "Condenser water side fouling",
                                "confidence": "moderate",
                            },
                            "open_questions": [],
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "artifacts": [
                    {
                        "artifact_type": "dataset_ref",
                        "asset_ids": ["Chiller 6"],
                        "time_window": {
                            "start": "2020-05-21T00:00:00",
                            "end": "2020-06-20T00:00:00",
                        },
                        "source_artifacts": [],
                        "payload": {
                            "csv_path": "/tmp/assetops/chiller6_temperature.csv",
                            "stats": {"Supply Temperature": {"mean": 51.8}},
                        },
                        "open_questions": [],
                    }
                ]
            }
        )

    def _final_response(self, prompt: str) -> str:
        if "Latest user question: What could be causing this during the same period?" in prompt:
            return "Likely cause: condenser water side fouling."
        if "Latest user question: What did you find?" in prompt:
            return "Earlier findings: Chiller 6 temperature data was collected and analyzed."
        return "Collected Chiller 6 temperature data for the past month."


class FakeMCPToolClient:
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
        return MCPToolResult(
            status="ok",
            result=json.dumps(
                {
                    "tool": tool_name,
                    "args": args,
                    "csv_path": "/tmp/assetops/fake_result.csv",
                }
            ),
        )


@pytest.mark.anyio
async def test_multi_turn_reuses_prior_artifacts_and_same_period(tmp_path):
    fake_mcp = FakeMCPToolClient()
    runner = SupervisorSpecialistRunner(
        llm=FakeLLM(),
        mcp_tools=fake_mcp,
        quiet=True,
        log_dir=tmp_path,
        reference_date="2020-06-20",
        max_steps=5,
    )

    first = await runner.run_turn(
        "The temperature of our chiller at Site MAIN seems unusually high lately."
    )
    assert "Collected Chiller 6 temperature data" in first
    state = runner.last_dialog_state
    assert state is not None
    memory = state["conversation_memory"]
    assert memory.active_asset_ids == ["Chiller 6"]
    assert memory.active_time_window.start == "2020-05-21T00:00:00"
    assert "artifact_dc_001" in memory.active_artifact_ids
    assert fake_mcp.calls == [("iot.sensors", {"site_name": "MAIN", "asset_id": "Chiller 6"})]

    second = await runner.run_turn("What could be causing this during the same period?")
    assert "condenser water side fouling" in second
    state = runner.last_dialog_state
    assert state is not None
    memory = state["conversation_memory"]
    assert memory.active_time_window.start == "2020-05-21T00:00:00"
    assert memory.active_time_window.end == "2020-06-20T00:00:00"
    assert "artifact_fr_001" in memory.active_artifact_ids
    assert fake_mcp.calls[-1] == ("fmsr.get_failure_modes", {"asset_name": "Chiller 6"})
    assert memory.recent_turns[-1].tool_calls[0].tool_name == "fmsr.get_failure_modes"
    assert memory.recent_turns[-1].tool_calls[0].file_paths == ["/tmp/assetops/fake_result.csv"]

    log_path = next(tmp_path.glob("*.jsonl"))
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert {"timestamp", "case_id", "agent_role", "task_type", "turn_id"} <= records[0].keys()
    assert {r["turn_id"] for r in records} == {"turn_001", "turn_002"}
    assert any(
        r["turn_id"] == "turn_001" and r["agent_role"] == "data_collection_specialist"
        for r in records
    )
    assert any(
        r["turn_id"] == "turn_002" and r["agent_role"] == "failure_reasoning_specialist"
        for r in records
    )


@pytest.mark.anyio
async def test_followup_can_answer_from_memory_without_new_tools(tmp_path):
    fake_mcp = FakeMCPToolClient()
    runner = SupervisorSpecialistRunner(
        llm=FakeLLM(),
        mcp_tools=fake_mcp,
        quiet=True,
        log_dir=tmp_path,
        reference_date="2020-06-20",
        max_steps=5,
    )

    await runner.run_turn("The temperature of our chiller at Site MAIN seems unusually high lately.")
    calls_after_first = len(fake_mcp.calls)

    answer = await runner.run_turn("What did you find?")

    assert "Earlier findings" in answer
    assert len(fake_mcp.calls) == calls_after_first
    state = runner.last_dialog_state
    assert state is not None
    memory = state["conversation_memory"]
    assert len(memory.recent_turns) == 2
    assert memory.recent_turns[-1].tool_calls == []
    assert "Chiller 6 temperature data" in memory.rolling_summary


@pytest.mark.anyio
async def test_cli_multi_turn_repl_runs_until_quit(monkeypatch, capsys):
    from agent.supervisor_specialist import cli
    import agent.supervisor_specialist.runner as runner_mod
    import llm.litellm as litellm_mod

    created_kwargs = {}

    class DummyRunner:
        def __init__(self, **kwargs) -> None:
            created_kwargs.update(kwargs)
            self.questions: list[str] = []

        async def run_turn(self, question: str) -> str:
            self.questions.append(question)
            return f"answer:{question}"

    monkeypatch.setattr(litellm_mod, "LiteLLMBackend", lambda model_id: object())
    monkeypatch.setattr(runner_mod, "SupervisorSpecialistRunner", DummyRunner)
    inputs = iter(["second turn", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    await cli._run(
        argparse.Namespace(
            question="first turn",
            model_id="fake/model",
            max_steps=3,
            no_stream=True,
            no_log=True,
            log_dir=None,
            reference_date="2020-06-20",
            multi_turn=True,
            parallel=True,
            reuse_mode="none",
            max_repeat_dispatch=2,
        )
    )

    out = capsys.readouterr().out
    assert "answer:first turn" in out
    assert "answer:second turn" in out
    assert created_kwargs["parallel"] is True
    assert created_kwargs["reuse_mode"] == "none"
    assert created_kwargs["max_repeat_dispatch"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("reuse_mode", ["full", "none", "stateless"])
async def test_reuse_modes_work_with_parallel_execution(tmp_path, parallel, reuse_mode):
    runner = SupervisorSpecialistRunner(
        llm=FakeLLM(), mcp_tools=FakeMCPToolClient(), quiet=True,
        log_dir=tmp_path, reference_date="2020-06-20", max_steps=5,
        parallel=parallel, reuse_mode=reuse_mode,
    )
    await runner.run_turn("The temperature of our chiller at Site MAIN seems unusually high lately.")
    assert runner.last_dialog_state["conversation_memory"].active_artifact_ids == ["artifact_dc_001"]
    await runner.run_turn("What did you find?")
    memory = runner.last_dialog_state["conversation_memory"]
    assert memory.active_artifact_ids == (["artifact_dc_001"] if reuse_mode == "full" else [])
    assert len(memory.recent_turns) == (1 if reuse_mode == "stateless" else 2)


@pytest.mark.anyio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("selected_artifacts", [[], ["artifact_dc_001"]])
async def test_specialist_receives_only_supervisor_selected_artifacts(
    tmp_path, parallel, selected_artifacts,
):
    class SelectiveLLM(FakeLLM):
        def _artifact_response(self, prompt):
            response = json.loads(super()._artifact_response(prompt))
            if "Data Collection Specialist" in prompt:
                response["artifacts"].append({
                    **response["artifacts"][0],
                    "payload": {"note": "Unselected evidence"},
                })
            return json.dumps(response)

        def _supervisor_decision(self, prompt):
            response = json.loads(super()._supervisor_decision(prompt))
            if response["next_node"] == "failure_reasoning_specialist":
                response["next_task"]["input_artifacts"] = selected_artifacts
            return json.dumps(response)

    runner = SupervisorSpecialistRunner(
        llm=SelectiveLLM(), mcp_tools=FakeMCPToolClient(), quiet=True,
        log_dir=tmp_path, reference_date="2020-06-20", max_steps=5,
        parallel=parallel,
    )
    await runner.run_turn(
        "The temperature of our chiller at Site MAIN seems unusually high lately."
    )
    assert runner.last_dialog_state["case_state"].artifact_ids == [
        "artifact_dc_001", "artifact_dc_002",
    ]
    await runner.run_turn("What could be causing this during the same period?")
    records = [
        json.loads(line)
        for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()
    ]
    specialist_records = [
        record for record in records
        if record["agent_role"] == "failure_reasoning_specialist"
    ]
    assert len(specialist_records) == 1
    assert specialist_records[0]["status"] == "ok"
    assert specialist_records[0]["input_artifact_ids"] == selected_artifacts
    assert specialist_records[0]["task"]["input_artifacts"] == selected_artifacts
