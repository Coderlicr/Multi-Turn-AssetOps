import json

import pytest

from agent.supervisor_specialist.runner import SupervisorSpecialistRunner
from agent.supervisor_specialist.maintie_path import (
    _apply_query_semantics,
    _can_answer_from_recent,
    _is_acknowledgement,
)
from agent.supervisor_specialist.agents.supervisor import SupervisorAgent
from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.runtime.behavior_log import BehaviorLog
from agent.supervisor_specialist.runtime.event_stream import EventStream
from agent.supervisor_specialist.schemas import (
    CaseState,
    ExecutionBudget,
    MCPToolResult,
    ConversationMemory,
    DialogTurnRecord,
    TimeWindow,
    ToolCallRequest,
)


class QueueLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt, temperature=0.0):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("Unexpected LLM call")
        return json.dumps(self.responses.pop(0))


class SelectionMCP:
    def __init__(self):
        self.calls = []

    async def get_allowed_tool_schemas(self, allowed_tools):
        return [
            {
                "name": "maintie.search",
                "description": "search",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filter": {"$ref": "#/$defs/QueryFilter"},
                        "within_ids": {"type": ["array", "null"]},
                    },
                    "$defs": {
                        "QueryFilter": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "activities": {"type": "array"},
                                "object_terms": {"type": "array"},
                                "has_fault": {"type": ["boolean", "null"]},
                            },
                        }
                    },
                },
            }
        ]

    async def call(self, tool_name, args):
        self.calls.append((tool_name, args))
        within = args.get("within_ids")
        if within is None:
            size = 107
        elif len(within) == 107:
            size = 40
        elif len(within) == 40:
            size = 24
        else:
            size = 1
        return MCPToolResult(
            status="ok",
            result=json.dumps({"count": size, "wo_ids": list(range(1, size + 1))}),
        )

    async def call_many_parallel(self, calls, max_concurrency=4):
        return [await self.call(call.tool_name, call.args) for call in calls]


@pytest.mark.anyio
async def test_progressive_filtering_uses_typed_active_selection(tmp_path):
    llm = QueueLLM(
        [
            {
                "tool_name": "maintie.search",
                "args": {"filter": {"object_terms": ["GuidingObject"]}},
                "selection_scope": "corpus",
            },
            {"done": True},
            {"result": {"n": 107}},
            {
                "tool_name": "maintie.search",
                "args": {"filter": {"activities": ["Replace"]}},
                "selection_scope": "active",
            },
            {"done": True},
            {"result": {"n": 40}},
            {
                "tool_name": "maintie.search",
                "args": {"filter": {"object_terms": ["hose"]}},
                "selection_scope": "active",
            },
            {"done": True},
            {"result": {"n": 24}},
        ]
    )
    mcp = SelectionMCP()
    runner = SupervisorSpecialistRunner(
        llm=llm,
        mcp_tools=mcp,
        mode="maintie",
        quiet=True,
        log_dir=tmp_path,
    )

    first = await runner.run_turn_result("guiding objects with a fault")
    second = await runner.run_turn_result("only those replaced")
    third = await runner.run_turn_result("now hoses out of those")

    assert [first.result, second.result, third.result] == [
        {"n": 107},
        {"n": 40},
        {"n": 24},
    ]
    assert "within_ids" not in mcp.calls[0][1]
    assert len(mcp.calls[1][1]["within_ids"]) == 107
    assert len(mcp.calls[2][1]["within_ids"]) == 40
    state = runner.last_dialog_state
    assert len(state["conversation_memory"].active_maintie_selection.wo_ids) == 24
    assert state["execution_budget"].specialist_dispatches_used == 1
    assert all("[1, 2, 3, 4, 5" not in prompt for prompt in llm.prompts)


@pytest.mark.anyio
async def test_exact_duplicate_tool_call_is_not_executed_twice(tmp_path):
    repeated = {
        "tool_name": "maintie.search",
        "args": {"filter": {"object_terms": ["belt"]}},
        "selection_scope": "corpus",
    }
    llm = QueueLLM([repeated, repeated, {"result": {"n": 107}}])
    mcp = SelectionMCP()
    runner = SupervisorSpecialistRunner(
        llm=llm,
        mcp_tools=mcp,
        mode="maintie",
        quiet=True,
        log_dir=tmp_path,
    )

    result = await runner.run_turn_result("belt work orders")

    assert len(mcp.calls) == 1
    assert result.tools == [["search"]]
    assert result.result == {"n": 107}


@pytest.mark.anyio
async def test_successful_aggregate_call_ends_tool_loop(tmp_path):
    llm = QueueLLM(
        [
            {
                "tool_name": "maintie.compare",
                "args": {
                    "queries": {
                        "bearing": {"object_terms": ["bearing"]},
                        "seal": {"object_terms": ["seal"]},
                    }
                },
            },
            {
                "tool_name": "maintie.search",
                "args": {"filter": {"object_terms": ["bearing", "seal"]}},
            },
            {"result": {"compared": True}},
        ]
    )
    mcp = SelectionMCP()
    runner = SupervisorSpecialistRunner(
        llm=llm,
        mcp_tools=mcp,
        mode="maintie",
        quiet=True,
        log_dir=tmp_path,
    )

    result = await runner.run_turn_result("compare bearings and seals")

    assert len(mcp.calls) == 1
    assert result.tools == [["compare"]]


