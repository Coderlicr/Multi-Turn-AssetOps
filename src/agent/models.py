"""Data models for the agent orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .plan_execute.models import Plan, PlanStep, StepResult


# ── Phase 1: Strong-typed Pydantic wrappers ─────────────────────────────────


class TaskStatus(str, Enum):
    """Lifecycle status of a single plan step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStepV2(BaseModel):
    """Pydantic wrapper for a single step — created *after* text-parse."""

    step_number: int
    task: str
    server: str
    tool: str
    tool_args: dict = Field(default_factory=dict)
    dependencies: list[int] = Field(default_factory=list)
    expected_output: str = ""
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    max_retries: int = 2

    @classmethod
    def from_legacy(cls, step: PlanStep) -> PlanStepV2:
        """Wrap an existing dataclass PlanStep."""
        return cls(
            step_number=step.step_number,
            task=step.task,
            server=step.server,
            tool=step.tool,
            tool_args=step.tool_args,
            dependencies=step.dependencies,
            expected_output=step.expected_output,
        )


class PlanV2(BaseModel):
    """Pydantic wrapper for a full plan — created *after* text-parse."""

    steps: list[PlanStepV2]
    original_question: str = ""

    @classmethod
    def from_legacy(cls, plan: Plan, question: str = "") -> PlanV2:
        """Wrap an existing dataclass Plan."""
        return cls(
            steps=[PlanStepV2.from_legacy(s) for s in plan.steps],
            original_question=question,
        )

    def independent_groups(self) -> list[list[PlanStepV2]]:
        """Return groups of steps that can execute in parallel.

        Steps whose dependencies are all already completed form a group.
        """
        completed: set[int] = set()
        groups: list[list[PlanStepV2]] = []
        remaining = list(self.steps)

        while remaining:
            group = [
                s for s in remaining
                if all(d in completed for d in s.dependencies)
            ]
            if not group:
                break  # circular or unresolvable
            groups.append(group)
            for s in group:
                completed.add(s.step_number)
            remaining = [s for s in remaining if s.step_number not in completed]

        return groups


class StepResultV2(BaseModel):
    """Pydantic wrapper for a step execution result."""

    step_number: int
    task: str
    server: str
    response: str = ""
    error: Optional[str] = None
    tool: str = ""
    tool_args: dict = Field(default_factory=dict)
    attempts: int = 0

    @property
    def success(self) -> bool:
        return self.error is None

    @classmethod
    def from_legacy(cls, result: StepResult) -> StepResultV2:
        """Wrap an existing dataclass StepResult."""
        return cls(
            step_number=result.step_number,
            task=result.task,
            server=result.server,
            response=result.response,
            error=result.error,
            tool=result.tool,
            tool_args=result.tool_args,
            attempts=1,
        )


# ── Original orchestrator result (unchanged interface) ──────────────────────


@dataclass
class OrchestratorResult:
    """Final result from the plan-execute orchestrator."""

    question: str
    answer: str
    plan: Plan
    history: list[StepResult]
