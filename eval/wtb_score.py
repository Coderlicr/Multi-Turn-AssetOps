"""Small, deterministic scorer for the advisor-provided WTB-50 benchmark."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from eval.wtb_scenarios import GOLD_FILE


def canonical_plan(plan: list[list[str]] | None) -> tuple[frozenset[str], ...]:
    """Keep sequential group order while ignoring order inside parallel groups."""
    return tuple(frozenset(group) for group in (plan or []))


def _same_result(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _same_result(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        return len(actual) == len(expected) and all(
            _same_result(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def score_dialog(agent_turns: list[dict], gold_turns: list[dict]) -> dict:
    """Score one aligned dialog; missing and extra turns are both penalized."""
    path_denominator = max(len(agent_turns), len(gold_turns))
    path_correct = 0
    no_tool_correct = 0

    for index in range(path_denominator):
        agent = agent_turns[index] if index < len(agent_turns) else {}
        gold = gold_turns[index] if index < len(gold_turns) else None
        if gold is None:
            continue
        if canonical_plan(agent.get("tools")) == canonical_plan(gold.get("tools")):
            path_correct += 1
        if bool(agent.get("tools")) == bool(gold.get("tools")):
            no_tool_correct += 1

    compute_indices = [
        index
        for index, gold in enumerate(gold_turns)
        if gold.get("result") is not None and not gold.get("judge", False)
    ]
    result_correct = sum(
        1
        for index in compute_indices
        if index < len(agent_turns)
        and _same_result(agent_turns[index].get("result"), gold_turns[index]["result"])
    )

    return {
        "optimal_path_rate": (
            path_correct / path_denominator if path_denominator else 1.0
        ),
        "accomplish_progress_rate": (
            result_correct / len(compute_indices) if compute_indices else None
        ),
        "no_tool_decision_accuracy": (
            no_tool_correct / path_denominator if path_denominator else 1.0
        ),
        "path_correct": path_correct,
        "path_turns": path_denominator,
        "result_correct": result_correct,
        "compute_turns": len(compute_indices),
        "missing_turns": max(len(gold_turns) - len(agent_turns), 0),
        "extra_turns": max(len(agent_turns) - len(gold_turns), 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score one WTB-50 agent trace JSON.")
    parser.add_argument("scenario_id", help="WTB01 through WTB50")
    parser.add_argument("trace", type=Path, help="JSON list of agent turn records")
    parser.add_argument("--gold", type=Path, default=GOLD_FILE)
    args = parser.parse_args()

    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    agent_turns = json.loads(args.trace.read_text(encoding="utf-8"))
    if args.scenario_id not in gold:
        parser.error(f"Unknown scenario: {args.scenario_id}")
    print(json.dumps(score_dialog(agent_turns, gold[args.scenario_id]), indent=2))


if __name__ == "__main__":
    main()
