"""Tests for turn-level and conversation-level multi-turn evaluation."""

from pathlib import Path

from benchmark.multi_turn_schema import load_scenarios
from evaluation.multi_turn import _bare_tool_name, answer_matches, score_conversation
from evaluation.multi_turn_compare import compare_reports

ROOT = Path(__file__).resolve().parents[3]


def _turn(answer: str, tool_groups: list[list[str]]) -> dict:
    return {
        "answer": answer,
        "trajectory": {
            "turns": [
                {
                    "tool_calls": [
                        {"name": f"maintie__{name}", "input": {}} for name in group
                    ]
                }
                for group in tool_groups
            ]
        },
    }


def test_answer_match_accepts_grounded_natural_language():
    assert answer_matches(
        "There are 347 replacements and 127 repairs.",
        {"replace": 347, "repair": 127},
    )


def test_tool_name_normalization_supports_every_mcp_server():
    assert _bare_tool_name("maintie__rank") == "rank"
    assert _bare_tool_name("iot__installed_sensors") == "installed_sensors"
    assert _bare_tool_name("fmsr.get_failure_modes") == "get_failure_modes"


def test_wtb01_perfect_trace_scores_all_turns():
    scenario = load_scenarios(ROOT / "benchmarks/multi_turn/data/wtb50.jsonl")[0]
    record = {
        "trajectory": {
            "user_turns": [
                _turn('{"replace":347,"repair":127}', [["count", "count"]]),
                _turn('{"top":[["Lines & drives",89]]}', [["rank"]]),
                _turn("Yes, change out is replacement.", []),
                _turn(
                    '{"top3":[["Lines & drives",89],["Engines & motors",44],'
                    '["Structural/mounting parts",36]]}',
                    [["rank"]],
                ),
            ]
        }
    }

    score = score_conversation(scenario, record)

    assert score["optimal_path_rate"] == 1.0
    assert score["accomplish_progress_rate"] == 1.0
    assert score["no_tool_decision_accuracy"] == 1.0
    assert score["context_retention"] == 1.0
    assert score["overall_task_success"] is True
    assert score["turns"][2]["answer_scored"] is False
    assert score["turns"][2]["answer_correct"] is None
    assert score["turns"][2]["turn_success"] is None


def test_compare_reports_calculates_single_vs_multi_turn_degradation():
    multi = {
        "results": [
            {
                "scenario_id": "WTB01",
                "overall_task_success": False,
                "accomplish_progress_rate": 0.5,
            }
        ]
    }
    single = {
        "results": [
            {
                "scenario_id": "ST-WTB01",
                "paired_scenario_id": "WTB01",
                "overall_task_success": True,
                "accomplish_progress_rate": 1.0,
            }
        ]
    }

    result = compare_reports(multi, single)

    assert result["paired_scenarios"] == 1
    assert result["multi_turn_degradation"] == 1.0
    assert result["apr_degradation"] == 0.5
