"""LLM-based plan generation for the plan-execute orchestrator.

Each plan step now includes the specific tool to call and its arguments,
so the executor needs no additional LLM calls — it calls the tool directly.
"""

from __future__ import annotations

import logging
import re

from llm import LLMBackend
from .models import Plan, PlanStep

_log = logging.getLogger(__name__)

_PLAN_PROMPT = """\
You are a planning assistant for industrial asset operations and maintenance.

Decompose the question below into a sequence of subtasks. For each subtask,
assign a server and select the exact tool to call. Do NOT include tool arguments —
they will be resolved at execution time from the task description and prior results.

Available servers and tools:
{servers}

Output format — one block per step, exactly:

#Task1: <task description>
#Server1: <exact server name>
#Tool1: <exact tool name>
#Dependency1: None
#ExpectedOutput1: <what this step should produce>

#Task2: <task description>
#Server2: <exact server name>
#Tool2: <exact tool name>
#Dependency2: #S1
#ExpectedOutput2: <what this step should produce>

If the current turn is only chat, acknowledgement, or a clarification that can
be answered from the recent conversation or the tool descriptions, do not call
a tool. Output exactly one line instead:
#NoTool: <concise direct response>

Rules:
- Server and tool names must exactly match those listed above.
- Every planned step must call a real tool. Never invent tool="none" or server="none"; use #NoTool for a turn that needs no tool.
- Dependencies use #S<N> notation (e.g., #S1, #S2). Use "None" if none.
- Keep tasks specific and actionable.
- CRITICAL: The tools sensors, history_csv, and history only support ONE asset per call. You MUST create one step per asset. Example — for Chiller 6 and Chiller 9: create step A "Get sensors for Chiller 6" AND step B "Get sensors for Chiller 9". NEVER write "Get sensors for Chiller 6 and Chiller 9" as a single step.
Question: {question}

Plan:
"""

_REPLAN_PROMPT = """\
You are a planning assistant for industrial asset operations and maintenance.

A previous plan partially failed during execution. Your job is to produce \
ONLY the remaining steps needed to complete the original goal, taking into \
account what has already succeeded and what went wrong.

Original question: {question}

Original plan:
{original_plan}

Execution results so far (successful and failed):
{execution_history}

Failed steps and their errors:
{failed_steps}

Output ONLY the new/replacement steps using the same format as before.
Number steps starting from {next_step_number}.
Reference earlier completed steps with #S<N> in dependencies if needed.

Available servers and tools:
{servers}

Output format — one block per step, exactly:

#Task{next_step_number}: <task description>
#Server{next_step_number}: <exact server name>
#Tool{next_step_number}: <exact tool name>
#Dependency{next_step_number}: None  (or #S<N> for dependencies)
#ExpectedOutput{next_step_number}: <what this step should produce>

Rules:
- Server and tool names must exactly match those listed above.
- Only output steps that still need to be done.
- If a failed step can be retried with a different tool or approach, include it.
- Do NOT re-run steps that already succeeded.
- If the same tool has failed multiple times for the same reason, do NOT retry it again. Choose a fundamentally different tool or approach instead.
- CRITICAL: The tools sensors, history_csv, and history only support ONE asset per call. You MUST create one step per asset — never combine two assets into a single step for these tools.

New steps:
"""

_TASK_RE = re.compile(r"#Task(\d+):\s*(.+)")
_SERVER_RE = re.compile(r"#Server(\d+):\s*(.+)")
_TOOL_RE = re.compile(r"#Tool(\d+):\s*(.+)")
_DEP_RE = re.compile(r"#Dependency(\d+):\s*(.+)")
_OUTPUT_RE = re.compile(r"#ExpectedOutput(\d+):\s*(.+)")
_DEP_NUM_RE = re.compile(r"#S(\d+)")
_NO_TOOL_RE = re.compile(r"#NoTool:\s*(.+)")


