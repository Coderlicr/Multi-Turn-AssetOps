"""Tests for Phase 1 Pydantic models (PlanStepV2, PlanV2, StepResultV2)."""

from agent.plan_execute.models import Plan, PlanStep, StepResult
from agent.models import PlanStepV2, PlanV2, StepResultV2, TaskStatus


def _legacy_step(n: int, deps: list[int] | None = None) -> PlanStep:
    return PlanStep(
        step_number=n,
        task=f"Task {n}",
        server="iot",
        tool="sites",
        tool_args={},
        dependencies=deps or [],
        expected_output=f"output {n}",
    )


class TestPlanStepV2:
    def test_from_legacy(self):
        legacy = _legacy_step(1)
        v2 = PlanStepV2.from_legacy(legacy)
        assert v2.step_number == 1
        assert v2.task == "Task 1"
        assert v2.server == "iot"
        assert v2.tool == "sites"
        assert v2.status == TaskStatus.PENDING
        assert v2.max_retries == 2

    def test_defaults(self):
        v2 = PlanStepV2(step_number=1, task="t", server="s", tool="t")
        assert v2.preconditions == []
        assert v2.postconditions == []
        assert v2.status == TaskStatus.PENDING
        assert v2.max_retries == 2


class TestPlanV2:
    def test_from_legacy(self):
        plan = Plan(
            steps=[_legacy_step(1), _legacy_step(2, [1])],
            raw="raw text",
        )
        v2 = PlanV2.from_legacy(plan, question="Q?")
        assert len(v2.steps) == 2
        assert v2.original_question == "Q?"
        assert v2.steps[1].dependencies == [1]

    def test_independent_groups_no_deps(self):
        plan = PlanV2(
            steps=[
                PlanStepV2(step_number=1, task="A", server="s", tool="t"),
                PlanStepV2(step_number=2, task="B", server="s", tool="t"),
            ],
        )
        groups = plan.independent_groups()
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_independent_groups_chain(self):
        plan = PlanV2(
            steps=[
                PlanStepV2(step_number=1, task="A", server="s", tool="t"),
                PlanStepV2(step_number=2, task="B", server="s", tool="t", dependencies=[1]),
                PlanStepV2(step_number=3, task="C", server="s", tool="t", dependencies=[2]),
            ],
        )
        groups = plan.independent_groups()
        assert len(groups) == 3
        assert groups[0][0].step_number == 1
        assert groups[1][0].step_number == 2
        assert groups[2][0].step_number == 3

    def test_independent_groups_diamond(self):
        plan = PlanV2(
            steps=[
                PlanStepV2(step_number=1, task="A", server="s", tool="t"),
                PlanStepV2(step_number=2, task="B", server="s", tool="t", dependencies=[1]),
                PlanStepV2(step_number=3, task="C", server="s", tool="t", dependencies=[1]),
                PlanStepV2(step_number=4, task="D", server="s", tool="t", dependencies=[2, 3]),
            ],
        )
        groups = plan.independent_groups()
        assert len(groups) == 3
        # Group 0: step 1
        # Group 1: steps 2 and 3 (both depend only on 1)
        # Group 2: step 4
        assert {s.step_number for s in groups[1]} == {2, 3}

    def test_independent_groups_empty(self):
        plan = PlanV2(steps=[])
        assert plan.independent_groups() == []


class TestStepResultV2:
    def test_from_legacy_success(self):
        legacy = StepResult(step_number=1, task="t", server="s", response="ok")
        v2 = StepResultV2.from_legacy(legacy)
        assert v2.success is True
        assert v2.status == TaskStatus.SUCCESS
        assert v2.attempts == 1

    def test_from_legacy_failure(self):
        legacy = StepResult(
            step_number=1, task="t", server="s", response="", error="oops"
        )
        v2 = StepResultV2.from_legacy(legacy)
        assert v2.success is False
        assert v2.status == TaskStatus.FAILED

    def test_success_property(self):
        r = StepResultV2(step_number=1, task="t", server="s", response="ok")
        assert r.success is True
        r2 = StepResultV2(
            step_number=1, task="t", server="s", response="", error="fail"
        )
        assert r2.success is False


class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.SUCCESS == "success"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.SKIPPED == "skipped"
