"""Compare paired single-turn and multi-turn reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def compare_reports(multi_turn: dict, single_turn: dict) -> dict[str, Any]:
    multi_by_id = {
        result["scenario_id"]: result for result in multi_turn.get("results", [])
    }
    pairs: list[dict[str, Any]] = []
    for control in single_turn.get("results", []):
        paired_id = control.get("paired_scenario_id")
        if not paired_id or paired_id not in multi_by_id:
            continue
        multi = multi_by_id[paired_id]
        pairs.append(
            {
                "scenario_id": paired_id,
                "single_turn_success": bool(control["overall_task_success"]),
                "multi_turn_success": bool(multi["overall_task_success"]),
                "success_degradation": (
                    int(bool(control["overall_task_success"]))
                    - int(bool(multi["overall_task_success"]))
                ),
                "single_turn_apr": control.get("accomplish_progress_rate"),
                "multi_turn_apr": multi.get("accomplish_progress_rate"),
                "apr_degradation": (
                    control["accomplish_progress_rate"]
                    - multi["accomplish_progress_rate"]
                    if control.get("accomplish_progress_rate") is not None
                    and multi.get("accomplish_progress_rate") is not None
                    else None
                ),
            }
        )
    count = len(pairs)
    apr_deltas = [
        pair["apr_degradation"] for pair in pairs if pair["apr_degradation"] is not None
    ]
    return {
        "paired_scenarios": count,
        "multi_turn_degradation": (
            sum(pair["success_degradation"] for pair in pairs) / count
            if count
            else None
        ),
        "apr_degradation": (sum(apr_deltas) / len(apr_deltas) if apr_deltas else None),
        "pairs": pairs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multi-turn-report", type=Path, required=True)
    parser.add_argument("--single-turn-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare_reports(
        json.loads(args.multi_turn_report.read_text(encoding="utf-8")),
        json.loads(args.single_turn_report.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
