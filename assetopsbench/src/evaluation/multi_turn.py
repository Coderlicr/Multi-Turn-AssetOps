"""Deterministic turn- and conversation-level evaluation for WTB multi-turn runs."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from benchmark.multi_turn_schema import MultiTurnScenario, load_scenarios
from evaluation.scorers.static_json import parse_structured_answer


def _bare_tool_name(name: str) -> str:
    return name.split("__", 1)[-1].rsplit(".", 1)[-1]


def canonical_plan(plan: list[list[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(sorted(_bare_tool_name(tool) for tool in group)) for group in plan
    )


def actual_tool_plan(user_turn: dict) -> list[list[str]]:
    groups: list[list[str]] = []
    for step in user_turn.get("trajectory", {}).get("turns", []):
        tools = [
            call.get("name", "")
            for call in step.get("tool_calls", [])
            if call.get("name") and call.get("name") != "finish"
        ]
        if tools:
            groups.append(tools)
    return groups


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).casefold(): _normalize(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(child) for child in value]
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


def _same_result(actual: Any, expected: Any) -> bool:
    actual = _normalize(actual)
    expected = _normalize(expected)
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(actual, dict) and isinstance(expected, dict):
        return expected.keys() <= actual.keys() and all(
            _same_result(actual[key], expected[key]) for key in expected
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same_result(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def _leaf_values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [leaf for child in value.values() for leaf in _leaf_values(child)]
    if isinstance(value, (list, tuple)):
        return [leaf for child in value for leaf in _leaf_values(child)]
    return [value]


def answer_matches(answer: str, expected: Any) -> bool:
    if expected is None:
        return True
    parsed = parse_structured_answer(answer)
    if _same_result(parsed, expected):
        return True
    normalized_answer = " ".join(answer.casefold().split())
    for leaf in _leaf_values(expected):
        if isinstance(leaf, bool) or leaf is None:
            continue
        if isinstance(leaf, (int, float)):
            pattern = rf"(?<![\d.]){re.escape(str(leaf))}(?![\d.])"
            if not re.search(pattern, normalized_answer):
                return False
        elif " ".join(str(leaf).casefold().split()) not in normalized_answer:
            return False
    return True


def score_conversation(scenario: MultiTurnScenario, record: dict) -> dict[str, Any]:
    trajectory = record.get("trajectory", {})
    actual_turns = trajectory.get("user_turns", [])
    if not actual_turns and isinstance(trajectory.get("turns"), list):
        actual_turns = [{"answer": record.get("answer", ""), "trajectory": trajectory}]
    turn_results: list[dict[str, Any]] = []
    capability_scores: dict[str, list[bool]] = defaultdict(list)
    for index, expected_turn in enumerate(scenario.turns):
        actual = actual_turns[index] if index < len(actual_turns) else {}
        actual_plan = actual_tool_plan(actual)
        accepted_plans = expected_turn.accepted_tool_plans or [
            expected_turn.expected_tool_behavior
        ]
        path_ok = bool(actual) and canonical_plan(actual_plan) in {
            canonical_plan(plan) for plan in accepted_plans
        }
        answer_scored = expected_turn.ground_truth is not None
        result_ok = (
            bool(actual)
            and answer_matches(actual.get("answer", ""), expected_turn.ground_truth)
            if answer_scored
            else None
        )
        tool_decision_ok = bool(actual) and bool(actual_plan) == bool(
            expected_turn.expected_tool_behavior
        )
        # Task success and path optimality are intentionally independent.  An
        # agent can reach the correct grounded answer through a redundant path;
        # OPR captures that inefficiency without erasing task success.
        turn_ok = result_ok
        for dependency in expected_turn.dependency_types:
            if str(dependency) == "cross_turn_tool_use":
                capability_scores[str(dependency)].append(tool_decision_ok)
            elif result_ok is not None:
                capability_scores[str(dependency)].append(result_ok)
        turn_results.append(
            {
                "turn_id": expected_turn.turn_id,
                "turn_type": expected_turn.turn_type,
                "path_correct": path_ok,
                "answer_scored": answer_scored,
                "answer_correct": result_ok,
                "tool_decision_correct": tool_decision_ok,
                "turn_success": turn_ok,
                "actual_tool_plan": actual_plan,
                "accepted_tool_plans": accepted_plans,
            }
        )

    expected_count = len(scenario.turns)
    path_correct = sum(turn["path_correct"] for turn in turn_results)
    scored_answers = [
        turn
        for turn, spec in zip(turn_results, scenario.turns, strict=True)
        if spec.ground_truth is not None
    ]
    answer_correct = sum(turn["answer_correct"] for turn in scored_answers)
    dependent_turns = [
        result
        for result, spec in zip(turn_results, scenario.turns, strict=True)
        if spec.dependency_types and spec.ground_truth is not None
    ]
    answer_failures = [
        index
        for index, result in enumerate(turn_results)
        if result["answer_correct"] is False
    ]
    post_failure_turns = [
        result
        for failed_index in answer_failures
        for result in turn_results[failed_index + 1 :]
        if result["answer_correct"] is not None
    ]
    return {
        "scenario_id": scenario.scenario_id,
        "paired_scenario_id": scenario.paired_scenario_id,
        "user_turns_expected": expected_count,
        "user_turns_observed": len(actual_turns),
        "optimal_path_rate": path_correct / expected_count if expected_count else 1.0,
        "accomplish_progress_rate": (
            answer_correct / len(scored_answers) if scored_answers else None
        ),
        "no_tool_decision_accuracy": sum(
            turn["tool_decision_correct"] for turn in turn_results
        )
        / expected_count,
        "context_retention": (
            sum(turn["answer_correct"] for turn in dependent_turns)
            / len(dependent_turns)
            if dependent_turns
            else None
        ),
        "error_propagation_resilience": (
            sum(turn["answer_correct"] for turn in post_failure_turns)
            / len(post_failure_turns)
            if post_failure_turns
            else 1.0
        ),
        "overall_task_success": (
            len(actual_turns) == expected_count
            and all(turn["answer_correct"] is True for turn in scored_answers)
        ),
        "capabilities": {
            name: sum(values) / len(values)
            for name, values in capability_scores.items()
        },
        "turns": turn_results,
    }


def evaluate_files(scenarios_path: Path, trajectories_path: Path) -> dict[str, Any]:
    scenarios = {
        scenario.scenario_id: scenario for scenario in load_scenarios(scenarios_path)
    }
    results: list[dict[str, Any]] = []
    for path in sorted(trajectories_path.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        scenario_id = str(record.get("scenario_id") or "")
        if scenario_id in scenarios:
            results.append(score_conversation(scenarios[scenario_id], record))
    count = len(results)
    return {
        "scenario_count": count,
        "optimal_path_rate": (
            sum(result["optimal_path_rate"] for result in results) / count
            if count
            else None
        ),
        "accomplish_progress_rate": (
            sum(result["accomplish_progress_rate"] for result in results) / count
            if count
            and all(
                result["accomplish_progress_rate"] is not None for result in results
            )
            else None
        ),
        "overall_task_success_rate": (
            sum(result["overall_task_success"] for result in results) / count
            if count
            else None
        ),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--trajectories", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_files(args.scenarios, args.trajectories)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
