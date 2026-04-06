"""Integration tests for Phase 1: retry, re-plan, and session tracking."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agent.models import PlanStepV2, PlanV2
from agent.plan_execute.executor import Executor
from agent.plan_execute.models import Plan, PlanStep
from agent.plan_execute.runner import PlanExecuteRunner
from agent.session import SessionState

# ── shared fixtures ────���─────────────────────────────────────────────────────

_MOCK_TOOLS = [
    {"name": "sites", "description": "List IoT sites", "parameters": []},
    {"name": "assets", "description": "List assets", "parameters": []},
]

_TWO_STEP_PLAN = """\
#Task1: Get IoT sites
#Server1: iot
#Tool1: sites
#Dependency1: None
#ExpectedOutput1: List of site names

#Task2: Get current datetime
#Server2: utilities
#Tool2: current_date_time
#Dependency2: None
#ExpectedOutput2: Current date and time"""

_REPLAN_ONE_STEP = """\
#Task1: Retry getting datetime via different approach
#Server1: utilities
#Tool1: current_date_time
#Dependency1: None
#ExpectedOutput1: Current date and time"""


def _patch_mcp(tool_response="{}"):
    return (
        patch(
            "agent.plan_execute.executor._list_tools",
            new=AsyncMock(return_value=_MOCK_TOOLS),
        ),
        patch(
            "agent.plan_execute.executor._call_tool",
            new=AsyncMock(return_value=tool_response),
        ),
    )


# ── execute_plan_v2 tests ───────��───────────────────────────────────────────


@pytest.mark.anyio
async def test_execute_plan_v2_success_records_session_state(sequential_llm):
    """Successful steps are written into the shared session state."""
    from pathlib import Path

    llm = sequential_llm(['{}'])
    executor = Executor(llm, server_paths={"iot": Path("/fake/server.py")})

    plan_v2 = PlanV2(
        steps=[PlanStepV2(step_number=1, task="Get sites", server="iot", tool="sites")],
        original_question="Q",
    )
    session = SessionState(question="Q")

    with (
        patch("agent.plan_execute.executor._list_tools", new=AsyncMock(return_value=_MOCK_TOOLS)),
        patch("agent.plan_execute.executor._call_tool", new=AsyncMock(return_value='{"sites": ["MAIN"]}')),
    ):
        results = await executor.execute_plan_v2(plan_v2, "Q", session)

    assert len(results) == 1
    assert results[0].success is True
    assert session.get_step(1) is not None


@pytest.mark.anyio
async def test_execute_plan_v2_retry_on_empty_response(sequential_llm):
    """Empty response triggers retry; second attempt succeeds."""
    from pathlib import Path

    llm = sequential_llm(['{}', '{}'])  # Two arg-resolution calls
    executor = Executor(llm, server_paths={"iot": Path("/fake/server.py")})

    plan_v2 = PlanV2(
        steps=[PlanStepV2(step_number=1, task="Get sites", server="iot", tool="sites")],
        original_question="Q",
    )
    session = SessionState(question="Q")

    call_count = 0

    async def _call_tool_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ""  # Empty — triggers retry
        return '{"sites": ["MAIN"]}'  # Second attempt succeeds

    with (
        patch("agent.plan_execute.executor._list_tools", new=AsyncMock(return_value=_MOCK_TOOLS)),
        patch("agent.plan_execute.executor._call_tool", new=AsyncMock(side_effect=_call_tool_side_effect)),
    ):
        results = await executor.execute_plan_v2(plan_v2, "Q", session)

    assert results[0].success is True
    assert results[0].attempts == 2


@pytest.mark.anyio
async def test_execute_plan_v2_max_retries_exhausted(sequential_llm):
    """After max_retries, step is marked as FAILED."""
    from pathlib import Path

    # max_retries=2 means attempts 1, 2, 3 total (initial + 2 retries)
    llm = sequential_llm(['{}', '{}', '{}'])
    executor = Executor(llm, server_paths={"iot": Path("/fake/server.py")})

    plan_v2 = PlanV2(
        steps=[PlanStepV2(
            step_number=1, task="Get sites", server="iot", tool="sites",
            max_retries=2,
        )],
        original_question="Q",
    )
    session = SessionState(question="Q")

    with (
        patch("agent.plan_execute.executor._list_tools", new=AsyncMock(return_value=_MOCK_TOOLS)),
        patch("agent.plan_execute.executor._call_tool", new=AsyncMock(return_value="")),  # Always empty
    ):
        results = await executor.execute_plan_v2(plan_v2, "Q", session)

    assert results[0].success is False
    assert results[0].attempts == 3  # initial + 2 retries


