"""Shared session state for a single plan-execute run."""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

from .models import PlanStepV2, StepResultV2, TaskStatus


def _coerce_shared_value(text: str) -> Any:
    """Parse JSON-looking text into Python values; otherwise keep the raw text."""
    stripped = text.strip()
    if not stripped:
        return ""
    if (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    ):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return text
    return text


def make_summary(text: str, max_chars: int = 200) -> str:
    """Build a short summary suitable for logs or LLM context."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


class SessionStepData(BaseModel):
    """Normalized step data stored in the shared session state."""

    step_number: int
    task: str
    server: str
    tool: str
    response: str = ""
    error: Optional[str] = None
    summary: str = ""
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    depends_on_steps: list[int] = Field(default_factory=list)
    shared_value: Any = None


class SessionState(BaseModel):
    """In-memory shared state for a single query execution."""

    question: str = ""
    steps: dict[int, SessionStepData] = Field(default_factory=dict)
    shared_memory: dict[str, Any] = Field(default_factory=dict)

    def record_step(self, step: PlanStepV2, result: StepResultV2) -> SessionStepData:
        """Persist the latest final state for a plan step into the session."""
        shared_value = _coerce_shared_value(result.response)
        record = SessionStepData(
            step_number=step.step_number,
            task=step.task,
            server=step.server,
            tool=step.tool,
            response=result.response,
            error=result.error,
            summary=make_summary(result.response),
            status=TaskStatus.SUCCESS if result.success else TaskStatus.FAILED,
            attempts=result.attempts,
            depends_on_steps=list(step.dependencies),
            shared_value=shared_value,
        )
        self.steps[step.step_number] = record
        self.shared_memory[f"step_{step.step_number}"] = shared_value
        if step.tool and step.tool.lower() not in ("none", "null"):
            self.shared_memory[f"{step.server}.{step.tool}"] = shared_value
        return record

    def get_step(self, step_number: int) -> Optional[SessionStepData]:
        """Return the recorded session data for a step, if present."""
        return self.steps.get(step_number)

    def lineage(self, step_number: int) -> list[SessionStepData]:
        """Return upstream records followed by the target step."""
        visited: set[int] = set()
        ordered: list[SessionStepData] = []

        def _walk(n: int) -> None:
            if n in visited:
                return
            visited.add(n)
            record = self.steps.get(n)
            if record is None:
                return
            for dep in record.depends_on_steps:
                _walk(dep)
            ordered.append(record)

        _walk(step_number)
        return ordered

    def render_context(self) -> str:
        """Render final step outcomes into a compact LLM context block."""
        lines = [
            f"Step {n}: {record.response if record.error is None else f'ERROR: {record.error}'}"
            for n, record in sorted(self.steps.items())
        ]
        return "\n".join(lines)
