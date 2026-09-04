import json
from pathlib import Path

from stirrup_benchmark.compare import compare_reports
from stirrup_benchmark.evaluate import answer_matches, evaluate_files
from stirrup_benchmark.schema import load_scenarios

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_dataset_shape():
    development = load_scenarios(ROOT / "data/assetops16.jsonl")
    main = load_scenarios(ROOT / "data/wtb50.jsonl")
    controls = load_scenarios(ROOT / "data/wtb50_single_turn.jsonl")

    assert len(development) == 16
    assert len(main) == 50
    assert len(controls) == 50
    assert sum(len(scenario.turns) for scenario in development + main) == 215
    assert not any(scenario.executable for scenario in development)
    assert all(scenario.executable and scenario.valid_multi_turn for scenario in main)
    assert all(
        not scenario.valid_multi_turn
        and len(scenario.turns) == 1
        and scenario.paired_scenario_id
        for scenario in controls
    )


def test_natural_language_answer_matching():
    assert answer_matches(
        "There are 347 replacements and 127 repairs.",
        {"replace": 347, "repair": 127},
    )


def test_bundled_real_poc_scores_successfully():
    report = evaluate_files(ROOT / "data/wtb50.jsonl", ROOT / "poc/trajectories")

    assert report["scenario_count"] == 1
    assert report["accomplish_progress_rate"] == 1.0
    assert report["overall_task_success_rate"] == 1.0
    assert report["results"][0]["user_turns_observed"] == 4
    assert report["results"][0]["turns"][2]["answer_scored"] is False


def test_compare_reports_computes_degradation():
    result = compare_reports(
        {
            "results": [
                {
                    "scenario_id": "WTB01",
                    "overall_task_success": False,
                    "accomplish_progress_rate": 0.5,
                }
            ]
        },
        {
            "results": [
                {
                    "scenario_id": "ST-WTB01",
                    "paired_scenario_id": "WTB01",
                    "overall_task_success": True,
                    "accomplish_progress_rate": 1.0,
                }
            ]
        },
    )

    assert result["paired_scenarios"] == 1
    assert result["multi_turn_degradation"] == 1.0
    assert result["apr_degradation"] == 0.5


def test_poc_contains_no_credentials():
    content = json.dumps(
        json.loads(
            (ROOT / "poc/trajectories/stirrup_mt_WTB01.json").read_text(
                encoding="utf-8"
            )
        )
    )
    assert "api_key" not in content.casefold()
    assert "sk-" not in content.casefold()
