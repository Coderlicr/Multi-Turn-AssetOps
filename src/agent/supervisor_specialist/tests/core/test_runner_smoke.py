"""Exercise the real runner with scripted LLM responses and a fake MCP client."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.supervisor_specialist.runner import SupervisorSpecialistRunner


def _make_runner(tmp_path, *, max_steps, finish_after_collection):
    supervisor_calls = []

    def generate(prompt, temperature=0.0):
        if "Your job: decide the next action" in prompt:
            case_state, _ = json.JSONDecoder().raw_decode(
                prompt.split("Current case state:\n", 1)[1]
            )
            supervisor_calls.append(case_state)
            if finish_after_collection and len(supervisor_calls) == 2:
                return json.dumps({
                    "next_node": "respond_to_user",
                    "next_task": None,
                    "case_status": "completed",
                    "next_step": "Answer from the collected inventory",
                })
            return json.dumps({
                "next_node": "data_collection_specialist",
                "next_task": {
                    "case_id": case_state["case_id"],
                    "task_type": "collect_assets",
                    "goal": "Collect asset inventory",
                    "site": case_state["site"],
                    "asset_ids": [],
                    "time_window": case_state["time_window"],
                    "focus_metrics": [],
                    "input_artifacts": [],
                },
                "case_status": "collecting_data",
                "next_step": "Collecting inventory",
            })
        if "Decide the NEXT action." in prompt:
            return '{"done": true}'
        if "produce structured analysis artifacts" in prompt:
            return json.dumps({"artifacts": [{
                "artifact_type": "inventory",
                "asset_ids": ["Chiller 6"],
                "payload": {"assets": ["Chiller 6"]},
            }]})
        if "write a clear and structured response" in prompt:
            assert "Chiller 6" in prompt
            return "Chiller 6 is listed at MAIN."
        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")

    llm = MagicMock()
    llm.generate.side_effect = generate
    mcp = MagicMock()
    mcp.get_allowed_tool_schemas = AsyncMock(return_value=[])
    mcp.call = AsyncMock()
    runner = SupervisorSpecialistRunner(
        llm=llm,
        mcp_tools=mcp,
        max_steps=max_steps,
        quiet=True,
        log_dir=tmp_path,
        reference_date="2020-06-20",
    )
    return runner, supervisor_calls, mcp


@pytest.mark.anyio
async def test_runner_completes_minimal_flow(tmp_path):
    runner, supervisor_calls, mcp = _make_runner(
        tmp_path, max_steps=12, finish_after_collection=True,
    )

    answer = await runner.run("What assets are at MAIN?")

    assert answer == "Chiller 6 is listed at MAIN."
    assert len(supervisor_calls) == 2
    assert supervisor_calls[1]["artifact_ids"] == ["artifact_dc_001"]
    snapshot = await runner._graph.aget_state({
        "configurable": {"thread_id": supervisor_calls[0]["case_id"]},
    })
    state = snapshot.values
    assert state["case_state"].status == "completed"
    assert state["error_message"] is None
    assert state["turn_artifact_ids"] == ["artifact_dc_001"]
    assert len(state["conversation_memory"].recent_turns) == 1
    mcp.get_allowed_tool_schemas.assert_awaited_once()
    mcp.call.assert_not_awaited()

    records = [json.loads(line) for line in
               (tmp_path / f'{state["case_state"].case_id}.jsonl').read_text().splitlines()]
    assert [record["agent_role"] for record in records] == [
        "user", "supervisor", "data_collection_specialist", "supervisor", "respond_to_user",
    ]
    assert all(record["status"] == "ok" for record in records)
    assert records[-1]["final_response"] == answer


@pytest.mark.anyio
async def test_runner_handles_max_steps(tmp_path):
    runner, supervisor_calls, mcp = _make_runner(
        tmp_path, max_steps=1, finish_after_collection=False,
    )

    answer = await runner.run("What assets are at MAIN?")

    assert answer == "Chiller 6 is listed at MAIN."
    # The second visit to the supervisor terminates without another LLM decision.
    assert len(supervisor_calls) == 1
    snapshot = await runner._graph.aget_state({
        "configurable": {"thread_id": supervisor_calls[0]["case_id"]},
    })
    state = snapshot.values
    assert state["case_state"].status == "waiting_for_user"
    assert "Maximum" in state["error_message"]
    assert state["turn_artifact_ids"] == ["artifact_dc_001"]
    mcp.get_allowed_tool_schemas.assert_awaited_once()
    mcp.call.assert_not_awaited()