def parse_plan(raw: str) -> Plan:
    """Parse an LLM-generated plan string into a Plan object."""
    tasks = {int(m.group(1)): m.group(2).strip() for m in _TASK_RE.finditer(raw)}
    servers = {int(m.group(1)): m.group(2).strip() for m in _SERVER_RE.finditer(raw)}
    # Strip any trailing signature the LLM may copy from the server description
    # format "tool_name(param: type)" — only the bare name is needed.
    tools = {
        int(m.group(1)): m.group(2).strip().split("(")[0].strip()
        for m in _TOOL_RE.finditer(raw)
    }
    deps_raw = {int(m.group(1)): m.group(2).strip() for m in _DEP_RE.finditer(raw)}
    outputs = {int(m.group(1)): m.group(2).strip() for m in _OUTPUT_RE.finditer(raw)}

    steps = []
    for n in sorted(tasks):
        raw_dep = deps_raw.get(n, "None").strip()

        if raw_dep.lower() == "none":
            dependencies = []
        else:
            dependencies = [int(x) for x in _DEP_NUM_RE.findall(raw_dep)]

            # Make sure dependency references only point to earlier valid steps.
            if not dependencies:
                raise ValueError(f"Invalid dependency format for step {n}: {raw_dep}")

            for dep in dependencies:
                if dep < 1 or dep >= n:
                    raise ValueError(
                        f"Invalid dependency reference for step {n}: #S{dep}"
                    )

        steps.append(
            PlanStep(
                step_number=n,
                task=tasks[n],
                server=servers.get(n, ""),
                tool=tools.get(n, ""),
                tool_args={},
                dependencies=dependencies,
                expected_output=outputs.get(n, ""),
            )
        )

    no_tool = _NO_TOOL_RE.search(raw)
    return Plan(
        steps=steps,
        raw=raw,
        direct_answer=no_tool.group(1).strip() if no_tool and not steps else None,
    )


class Planner:
    """Decomposes a question into a structured execution plan using an LLM."""

    def __init__(self, llm: LLMBackend) -> None:
        self._llm = llm

    def generate_replan(
        self,
        question: str,
        original_plan: Plan,
        history: list,
        server_descriptions: dict[str, str],
        next_step_number: int | None = None,
    ) -> Plan:
        """Generate replacement steps for failed parts of a plan.

        Args:
            question: The original user question.
            original_plan: The plan that was partially executed.
            history: StepResult list from the partial execution.
            server_descriptions: Mapping of server_name -> formatted tool signatures.

        Returns:
            A Plan containing only the new steps to execute.
        """
        _MAX_RESP = 500
        history_text = "\n".join(
            f"Step {r.step_number} [{r.server}/{r.tool}] "
            + ("OK: " + r.response[:_MAX_RESP] if r.success else f"FAILED: {r.error}")
            for r in history
        )
        failed_text = "\n".join(
            f"Step {r.step_number} ({r.task}): {r.error}"
            for r in history
            if not r.success
        )
        next_n = next_step_number if next_step_number is not None else (
            max((r.step_number for r in history), default=0) + 1
        )
        servers_text = "\n\n".join(
            f"{name}:\n{desc}" for name, desc in server_descriptions.items()
        )
        prompt = _REPLAN_PROMPT.format(
            question=question,
            original_plan=original_plan.raw,
            execution_history=history_text or "(none)",
            failed_steps=failed_text or "(none)",
            next_step_number=next_n,
            servers=servers_text,
        )
        raw = self._llm.generate(prompt)
        return parse_plan(raw)

    def generate_plan(
        self,
        question: str,
        server_descriptions: dict[str, str],
    ) -> Plan:
        """Generate a plan for a question given available servers and their tools.

        Args:
            question: The user question to answer.
            server_descriptions: Mapping of server_name -> formatted tool signatures.

        Returns:
            A Plan where each PlanStep includes the tool to call and its arguments.
        """
        servers_text = "\n\n".join(
            f"{name}:\n{desc}" for name, desc in server_descriptions.items()
        )
        prompt = _PLAN_PROMPT.format(servers=servers_text, question=question)
        raw = self._llm.generate(prompt)
        return parse_plan(raw)
