"""Tests for the step-level validator (Phase 1)."""

from agent.artifacts import Artifact
from agent.models import PlanStepV2, StepResultV2, TaskStatus
from agent.validator import ValidationResult, validate_step


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
        status=TaskStatus.SUCCESS if error is None else TaskStatus.FAILED,
    )


def _artifact(step: int = 1) -> Artifact:
    return Artifact(
        artifact_type="raw_json",
        created_by_step=step,
        created_by_server="iot",
        summary="summary",
        raw_data="raw",
    )


class TestValidateStep:
    def test_success(self):
        v = validate_step(_step(), _result(), _artifact())
        assert v.passed is True
        assert v.action == "continue"

    def test_error_present_triggers_retry(self):
        v = validate_step(_step(), _result(error="timeout"), _artifact())
        assert v.passed is False
        assert v.action == "retry"
        assert "timeout" in v.reason

    def test_empty_response_triggers_retry(self):
        v = validate_step(_step(), _result(response=""), _artifact())
        assert v.passed is False
        assert v.action == "retry"
        assert "Empty" in v.reason

    def test_whitespace_only_response_triggers_retry(self):
        v = validate_step(_step(), _result(response="   "), _artifact())
        assert v.passed is False
        assert v.action == "retry"

    def test_valid_json_passes(self):
        v = validate_step(_step(), _result(response='{"a": 1}'), _artifact())
        assert v.passed is True

    def test_invalid_json_triggers_retry(self):
        v = validate_step(_step(), _result(response='{invalid json}'), _artifact())
        assert v.passed is False
        assert v.action == "retry"
        assert "JSON" in v.reason

    def test_non_json_text_passes(self):
        v = validate_step(_step(), _result(response="plain text answer"), _artifact())
        assert v.passed is True

    def test_valid_json_array_passes(self):
        v = validate_step(_step(), _result(response='[1, 2, 3]'), _artifact())
        assert v.passed is True
