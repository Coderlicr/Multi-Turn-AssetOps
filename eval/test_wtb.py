from copy import deepcopy

from eval.wtb_scenarios import WTB_SCENARIOS
from eval.wtb_score import score_dialog


def test_wtb_scenarios_are_complete_and_aligned():
    assert len(WTB_SCENARIOS) == 50
    assert sum(len(scenario["turns"]) for scenario in WTB_SCENARIOS) == 152
    assert WTB_SCENARIOS[0]["id"] == 1
    assert WTB_SCENARIOS[0]["scenario_id"] == "WTB01"
    assert WTB_SCENARIOS[-1]["id"] == 50
    assert WTB_SCENARIOS[-1]["scenario_id"] == "WTB50"
    assert all("[task]" not in turn for scenario in WTB_SCENARIOS for turn in scenario["turns"])


def test_perfect_trace_scores_one():
    gold = [
        {"tools": [["a", "b"]], "result": {"n": 2}, "judge": False},
        {"tools": [], "result": None, "judge": False},
    ]
    agent = deepcopy(gold)
    score = score_dialog(agent, gold)
    assert score["optimal_path_rate"] == 1.0
    assert score["accomplish_progress_rate"] == 1.0
    assert score["no_tool_decision_accuracy"] == 1.0


def test_parallel_order_does_not_matter_but_serial_order_does():
    gold = [{"tools": [["a", "b"]], "result": None, "judge": False}]
    assert score_dialog([{"tools": [["b", "a"]]}], gold)["optimal_path_rate"] == 1.0
    assert score_dialog([{"tools": [["a"], ["b"]]}], gold)["optimal_path_rate"] == 0.0


def test_missing_turn_is_not_dropped_from_apr_denominator():
    gold = [
        {"tools": [["a"]], "result": {"n": 1}, "judge": False},
        {"tools": [["b"]], "result": {"n": 2}, "judge": False},
    ]
    score = score_dialog([{"tools": [["a"]], "result": {"n": 1}}], gold)
    assert score["accomplish_progress_rate"] == 0.5
    assert score["missing_turns"] == 1


def test_extra_turn_is_penalized_in_path_rate():
    gold = [{"tools": [], "result": None, "judge": False}]
    agent = [{"tools": []}, {"tools": [["extra"]]}]
    score = score_dialog(agent, gold)
    assert score["optimal_path_rate"] == 0.5
    assert score["extra_turns"] == 1


def test_judge_turn_is_not_counted_as_exact_result_apr():
    gold = [{"tools": [["compose"]], "result": {"target": "x"}, "judge": True}]
    score = score_dialog([{"tools": [["compose"]], "result": {"target": "wrong"}}], gold)
    assert score["accomplish_progress_rate"] is None
    assert score["compute_turns"] == 0
