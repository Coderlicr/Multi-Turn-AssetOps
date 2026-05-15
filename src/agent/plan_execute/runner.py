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
import uuid
from datetime import datetime, timezone
from pathlib import Path

from llm import LLMBackend

from .behavior_log import PlanExecuteBehaviorLog, plan_to_dict
from .executor import Executor
from .planner import Planner
from ..models import OrchestratorResult
from ..runner import AgentRunner
from ..session import SessionState

_log = logging.getLogger(__name__)

_MAX_REPLAN_ATTEMPTS = 2

_SUMMARIZE_PROMPT = """\
You are summarizing the results of a multi-step task execution for an \
industrial asset operations system.

Original question: {question}

Step-by-step execution results:
{results}

Provide a concise, direct answer to the original question based on the results above.
Rules:
- Do not repeat the individual steps — just give the final answer.
- Read the question type before framing the answer:
  * Fault / anomaly / "what's wrong" questions: identify the primary concern asset \
by name and lead with it (highest anomaly count, highest mean, increasing trend).
  * Comparison questions ("compare", "which is more efficient", "difference between"): \
summarise the differences objectively — do NOT label one asset as "primary concern" \
unless the data clearly shows a fault.
  * Prediction / forecast questions: state the predicted outcome with the supporting numbers.
- State conclusions directly. Do not end with "further investigation is recommended" \
unless no data supports a conclusion.
- Include specific numbers (mean, anomaly count, trend direction, slope) to back up claims.
- Do not interpret a higher or lower metric value as good or bad unless the metric name \
makes it unambiguous (e.g. "anomaly_count", "error_rate" are bad when high; \
"efficiency" direction depends on context — state the value and trend, not a judgement).
"""


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
        behavior_log: PlanExecuteBehaviorLog | None = None,
        log_dir: Path | None = None,
        reference_date: str | None = None,
    ) -> None:
        super().__init__(llm, server_paths)
        if behavior_log is not None and log_dir is not None:
            raise ValueError("Pass either behavior_log or log_dir, not both.")
        self._reference_date = self._resolve_reference_date(reference_date)
        self._behavior_log = behavior_log or (
            PlanExecuteBehaviorLog(log_dir=log_dir) if log_dir is not None else None
        )
        self._dialog_case_id = self._make_case_id()
        self._turn_index = 0
        self._planner = Planner(llm)
        self._executor = Executor(
            llm,
            server_paths,
            behavior_log=self._behavior_log,
            reference_date=self._reference_date,
        )

    async def run(
        self,
        question: str,
        session: SessionState | None = None,
    ) -> OrchestratorResult:
        """Run the full plan-execute loop for a question.

        Steps:
          1. Discover available servers from registered MCP servers.
          2. Use the LLM to decompose the question into an execution plan.
          3. Execute each plan step by routing tool calls to MCP servers.
          4. Summarise the step results into a final answer.

        Args:
            question: The user question to answer.
            session: Optional conversation state reused across turns.

        Returns:
            OrchestratorResult with the final answer, the generated plan, and
            the per-step execution history.
        """
        effective_question = (
            session.build_question(question) if session is not None else question
        )
        if session is None:
            case_id = self._make_case_id()
            turn_index = 1
        else:
            case_id = self._dialog_case_id
            self._turn_index += 1
            turn_index = self._turn_index
        turn_id = f"turn_{turn_index:03d}"

        self._write_behavior(
            case_id=case_id,
            turn_id=turn_id,
            agent_role="user",
            task_type="user_question",
            status="ok",
            user_message=question,
            effective_question=effective_question,
            reference_date=self._reference_date,
        )
        print("[DEBUG] Question of this turn:")
        print(effective_question)

        # 1. Discover
        _log.info("Discovering server capabilities...")
        server_descriptions = await self._executor.get_server_descriptions()

        # 2. Plan
        _log.info("Planning...")
        plan = self._planner.generate_plan(effective_question, server_descriptions)
        _log.info("Plan has %d step(s).", len(plan.steps))
        self._write_behavior(
            case_id=case_id,
            turn_id=turn_id,
            agent_role="planner",
            task_type="plan_generation",
            status="ok",
            plan_id="plan_001",
            plan_kind="original",
            plan=plan_to_dict(plan),
        )

        # 3. Execute (with replan loop on failures)
        original_plan = plan
        replans: list = []
        accumulated_context: dict[int, object] = {}

        round_history = await self._executor.execute_plan(
            plan,
            effective_question,
            case_id=case_id,
            turn_id=turn_id,
            plan_id="plan_001",
        )
        for r in round_history:
            accumulated_context[r.step_number] = r
        history = round_history
        next_step = max(s.step_number for s in plan.steps) + 1

        for attempt in range(_MAX_REPLAN_ATTEMPTS):
            # Only check the most recent round — already-repaired failures are ignored.
            failed = [r for r in round_history if not r.success]
            if not failed:
                break
            _log.info(
                "Replan attempt %d/%d: %d failed step(s).",
                attempt + 1,
                _MAX_REPLAN_ATTEMPTS,
                len(failed),
            )
            replan = self._planner.generate_replan(
                question=effective_question,
                original_plan=original_plan,
                history=history,
                server_descriptions=server_descriptions,
                next_step_number=next_step,
            )
            if not replan.steps:
                _log.warning("Replan produced no steps; stopping.")
                self._write_behavior(
                    case_id=case_id,
                    turn_id=turn_id,
                    agent_role="planner",
                    task_type="replan_generation",
                    status="failed",
                    plan_id=f"replan_{attempt + 1:03d}",
                    plan_kind="replan",
                    replan_attempt=attempt + 1,
                    failed_step_numbers=[r.step_number for r in failed],
                    error_message="Replan produced no steps.",
                    plan=plan_to_dict(replan),
                )
                break
            _log.info("Replan has %d new step(s).", len(replan.steps))
            replan_id = f"replan_{attempt + 1:03d}"
            self._write_behavior(
                case_id=case_id,
                turn_id=turn_id,
                agent_role="planner",
                task_type="replan_generation",
                status="ok",
                plan_id=replan_id,
                plan_kind="replan",
                replan_attempt=attempt + 1,
                failed_step_numbers=[r.step_number for r in failed],
                plan=plan_to_dict(replan),
            )
            replans.append(replan)
            next_step = max(s.step_number for s in replan.steps) + 1
            round_history = await self._executor.execute_plan(
                replan,
                effective_question,
                prior_context=accumulated_context,
                case_id=case_id,
                turn_id=turn_id,
                plan_id=replan_id,
            )
            for r in round_history:
                accumulated_context[r.step_number] = r
            history = history + round_history

        # 4. Summarise
        _log.info("Summarising...")
        _MAX_RESPONSE_CHARS = 2000
        results_text = "\n\n".join(
            f"Step {r.step_number} — {r.task} (server: {r.server}):\n"
            + (
                (r.response[:_MAX_RESPONSE_CHARS] + "... [truncated]"
                 if len(r.response) > _MAX_RESPONSE_CHARS else r.response)
                if r.success else f"ERROR: {r.error}"
            )
            for r in history
        )
        answer = self._llm.generate(
            _SUMMARIZE_PROMPT.format(question=question, results=results_text)
        )
        self._write_behavior(
            case_id=case_id,
            turn_id=turn_id,
            agent_role="summarizer",
            task_type="final_response",
            status="ok",
            input_step_numbers=[r.step_number for r in history],
            final_response=answer,
        )

        result = OrchestratorResult(
            question=question,
            answer=answer,
            plan=original_plan,
            replans=replans,
            history=history,
        )
        if session is not None:
            session.record_turn(question=question, answer=answer, history=history)
        return result

    def _write_behavior(self, *, case_id: str, **kwargs) -> None:
        if self._behavior_log is None:
            return
        self._behavior_log.write(case_id=case_id, **kwargs)

    @staticmethod
    def _make_case_id() -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        short = uuid.uuid4().hex[:6]
        return f"case_{ts}_{short}"

    @staticmethod
    def _resolve_reference_date(reference_date: str | None) -> str | None:
        if reference_date is None:
            return None
        return datetime.strptime(reference_date, "%Y-%m-%d").date().isoformat()
