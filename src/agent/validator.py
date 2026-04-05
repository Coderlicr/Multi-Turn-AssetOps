"""Step-level validation for plan execution.

Phase 1: rule-based checks only (no LLM calls).
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from .artifacts import Artifact
from .models import PlanStepV2, StepResultV2


class ValidationResult(BaseModel):
    """Outcome of validating a single step execution."""

    passed: bool
    reason: str
    action: str = "continue"  # "continue" | "retry" | "replan"


def _looks_like_json(text: str) -> bool:
    """Check if text appears to be a JSON string."""
    stripped = text.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )


def validate_step(
    step: PlanStepV2,
    result: StepResultV2,
    artifact: Artifact,
) -> ValidationResult:
    """Rule-based post-execution validation -- no LLM needed.

    Checks:
      1. Tool call succeeded (no error).
      2. Response is non-empty.
      3. If response looks like JSON, it parses correctly.
    """
    # Check 1: error present
    if result.error:
        return ValidationResult(passed=False, reason=result.error, action="retry")

    # Check 2: empty response
    if not result.response or result.response.strip() == "":
        return ValidationResult(
            passed=False, reason="Empty response", action="retry"
        )

    # Check 3: JSON validity
    if _looks_like_json(result.response):
        try:
            json.loads(result.response)
        except json.JSONDecodeError:
            return ValidationResult(
                passed=False, reason="Invalid JSON in response", action="retry"
            )

    return ValidationResult(passed=True, reason="OK")
