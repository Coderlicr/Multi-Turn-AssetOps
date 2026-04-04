"""Data models for the agent orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass

from .plan_execute.models import Plan, StepResult


@dataclass
class OrchestratorResult:
    """Final result from the plan-execute orchestrator."""

    question: str
    answer: str
    plan: Plan
    history: list[StepResult]