@pytest.mark.anyio
async def test_execute_plan_v2_session_lineage(sequential_llm):
    """Step 2 session record depends_on step 1 via lineage."""
    from pathlib import Path

    llm = sequential_llm(['{}', '{}'])
    executor = Executor(llm, server_paths={"iot": Path("/fake/server.py")})

    plan_v2 = PlanV2(
        steps=[
            PlanStepV2(step_number=1, task="A", server="iot", tool="sites"),
            PlanStepV2(step_number=2, task="B", server="iot", tool="assets", dependencies=[1]),
        ],
        original_question="Q",
    )
    session = SessionState(question="Q")

    with (
        patch("agent.plan_execute.executor._list_tools", new=AsyncMock(return_value=_MOCK_TOOLS)),
        patch("agent.plan_execute.executor._call_tool", new=AsyncMock(return_value='{"ok": true}')),
    ):
        results = await executor.execute_plan_v2(plan_v2, "Q", session)

    assert all(r.success for r in results)
    lineage = session.lineage(2)
    assert [record.step_number for record in lineage] == [1, 2]


@pytest.mark.anyio
async def test_execute_plan_v2_no_tool_step(sequential_llm):
    """A step with tool=none succeeds without MCP or LLM calls."""
    from pathlib import Path

    llm = sequential_llm([])  # No LLM calls expected
    executor = Executor(llm, server_paths={"iot": Path("/fake/server.py")})

    plan_v2 = PlanV2(
        steps=[PlanStepV2(
            step_number=1, task="Answer", server="iot", tool="none",
            expected_output="42",
        )],
        original_question="Q",
    )
    session = SessionState(question="Q")

    with (
        patch("agent.plan_execute.executor._list_tools", new=AsyncMock(return_value=_MOCK_TOOLS)),
        patch("agent.plan_execute.executor._call_tool", new=AsyncMock(return_value="")),
    ):
        results = await executor.execute_plan_v2(plan_v2, "Q", session)

    assert results[0].success is True
    assert results[0].response == "42"


# ── runner-level integration (re-plan) ──────────────────────────────────────


@pytest.mark.anyio
async def test_runner_replan_on_failure(sequential_llm):
    """When a step fails, runner triggers re-plan and executes replacement steps."""
    # Plan: 2 steps. Step 2 will always fail (empty response).
    # Re-plan: 1 step that succeeds.
    # LLM calls:
    #   1. planner -> _TWO_STEP_PLAN
    #   2. arg resolution step 1 -> {}
    #   3. arg resolution step 2 (attempt 1) -> {}
    #   4. arg resolution step 2 (attempt 2) -> {}
    #   5. arg resolution step 2 (attempt 3) -> {}
    #   6. re-planner -> _REPLAN_ONE_STEP
    #   7. arg resolution re-plan step 1 -> {}
    #   8. summarization -> "Final answer"

    call_count = 0

    async def _selective_tool_response(server_path, tool_name, args):
        nonlocal call_count
        call_count += 1
        if tool_name == "current_date_time" and call_count <= 4:
            return ""  # Fail for original step 2 (3 attempts)
        return '{"result": "ok"}'

    llm = sequential_llm([
        _TWO_STEP_PLAN,       # planner
        '{}',                 # step 1 args
        '{}',                 # step 2 args (attempt 1)
        '{}',                 # step 2 args (attempt 2)
        '{}',                 # step 2 args (attempt 3)
        _REPLAN_ONE_STEP,     # re-planner
        '{}',                 # re-plan step 1 args
        "Final answer",       # summarization
    ])

    with (
        patch("agent.plan_execute.executor._list_tools", new=AsyncMock(return_value=_MOCK_TOOLS)),
        patch("agent.plan_execute.executor._call_tool", new=AsyncMock(side_effect=_selective_tool_response)),
    ):
        result = await PlanExecuteRunner(llm).run("Q")

    assert result.answer == "Final answer"
    # Original 2 steps + 1 re-plan step = 3 history entries
    assert len(result.history) == 3
    assert [r.step_number for r in result.history] == [1, 2, 3]


@pytest.mark.anyio
async def test_runner_all_succeed_no_replan(sequential_llm):
    """When all steps succeed, no re-plan is triggered."""
    llm = sequential_llm([
        _TWO_STEP_PLAN,
        '{}',          # step 1 args
        '{}',          # step 2 args
        "Answer",      # summarization
    ])

    with _patch_mcp('{"ok": true}')[0], _patch_mcp('{"ok": true}')[1]:
        result = await PlanExecuteRunner(llm).run("Q")

    assert result.answer == "Answer"
    assert len(result.history) == 2
    assert all(r.success for r in result.history)
