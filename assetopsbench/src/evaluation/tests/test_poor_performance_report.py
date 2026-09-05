"""Tests for the poor-scenario-only reporting view."""

from evaluation.poor_performance_report import build_poor_performance_report


def test_poor_report_omits_strict_passes():
    report = {
        "generated_at": "2026-09-05T00:00:00Z",
        "results": [
            {
                "scenario_id": "pass",
                "run_id": "run-pass",
                "model": "m",
                "answer": '{"x": 1}',
                "score": {
                    "passed": True,
                    "score": 1.0,
                    "details": {"strict_exact_match_accuracy": 1.0},
                },
            },
            {
                "scenario_id": "poor",
                "run_id": "run-poor",
                "model": "m",
                "answer": '{"x": 2}',
                "score": {
                    "passed": False,
                    "score": 0.0,
                    "rationale": "structured answer differs from ground truth",
                    "details": {
                        "strict_exact_match_accuracy": 0.0,
                        "missing_keys": ["x"],
                        "extra_keys": [],
                    },
                },
            },
        ],
    }

    reduced = build_poor_performance_report(report)

    assert reduced["scenarios_evaluated"] == 2
    assert reduced["poor_scenario_count"] == 1
    assert [item["scenario_id"] for item in reduced["poor_scenarios"]] == ["poor"]
