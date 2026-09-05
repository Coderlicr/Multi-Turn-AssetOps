"""Tests for the unified multi-turn schema and runner selection."""

import json
from pathlib import Path

import pytest

from benchmark.multi_turn_runner import (
    prepare_couchdb_state,
    scenario_manifest,
    select_scenarios,
    server_paths_for,
)
from benchmark.multi_turn_schema import load_scenarios
from evaluation.scorers.static_json import evaluate_static_json

ROOT = Path(__file__).resolve().parents[3]


def test_built_dataset_has_16_development_and_50_main_scenarios():
    development = load_scenarios(ROOT / "benchmarks/multi_turn/data/assetops16.jsonl")
    main = load_scenarios(ROOT / "benchmarks/multi_turn/data/wtb50.jsonl")
    controls = load_scenarios(
        ROOT / "benchmarks/multi_turn/data/wtb50_single_turn.jsonl"
    )

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


def test_wtb_scenario_resolves_only_maintie_server():
    scenarios = load_scenarios(ROOT / "benchmarks/multi_turn/data/wtb50.jsonl")
    selected = select_scenarios(scenarios, "WTB01")

    assert [scenario.scenario_id for scenario in selected] == ["WTB01"]
    assert server_paths_for(selected[0]) == {"maintie": "maintie-mcp-server"}


def test_unknown_scenario_is_rejected():
    scenarios = load_scenarios(ROOT / "benchmarks/multi_turn/data/wtb50.jsonl")
    with pytest.raises(ValueError, match="Unknown scenario"):
        select_scenarios(scenarios, "missing")


def test_folder_pilot_loads_one_old_and_one_new_scenario():
    scenario_root = ROOT / "src/couchdb/scenarios_data"

    scenarios = load_scenarios(scenario_root)

    assert [scenario.scenario_id for scenario in scenarios] == ["A16-06", "WTB01"]
    assert all(scenario.executable for scenario in scenarios)
    assert scenarios[0].turns[-1].ground_truth == {
        "failure_modes": [
            "condenser fouling",
            "refrigerant leakage",
            "compressor oil pressure loss",
        ]
    }
    assert scenarios[1].turns[-1].ground_truth["top3"][0] == [
        "Lines & drives",
        89,
    ]


def test_folder_manifests_declare_database_requirement():
    scenario_root = ROOT / "src/couchdb/scenarios_data"

    assert scenario_manifest(scenario_root, "A16-06")
    assert scenario_manifest(scenario_root, "WTB01") == {}
    assert prepare_couchdb_state(scenario_root, "A16-06", dry_run=True) is True
    assert prepare_couchdb_state(scenario_root, "WTB01", dry_run=True) is False


def test_folder_pilot_final_truths_pass_the_standard_static_json_scorer():
    scenario_root = ROOT / "src/couchdb/scenarios_data"

    for scenario in load_scenarios(scenario_root):
        folder = scenario_root / f"scenario_{scenario.scenario_id}"
        gold = (folder / "groundtruth.txt").read_text(encoding="utf-8")
        model_answer = json.dumps(scenario.turns[-1].ground_truth)

        score = evaluate_static_json(gold, model_answer)

        assert score.strict_exact_match_accuracy == 1.0
