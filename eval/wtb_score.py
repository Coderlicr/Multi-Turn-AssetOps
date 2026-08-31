"""Small, deterministic scorer for the advisor-provided WTB-50 benchmark."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

if __package__:
    from .wtb_scenarios import GOLD_FILE, load_wtb_gold
else:  # Support ``python eval/wtb_score.py``.
    from wtb_scenarios import GOLD_FILE, load_wtb_gold


def _bare_tool_name(name: str) -> str:
    """Accept both bare trace names and supervisor-style ``maintie.name``."""
    return name.rsplit(".", 1)[-1]


def canonical_plan(plan: list[list[str]] | None) -> tuple[tuple[str, ...], ...]:
    """Keep sequence and duplicate calls; ignore order only within parallel groups."""
    return tuple(
        tuple(sorted(_bare_tool_name(tool) for tool in group))
        for group in (plan or [])
    )


def _accepted_plans(gold_turn: dict) -> list[list[list[str]]]:
    return gold_turn.get("accepted_tool_plans") or [gold_turn.get("tools", [])]


def _normalize_result(value: Any) -> Any:
    """Normalize presentation-only variations without using scenario answers."""
    if isinstance(value, list):
        return [_normalize_result(item) for item in value]
    if not isinstance(value, dict):
        return value

    folded_keys = {str(key).casefold() for key in value}
    if folded_keys == {"object_class", "count"}:
        object_key = next(
            key for key in value if str(key).casefold() == "object_class"
        )
        count_key = next(key for key in value if str(key).casefold() == "count")
        return {
            "top": [[value[object_key], value[count_key]]]
        }

    aliases = {
        "replacements": "replace",
        "repairs": "repair",
        "fault_work_orders": "fault",
        "activities": "remedy",
        "actions_taken": "remedy",
        "more_problematic_component": "worse",
        "selected": "worse",
        "most_common_equipment": "top",
        "top_3_object_classes": "top3",
        "top_3": "top3",
        "total_failure_records": "n",
    }
    normalized: dict[str, Any] = {}
    for raw_key, raw_child in value.items():
        key = aliases.get(str(raw_key).casefold(), str(raw_key).casefold())
        child = _normalize_result(raw_child)
        if key == "top" and isinstance(child, list) and len(child) == 2:
            if isinstance(child[0], str) and isinstance(child[1], (int, float)):
                child = [child]
        if key == "remedy" and isinstance(child, list):
            if all(
                isinstance(item, list)
                and len(item) == 2
                and isinstance(item[0], str)
                for item in child
            ):
                child = {item[0]: item[1] for item in child}
        normalized[key] = child

    if len(normalized) == 1:
        key, child = next(iter(normalized.items()))
        if (key == "count" or key.endswith("_count")) and isinstance(
            child, (int, float)
        ):
            return {"n": child}
    return normalized


def _same_result(actual: Any, expected: Any) -> bool:
    actual = _normalize_result(actual)
    expected = _normalize_result(expected)
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(actual, dict) and isinstance(expected, dict):
        if set(expected) == {"worse"} and isinstance(expected["worse"], str):
            selected = expected["worse"].casefold()
            if any(str(key).casefold() == selected for key in actual):
                return True
        return expected.keys() <= actual.keys() and all(
            _same_result(actual[key], expected[key]) for key in expected
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
        if index >= len(agent_turns):
            # A missing response is never a correct path, including when the
            # expected decision was to reuse context without another tool.
            continue
        actual_plan = canonical_plan(agent.get("tools"))
        accepted = {canonical_plan(plan) for plan in _accepted_plans(gold)}
        if actual_plan in accepted:
            path_correct += 1
        gold_requires_tool = bool(gold.get("tools"))
        if bool(agent.get("tools")) == gold_requires_tool:
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


def load_agent_trace(path: Path) -> list[dict]:
    """Load either the legacy JSON array or the CLI's per-turn JSONL trace."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        records = json.loads(text)
    else:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise ValueError("Agent trace must contain a list of JSON objects")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score one WTB-50 agent trace (JSON array or JSONL)."
    )
    parser.add_argument("scenario_id", help="WTB01 through WTB50")
    parser.add_argument("trace", type=Path, help="Agent turn records as JSON or JSONL")
    parser.add_argument("--gold", type=Path, default=GOLD_FILE)
    args = parser.parse_args()

    gold = load_wtb_gold(args.gold)
    agent_turns = load_agent_trace(args.trace)
    if args.scenario_id not in gold:
        parser.error(f"Unknown scenario: {args.scenario_id}")
    print(json.dumps(score_dialog(agent_turns, gold[args.scenario_id]), indent=2))


if __name__ == "__main__":
    main()
