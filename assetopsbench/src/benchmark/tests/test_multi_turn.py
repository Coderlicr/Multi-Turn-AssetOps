"""Tests for the unified multi-turn schema and runner selection."""

import asyncio
import json
from pathlib import Path

import pytest

from benchmark.multi_turn_runner import (
    _build_parser,
    _PacedClient,
    _run,
    prepare_couchdb_state,
    scenario_manifest,
    select_scenarios,
    server_paths_for,
)
from benchmark.multi_turn_schema import load_scenarios, parse_question
from evaluation.scorers.static_json import evaluate_static_json

ROOT = Path(__file__).resolve().parents[3]


def test_request_pacing_preserves_client_messages_and_response(monkeypatch):
    waits, received = [], []
    response = object()

    class Client:
        model_slug = "model"

        async def generate(self, messages, tools):
            received.append((messages, tools))
            return response

    async def sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    async def run():
        client = _PacedClient(Client(), 8.0)
        assert client.model_slug == "model"
        assert await client.generate(["first"], {}) is response
        assert await client.generate(["second"], {}) is response

    asyncio.run(run())
    assert received == [(["first"], {}), (["second"], {})]
    assert len(waits) == 1
    assert 7.0 < waits[0] <= 8.0


def test_question_preserves_multiline_messages():
    assert parse_question(
        "User turn 1:\nFirst line\nSecond line\n\nUser turn 2:\nAnd that?"
    ) == ["First line\nSecond line", "And that?"]


@pytest.mark.parametrize(
    "text",
    [
        "User turn 2:\nMissing first",
        "User turn 1:\nA\nUser turn 1:\nB",
        "User turn 1:\n\nUser turn 2:\nB",
        "Preamble\nUser turn 1:\nA",
    ],
)
def test_question_rejects_ambiguous_turns(text):
    with pytest.raises(ValueError):
        parse_question(text)


def test_wtb_folder_needs_only_three_files(tmp_path):
    folder = tmp_path / "scenario_WTB01"
    folder.mkdir()
    original = ROOT / "src/couchdb/scenarios_data/scenario_WTB01"
    for name in ("question.txt", "manifest.json", "groundtruth.txt"):
        (folder / name).write_text((original / name).read_text())
    (scenario,) = load_scenarios(tmp_path)
    assert len(scenario.turns) == 4
    assert scenario.required_tools == ["maintie"]
    assert "top three" in scenario.turns[-1].user_message
    assert all(t.ground_truth is None for t in scenario.turns[:-1])
    assert scenario.turns[-1].ground_truth == json.loads(
        (folder / "groundtruth.txt").read_text()
    )


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
    assert not scenarios[0].executable
    assert scenarios[0].turns[-1].ground_truth is None
    assert scenarios[1].executable
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
        if not scenario.executable:
            continue
        folder = scenario_root / f"scenario_{scenario.scenario_id}"
        gold = (folder / "groundtruth.txt").read_text(encoding="utf-8")
        model_answer = json.dumps(scenario.turns[-1].ground_truth)

        score = evaluate_static_json(gold, model_answer)

        assert score.strict_exact_match_accuracy == 1.0


def test_missing_truth_blocks_run_before_environment_mutation(tmp_path):
    args = _build_parser().parse_args(
        [
            "--scenarios",
            str(ROOT / "src/couchdb/scenarios_data"),
            "--scenario-ids",
            "A16-06",
            "--trajectory-dir",
            str(tmp_path / "output"),
        ]
    )
    with pytest.raises(ValueError, match="Formal run suspended: A16-06"):
        asyncio.run(_run(args))
    assert not (tmp_path / "output").exists()


def test_standard_evaluator_excludes_suspended_scenario():
    from evaluation.loader import load_scenarios as load_evaluation_scenarios

    scenarios = load_evaluation_scenarios(ROOT / "src/couchdb/scenarios_data")
    assert "A16-06" not in {s.id for s in scenarios}
    assert "WTB01" in {s.id for s in scenarios}


def test_pilot_directories_have_exactly_three_files():
    for scenario_id in ["A16-06", "WTB01"]:
        folder = ROOT / "src/couchdb/scenarios_data" / f"scenario_{scenario_id}"
        assert {p.name for p in folder.iterdir()} == {
            "manifest.json",
            "question.txt",
            "groundtruth.txt",
        }
