"""LLM-based plan generation for the plan-execute orchestrator.

Each plan step now includes the specific tool to call and its arguments,
so the executor needs no additional LLM calls — it calls the tool directly.
"""

from __future__ import annotations

import logging
import re

from llm import LLMBackend
from .models import Plan, PlanStep
from ..models import PlanV2, PlanStepV2, StepResultV2

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
#Tool1: <exact tool name, or "none" if no tool call is needed>
#Dependency1: None
#ExpectedOutput1: <what this step should produce>

#Task2: <task description>
#Server2: <exact server name>
#Tool2: <exact tool name>
#Dependency2: #S1
#ExpectedOutput2: <what this step should produce>

Rules:
- Server and tool names must exactly match those listed above.
- Server must always be a real server name from the list above; never use "none" or "null" for a server.
- Dependencies use #S<N> notation (e.g., #S1, #S2). Use "None" if none.
- Keep tasks specific and actionable.

Question: {question}

Plan:
"""

_REPLAN_PROMPT = """\
You are a planning assistant for industrial asset operations and maintenance.

A previous plan partially failed. Re-plan only the remaining steps to answer
the original question, taking into account what already succeeded and what
went wrong.

Available servers and tools:
{servers}

Already completed steps:
{completed_steps}

Failed step:
{failed_step}
Failure reason: {failure_reason}

Remaining steps that were not attempted:
{remaining_steps}

Create a new plan for the remaining work. Use the same output format:

#Task1: <task description>
#Server1: <exact server name>
#Tool1: <exact tool name, or "none" if no tool call is needed>
#Dependency1: None
#ExpectedOutput1: <what this step should produce>

Rules:
- Server and tool names must exactly match those listed above.
- Server must always be a real server name from the list above; never use "none" or "null" for a server.
- Dependencies use #S<N> notation (e.g., #S1, #S2). Use "None" if none.
- Step numbering restarts from 1.
- You may use different tools or servers to work around the failure.

Original question: {question}

Plan:
"""

_TASK_RE = re.compile(r"#Task(\d+):\s*(.+)")
_SERVER_RE = re.compile(r"#Server(\d+):\s*(.+)")
_TOOL_RE = re.compile(r"#Tool(\d+):\s*(.+)")
_DEP_RE = re.compile(r"#Dependency(\d+):\s*(.+)")
_OUTPUT_RE = re.compile(r"#ExpectedOutput(\d+):\s*(.+)")
_DEP_NUM_RE = re.compile(r"#S(\d+)")


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

    return Plan(steps=steps, raw=raw)


class Planner:
    """Decomposes a question into a structured execution plan using an LLM."""

    def __init__(self, llm: LLMBackend) -> None:
        self._llm = llm

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

    def replan(
        self,
        original_question: str,
        server_descriptions: dict[str, str],
        completed: list[StepResultV2],
        failed: StepResultV2,
        remaining: list[PlanStepV2],
    ) -> Plan:
        """Generate a replacement plan for remaining work after a step failure.

        Uses the same text-format prompt/parse pipeline as generate_plan,
        but injects completed-step context and the failure reason so the
        LLM can route around the problem.
        """
        servers_text = "\n\n".join(
            f"{name}:\n{desc}" for name, desc in server_descriptions.items()
        )

        completed_text = "\n".join(
            f"  Step {r.step_number} ({r.server}): {r.task} -> {r.response[:120]}"
            for r in completed
        )
        remaining_text = "\n".join(
            f"  Step {s.step_number}: {s.task}" for s in remaining
        )

        prompt = _REPLAN_PROMPT.format(
            servers=servers_text,
            question=original_question,
            completed_steps=completed_text or "(none)",
            failed_step=f"Step {failed.step_number} ({failed.server}): {failed.task}",
            failure_reason=failed.error or "unknown",
            remaining_steps=remaining_text or "(none)",
        )
        raw = self._llm.generate(prompt)
        return parse_plan(raw)
