"""Tests for the step-level validator (Phase 1)."""

from agent.models import PlanStepV2, StepResultV2
from agent.validator import validate_step


def _step(n: int = 1) -> PlanStepV2:
    return PlanStepV2(
        step_number=n,
        task=f"Task {n}",
        server="iot",
        tool="sites",
    )


def _result(
    response: str = "ok",
    error: str | None = None,
    n: int = 1,
) -> StepResultV2:
    return StepResultV2(
        step_number=n,
        task=f"Task {n}",
        server="iot",
        response=response,
        error=error,
    )


class TestValidateStep:
    def test_success(self):
        v = validate_step(_step(), _result())
        assert v.passed is True
        assert v.action == "continue"

    def test_error_present_triggers_retry(self):
        v = validate_step(_step(), _result(error="timeout"))
        assert v.passed is False
        assert v.action == "retry"
        assert "timeout" in v.reason

    def test_empty_response_triggers_retry(self):
        v = validate_step(_step(), _result(response=""))
        assert v.passed is False
        assert v.action == "retry"
        assert "Empty" in v.reason

    def test_whitespace_only_response_triggers_retry(self):
        v = validate_step(_step(), _result(response="   "))
        assert v.passed is False
        assert v.action == "retry"

    def test_valid_json_passes(self):
        v = validate_step(_step(), _result(response='{"a": 1}'))
        assert v.passed is True

    def test_invalid_json_triggers_retry(self):
        v = validate_step(_step(), _result(response='{invalid json}'))
        assert v.passed is False
        assert v.action == "retry"
        assert "JSON" in v.reason

    def test_non_json_text_passes(self):
        v = validate_step(_step(), _result(response="plain text answer"))
        assert v.passed is True

    def test_valid_json_array_passes(self):
        v = validate_step(_step(), _result(response='[1, 2, 3]'))
        assert v.passed is True