def test_maintie_prompt_requires_tools_for_new_filters(tmp_path):
    runner = SupervisorSpecialistRunner(
        llm=QueueLLM([]),
        mcp_tools=SelectionMCP(),
        mode="maintie",
        quiet=True,
        log_dir=tmp_path,
    )
    prompt = runner._maintie_path._tool_prompt(
        "now hoses out of those", runner._maintie_memory, [], [], 6
    )

    assert "newly requested filter" in prompt
    assert "prior count alone cannot answer" in prompt
    assert "change out" in prompt


def test_lines_and_drives_query_preserves_explicit_broad_class():
    request = ToolCallRequest(
        tool_name="maintie.search",
        args={
            "filter": {
                "object_terms": ["belt", "chain", "hose", "cable"],
                "has_fault": True,
            }
        },
    )

    resolved = _apply_query_semantics("show failures on lines and drives", request)

    assert resolved.args == {
        "filter": {"object_terms": ["Lines & drives"], "has_fault": True}
    }


def test_rank_limit_is_derived_from_question():
    request = ToolCallRequest(tool_name="maintie.rank", args={"by": "object_class"})
    assert _apply_query_semantics("which equipment shows up most?", request).args["n"] == 1
    assert _apply_query_semantics("give me the top three", request).args["n"] == 3


def test_chat_acknowledgement_is_not_a_query():
    assert _is_acknowledgement("Makes sense, those seals are rubbish.")
    assert not _is_acknowledgement("Makes sense, but which seal is worst?")


def test_comparison_followup_can_reuse_recent_structured_result():
    memory = ConversationMemory(
        recent_turns=[
            DialogTurnRecord(
                turn_index=1,
                user_message="compare",
                assistant_answer="{}",
                structured_result={
                    "bearing": {"fault_work_orders": 10},
                    "seal": {"fault_work_orders": 14},
                },
            )
        ]
    )

    assert _can_answer_from_recent("Which of the two is more of a problem?", memory)
    assert not _can_answer_from_recent("Which equipment shows up most?", memory)


@pytest.mark.anyio
async def test_maintie_tool_budget_stops_seventh_call(tmp_path):
    responses = []
    for index in range(7):
        responses.append(
            {
                "tool_name": "maintie.search",
                "args": {"filter": {"object_terms": [f"term-{index}"]}},
            }
        )
    # The seventh queued item becomes the synthesis response after six calls.
    responses[6] = {"result": {"bounded": True}}
    llm = QueueLLM(responses)
    mcp = SelectionMCP()
    runner = SupervisorSpecialistRunner(
        llm=llm,
        mcp_tools=mcp,
        mode="maintie",
        quiet=True,
        log_dir=tmp_path,
        max_tool_calls=6,
    )

    result = await runner.run_turn_result("keep searching")

    assert len(mcp.calls) == 6
    assert len(result.tool_calls) == 6
    assert result.result == {"bounded": True}
    assert runner.last_dialog_state["execution_budget"].tool_calls_used == 6


def test_auto_mode_uses_maintie_only_server_set(tmp_path):
    runner = SupervisorSpecialistRunner(
        llm=QueueLLM([]),
        mcp_tools=SelectionMCP(),
        server_paths={"maintie": "maintie-mcp-server"},
        mode="auto",
        quiet=True,
        log_dir=tmp_path,
    )

    assert runner.mode == "maintie"


def test_deterministic_answer_is_exact_json(tmp_path):
    runner = SupervisorSpecialistRunner(
        llm=QueueLLM([]),
        mcp_tools=SelectionMCP(),
        mode="maintie",
        quiet=True,
        log_dir=tmp_path,
    )

    from agent.supervisor_specialist.maintie_path import render_maintie_answer

    assert render_maintie_answer({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'


@pytest.mark.anyio
async def test_supervisor_stops_before_third_specialist_dispatch(tmp_path):
    task = {
        "case_id": "case_budget",
        "task_type": "collect",
        "goal": "collect more",
        "site": "MAIN",
        "asset_ids": [],
        "time_window": {},
        "focus_metrics": [],
        "input_artifacts": [],
        "constraints": {},
    }
    llm = QueueLLM(
        [
            {
                "next_node": "data_collection_specialist",
                "next_task": task,
                "case_status": "collecting_data",
                "next_step": "first",
            },
            {
                "next_node": "data_collection_specialist",
                "next_task": task,
                "case_status": "collecting_data",
                "next_step": "second",
            },
        ]
    )
    supervisor = SupervisorAgent(
        llm=llm,
        artifact_store=ArtifactStore(),
        event_stream=EventStream(quiet=True),
        behavior_log=BehaviorLog(log_dir=tmp_path),
    )
    state = {
        "case_state": CaseState(
            case_id="case_budget",
            user_goal="collect",
            site="MAIN",
            asset_ids=[],
            time_window=TimeWindow(),
            focus_metrics=[],
            status="collecting_data",
        ),
        "current_user_message": "collect",
        "step_count": 0,
        "max_steps": 12,
        "execution_budget": ExecutionBudget(
            max_specialist_dispatches=2,
            max_tool_calls=6,
        ),
    }

    first = await supervisor.decide(state)
    second = await supervisor.decide(first)
    third = await supervisor.decide(second)

    assert first["next_node"] == "data_collection_specialist"
    assert second["next_node"] == "data_collection_specialist"
    assert third["next_node"] == "respond_to_user"
    assert third["execution_budget"].specialist_dispatches_used == 2
    assert len(llm.prompts) == 2
