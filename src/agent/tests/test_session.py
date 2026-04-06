"""Tests for the shared SessionState."""

from agent.models import PlanStepV2, StepResultV2
from agent.session import SessionState, make_summary


def _step(n: int, deps: list[int] | None = None, tool: str = "sites") -> PlanStepV2:
    return PlanStepV2(
        step_number=n,
        task=f"Task {n}",
        server="iot",
        tool=tool,
        dependencies=deps or [],
    )


def _result(
    n: int,
    response: str = "ok",
    error: str | None = None,
    attempts: int = 1,
) -> StepResultV2:
    return StepResultV2(
        step_number=n,
        task=f"Task {n}",
        server="iot",
        response=response,
        error=error,
        tool="sites",
        attempts=attempts,
    )


class TestMakeSummary:
    def test_short_text_unchanged(self):
        assert make_summary("hello", 200) == "hello"

    def test_long_text_truncated(self):
        text = "x" * 300
        result = make_summary(text, 200)
        assert len(result) == 200


class TestSessionState:
    def test_record_step_stores_result(self):
        session = SessionState(question="Q")
        session.record_step(_step(1), _result(1, response='{"sites":["MAIN"]}'))

        record = session.get_step(1)
        assert record is not None
        assert record.step_number == 1
        assert record.summary == '{"sites":["MAIN"]}'

    def test_record_step_populates_shared_memory(self):
        session = SessionState(question="Q")
        session.record_step(_step(1, tool="assets"), _result(1, response='{"assets":["CH-1"]}'))

        assert session.shared_memory["step_1"] == {"assets": ["CH-1"]}
        assert session.shared_memory["iot.assets"] == {"assets": ["CH-1"]}

    def test_non_json_response_kept_as_text(self):
        session = SessionState(question="Q")
        session.record_step(_step(1), _result(1, response="plain text"))

        assert session.shared_memory["step_1"] == "plain text"

    def test_lineage_follows_dependencies(self):
        session = SessionState(question="Q")
        session.record_step(_step(1), _result(1, response="one"))
        session.record_step(_step(2, deps=[1]), _result(2, response="two"))
        session.record_step(_step(3, deps=[2]), _result(3, response="three"))

        lineage = session.lineage(3)
        assert [record.step_number for record in lineage] == [1, 2, 3]

    def test_render_context_includes_failures(self):
        session = SessionState(question="Q")
        session.record_step(_step(1), _result(1, response="ok"))
        session.record_step(_step(2), _result(2, response="", error="boom"))

        assert session.render_context() == "Step 1: ok\nStep 2: ERROR: boom"
