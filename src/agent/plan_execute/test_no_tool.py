from agent.plan_execute.planner import parse_plan


def test_parse_no_tool_turn():
    plan = parse_plan("#NoTool: Yes — 'change out' is annotated as Replace.")
    assert plan.steps == []
    assert plan.direct_answer == "Yes — 'change out' is annotated as Replace."


def test_real_plan_does_not_become_direct_answer():
    raw = """#Task1: Count replacements
#Server1: maintie
#Tool1: count
#Dependency1: None
#ExpectedOutput1: replacement count
#NoTool: ignore this stray line
"""
    plan = parse_plan(raw)
    assert len(plan.steps) == 1
    assert plan.direct_answer is None
