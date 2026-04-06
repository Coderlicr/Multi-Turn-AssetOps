"""Plan-and-execute agent runner using MCP servers as tool providers.

Replaces AgentHive's combination of PlanningWorkflow + SequentialWorkflow with
an MCP-native implementation:

  AgentHive                       plan_execute
  ────────────────────────────    ─────────────────────────────
  PlanningWorkflow.generate_steps → Planner.generate_plan
  SequentialWorkflow.run          → Executor.execute_plan
  ReactAgent.execute_task         → _list_tools + _call_tool (MCP stdio)
"""

from __future__ import annotations

import logging
from pathlib import Path

from llm import LLMBackend

from .executor import Executor
from .models import Plan
from .planner import Planner
from ..models import OrchestratorResult, PlanV2, TaskStatus
from ..runner import AgentRunner
from ..session import SessionState

_log = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = """\
You are summarizing the results of a multi-step task execution for an \
industrial asset operations system.

Original question: {question}

Step-by-step execution results:
{results}

Provide a concise, direct answer to the original question based on the results
above. Do not repeat the individual steps — just give the final answer.
"""


def _renumber_plan(plan: Plan, start_from: int) -> Plan:
    """Rewrite a plan's step numbers so they are globally unique within a run."""
    number_map: dict[int, int] = {}
    next_number = start_from
    for step in plan.steps:
        number_map[step.step_number] = next_number
        next_number += 1

    for step in plan.steps:
        step.step_number = number_map[step.step_number]
        step.dependencies = [number_map[dep] for dep in step.dependencies]

    return plan


class PlanExecuteRunner(AgentRunner):
    """Entry-point for plan-and-execute workflows using MCP servers as tool providers.

    Usage::

        from agent import PlanExecuteRunner
        from llm import LiteLLMBackend

        runner = PlanExecuteRunner(llm=LiteLLMBackend("watsonx/meta-llama/llama-3-3-70b-instruct"))
        result = await runner.run("What are the assets at site MAIN?")
        print(result.answer)

    Args:
        llm: LLM backend used for planning, tool selection, and summarisation.
        server_paths: Override MCP server specs.  Keys must match the server
                      names the planner will assign steps to.  Values are
                      either a uv entry-point name (str) or a Path to a
                      script file.  Defaults to all five registered servers.
    """

    def __init__(
        self,
        llm: LLMBackend,
        server_paths: dict[str, Path | str] | None = None,
    ) -> None:
        super().__init__(llm, server_paths)
        self._planner = Planner(llm)
        self._executor = Executor(llm, server_paths)

    async def run(self, question: str) -> OrchestratorResult:
        """Run the full plan-execute loop for a question.

        Phase 1 pipeline:
          1. Discover available servers from registered MCP servers.
          2. Use the LLM to decompose the question into an execution plan.
          3. Wrap into PlanV2 (strong-typed Pydantic models).
          4. Execute with validation, retry, and shared session state.
          5. On step failure after max retries, re-plan remaining steps once.
          6. Summarise the step results into a final answer.

        Returns:
            OrchestratorResult with the same interface as before.
        """
        # 1. Discover
        _log.info("Discovering server capabilities...")
        server_descriptions = await self._executor.get_server_descriptions()

        # 2. Plan (text-format, parsed via regex — unchanged)
        _log.info("Planning...")
        plan = self._planner.generate_plan(question, server_descriptions)
        _log.info("Plan has %d step(s).", len(plan.steps))

        # 3. Wrap into V2 models
        plan_v2 = PlanV2.from_legacy(plan, question=question)
        session = SessionState(question=question)

        # 4. Execute with validation, retry, and shared session state
        history_v2 = await self._executor.execute_plan_v2(plan_v2, question, session)

        # 5. Check for failures — attempt one re-plan if needed
        failed = [r for r in history_v2 if not r.success]
        if failed:
            first_fail = failed[0]
            completed = [r for r in history_v2 if r.success]
            remaining_steps = [
                s for s in plan_v2.steps
                if s.step_number > first_fail.step_number
                and s.status == TaskStatus.PENDING
            ]

            if remaining_steps or first_fail:
                _log.info(
                    "Step %d failed after retries. Attempting re-plan...",
                    first_fail.step_number,
                )
                replan = self._planner.replan(
                    original_question=question,
                    server_descriptions=server_descriptions,
                    completed=completed,
                    failed=first_fail,
                    remaining=remaining_steps,
                )
                if replan.steps:
                    next_step_number = max((r.step_number for r in history_v2), default=0) + 1
                    replan = _renumber_plan(replan, start_from=next_step_number)
                    replan_v2 = PlanV2.from_legacy(replan, question=question)
                    replan_results = await self._executor.execute_plan_v2(
                        replan_v2, question, session
                    )
                    history_v2.extend(replan_results)

        # 6. Convert V2 results back to legacy StepResult for backward compat
        from .models import StepResult

        history = [
            StepResult(
                step_number=r.step_number,
                task=r.task,
                server=r.server,
                response=r.response,
                error=r.error,
                tool=r.tool,
                tool_args=r.tool_args,
            )
            for r in history_v2
        ]

        # 7. Summarise
        _log.info("Summarising...")
        results_text = "\n\n".join(
            f"Step {r.step_number} — {r.task} (server: {r.server}):\n"
            + (r.response if r.success else f"ERROR: {r.error}")
            for r in history
        )
        answer = self._llm.generate(
            _SUMMARIZE_PROMPT.format(question=question, results=results_text)
        )

        return OrchestratorResult(
            question=question,
            answer=answer,
            plan=plan,
            history=history,
        )
