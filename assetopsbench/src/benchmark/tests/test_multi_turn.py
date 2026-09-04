"""Tests for the unified multi-turn schema and runner selection."""

from pathlib import Path

import pytest

from benchmark.multi_turn_runner import select_scenarios, server_paths_for
from benchmark.multi_turn_schema import load_scenarios


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
