#!/usr/bin/env python3
"""Standardize and audit the 16 legacy dialogs plus the 50 Mentor dialogs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .schema import DependencyType, MultiTurnScenario, TurnSpec


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "source"
OUTPUT = ROOT / "data"

_HEADING_RE = re.compile(r"^## (WTB\d{2}) — (.+)$")
_TURN_RE = re.compile(r"^- \*\*\[(task|follow|clarify|chat)\]\*\* (.+)$")

_ASSETOPS_TOOLS = {
    1: ["iot", "tsfm", "fmsr"],
    2: ["iot", "tsfm", "fmsr"],
    3: ["iot", "tsfm"],
    4: ["wo", "fmsr"],
    5: ["iot", "tsfm", "wo"],
    6: ["iot", "fmsr", "tsfm"],
    7: ["iot", "tsfm", "fmsr"],
    8: ["fmsr", "iot", "tsfm"],
    9: ["iot", "tsfm", "fmsr", "wo"],
    10: ["iot", "tsfm", "wo"],
    11: ["iot", "tsfm"],
    12: ["wo", "iot", "tsfm"],
    13: ["iot", "tsfm", "fmsr"],
    14: ["iot", "tsfm"],
    15: ["iot", "tsfm", "fmsr", "wo"],
    16: ["iot", "tsfm", "fmsr"],
}

_ASSETOPS_DEPENDENCIES = {
    1: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    2: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    3: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    4: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    5: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    6: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    7: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    8: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    9: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    10: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    11: ["reference_resolution", "constraint_update", "cross_turn_tool_use"],
    12: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    13: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    14: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    15: ["reference_resolution", "information_accumulation", "cross_turn_tool_use"],
    16: [
        "reference_resolution",
        "information_accumulation",
        "correction_clarification",
    ],
}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dependency_types(intent: str, transition: str) -> list[DependencyType]:
    text = f"{intent} {transition}".casefold()
    values: list[DependencyType] = []
    if any(word in text for word in ("coreference", "refer", "ordinal", "same for")):
        values.append(DependencyType.REFERENCE_RESOLUTION)
    if any(
        word in text for word in ("long-range", "accumul", "combine", "merge", "extend")
    ):
        values.append(DependencyType.INFORMATION_ACCUMULATION)
    if any(word in text for word in ("clarif", "revise", "scope", "metric")):
        values.append(DependencyType.CONSTRAINT_UPDATE)
    if any(word in text for word in ("correct", "override", "self-correct")):
        values.append(DependencyType.CORRECTION_CLARIFICATION)
    values.append(DependencyType.CROSS_TURN_TOOL_USE)
    return list(dict.fromkeys(values))


def _read_wtb_turns(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if heading := _HEADING_RE.match(line):
            scenario_id, title = heading.groups()
            current = {"scenario_id": scenario_id, "title": title, "turns": []}
            records[scenario_id] = current
            continue
        if current is not None and (turn := _TURN_RE.match(line)):
            turn_type, message = turn.groups()
            current["turns"].append((turn_type, message))
    return records


def build_wtb() -> list[MultiTurnScenario]:
    metadata_path = SOURCE / "MaintIE_50_WildToolBench_Scenarios.csv"
    with metadata_path.open(encoding="utf-8-sig", newline="") as handle:
        metadata = {row["id"]: row for row in csv.DictReader(handle)}
    raw_turns = _read_wtb_turns(SOURCE / "MaintIE_50_WildToolBench_Scenarios.md")
    gold = json.loads((SOURCE / "wtb_ground_truth.json").read_text(encoding="utf-8"))
    policy = _load_module("wtb_tool_policy", SOURCE / "wtb_tool_policy.py")
    gold = policy.apply_real_tool_policy(gold)

    scenarios: list[MultiTurnScenario] = []
    for scenario_id in sorted(raw_turns):
        row = metadata[scenario_id]
        source_record = raw_turns[scenario_id]
        gold_turns = gold[scenario_id]
        dependencies = _dependency_types(
            row["intent_mechanism"], row["instruction_transition"]
        )
        turns: list[TurnSpec] = []
        for index, ((turn_type, message), truth) in enumerate(
            zip(source_record["turns"], gold_turns, strict=True), 1
        ):
            turn_dependencies = [] if index == 1 else dependencies
            turns.append(
                TurnSpec(
                    turn_id=index,
                    turn_type=turn_type,
                    user_message=message,
                    dependency_on_previous_turns=(
                        "Initial task; no prior user turn."
                        if index == 1
                        else f"{row['intent_mechanism']}; transition: {row['instruction_transition']}."
                    ),
                    dependency_types=turn_dependencies,
                    expected_information=truth["intent"],
                    expected_tool_behavior=truth.get("tools", []),
                    accepted_tool_plans=truth.get("accepted_tool_plans", []),
                    ground_truth=truth.get("result"),
                )
            )
        scenarios.append(
            MultiTurnScenario(
                scenario_id=scenario_id,
                source="mentor_wtb50",
                split="main",
                description=source_record["title"],
                overall_user_goal=source_record["title"],
                overall_expected_outcome=row["gold_orchestration"],
                reference_date=None,
                context_dependency=dependencies,
                required_tools=["maintie"],
                executable=True,
                valid_multi_turn=True,
                ground_truth_available=True,
                notes=(
                    "Executable against the bundled read-only MaintIE MCP server; "
                    f"weak-agent trap: {row['weak_agent_trap']}"
                ),
                turns=turns,
            )
        )
    return scenarios


def build_assetops16() -> list[MultiTurnScenario]:
    module = _load_module("assetops16_scenarios", SOURCE / "assetops16_scenarios.py")
    scenarios: list[MultiTurnScenario] = []
    for source in module.SCENARIOS:
        dependencies = [
            DependencyType(value) for value in _ASSETOPS_DEPENDENCIES[source["id"]]
        ]
        tools = _ASSETOPS_TOOLS[source["id"]]
        turns = [
            TurnSpec(
                turn_id=index,
                turn_type="task" if index == 1 else "follow",
                user_message=message,
                dependency_on_previous_turns=(
                    "Initial task; no prior user turn."
                    if index == 1
                    else "Depends on the entity, time window, evidence, or decision state established in earlier turns."
                ),
                dependency_types=[] if index == 1 else dependencies,
                expected_information=(
                    f"A grounded contribution to: {source['title']}. "
                    "Exact per-turn ground truth still requires curation."
                ),
                expected_tool_behavior=[],
                accepted_tool_plans=[],
                ground_truth=None,
            )
            for index, message in enumerate(source["turns"], 1)
        ]
        scenarios.append(
            MultiTurnScenario(
                scenario_id=f"A16-{source['id']:02d}",
                source="existing_16_dialogs",
                split="development",
                description=source["title"],
                overall_user_goal=source["title"],
                overall_expected_outcome=(
                    "Complete the chained O&M investigation while retaining prior entities, "
                    "time windows, evidence, and user constraints."
                ),
                reference_date=source["reference_date"],
                context_dependency=dependencies,
                required_tools=tools,
                executable=False,
                valid_multi_turn=True,
                ground_truth_available=False,
                notes=(
                    "Retained as development data only. The latest official checkout does "
                    "not contain a scenario-specific manifest/data package or curated per-turn "
                    "ground truth for this dialog; do not include it in formal scores yet."
                ),
                turns=turns,
            )
        )
    return scenarios


def build_single_turn_controls(
    multi_turn_scenarios: list[MultiTurnScenario],
) -> list[MultiTurnScenario]:
    """Collapse each WTB conversation into one prompt with the same subgoals."""
    controls: list[MultiTurnScenario] = []
    for scenario in multi_turn_scenarios:
        numbered = "\n".join(
            f"{turn.turn_id}. [{turn.turn_type}] {turn.user_message}"
            for turn in scenario.turns
        )
        prompt = (
            "Complete the following combined maintenance-analysis request in one "
            "response. Treat the numbered items as one ordered specification, resolve "
            "all references from the text, and answer every non-chat item.\n\n"
            f"{numbered}"
        )
        combined_truth = {
            f"turn_{turn.turn_id}": turn.ground_truth
            for turn in scenario.turns
            if turn.ground_truth is not None
        }
        preferred_path = [
            group for turn in scenario.turns for group in turn.expected_tool_behavior
        ]
        controls.append(
            MultiTurnScenario(
                scenario_id=f"ST-{scenario.scenario_id}",
                paired_scenario_id=scenario.scenario_id,
                source=scenario.source,
                split="single_turn_control",
                description=f"Single-turn control for {scenario.description}",
                overall_user_goal=scenario.overall_user_goal,
                overall_expected_outcome=scenario.overall_expected_outcome,
                context_dependency=[],
                required_tools=scenario.required_tools,
                executable=scenario.executable,
                valid_multi_turn=False,
                ground_truth_available=scenario.ground_truth_available,
                notes=(
                    "Paired control generated by presenting every original user turn "
                    "at once. Use task-success/APR, not cross-turn capability metrics, "
                    "for the paired degradation comparison."
                ),
                turns=[
                    TurnSpec(
                        turn_id=1,
                        turn_type="single_turn_control",
                        user_message=prompt,
                        dependency_on_previous_turns=(
                            "None: all information and constraints are present in one prompt."
                        ),
                        expected_information=(
                            "Return all objectively scored results from the paired conversation."
                        ),
                        expected_tool_behavior=preferred_path,
                        accepted_tool_plans=[preferred_path],
                        ground_truth=combined_truth,
                    )
                ],
            )
        )
    return controls


def _fingerprint(scenario: MultiTurnScenario) -> str:
    normalized = "\n".join(
        " ".join(turn.user_message.casefold().split()) for turn in scenario.turns
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def audit(scenarios: list[MultiTurnScenario]) -> list[dict[str, Any]]:
    seen: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        fingerprint = _fingerprint(scenario)
        duplicate_of = seen.get(fingerprint)
        seen.setdefault(fingerprint, scenario.scenario_id)
        if duplicate_of:
            scenario.duplicate_of = duplicate_of
            scenario.executable = False
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "source": scenario.source,
                "number_of_turns": len(scenario.turns),
                "user_goal": scenario.overall_user_goal,
                "context_dependency": ";".join(scenario.context_dependency),
                "required_tools": ";".join(scenario.required_tools),
                "expected_outcome": scenario.overall_expected_outcome,
                "executable": scenario.executable,
                "valid_multi_turn": scenario.valid_multi_turn,
                "ground_truth_available": scenario.ground_truth_available,
                "duplicate_of": scenario.duplicate_of or "",
                "notes": scenario.notes,
            }
        )
    return rows


def _write_jsonl(path: Path, scenarios: list[MultiTurnScenario]) -> None:
    path.write_text(
        "".join(
            json.dumps(scenario.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for scenario in scenarios
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    development = build_assetops16()
    main_set = build_wtb()
    controls = build_single_turn_controls(main_set)
    rows = audit([*development, *main_set])
    _write_jsonl(args.output_dir / "assetops16.jsonl", development)
    _write_jsonl(args.output_dir / "wtb50.jsonl", main_set)
    _write_jsonl(args.output_dir / "wtb50_single_turn.jsonl", controls)

    audit_path = args.output_dir / "audit.csv"
    with audit_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "schema_version": "1.0",
        "candidate_scenarios": len(rows),
        "candidate_user_turns": sum(row["number_of_turns"] for row in rows),
        "valid_multi_turn": sum(row["valid_multi_turn"] for row in rows),
        "executable": sum(row["executable"] for row in rows),
        "formal_evaluation_set": sum(
            row["executable"] and row["ground_truth_available"] for row in rows
        ),
        "by_source": dict(Counter(row["source"] for row in rows)),
        "paired_single_turn_controls": len(controls),
        "decision": (
            "WTB50 is the executable main set. A16 remains a development set until "
            "scenario manifests and per-turn ground truth are curated."
        ),
    }
    (args.output_dir / "audit_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
