"""Reduce an aggregate static-JSON report to failed/poor scenarios only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_poor_performance_report(
    report: dict[str, Any], *, score_threshold: float = 1.0
) -> dict[str, Any]:
    """Keep only non-passing or below-threshold scenario results."""
    results = report.get("results") or []
    poor: list[dict[str, Any]] = []
    for result in results:
        score = result.get("score") or {}
        numeric_score = score.get("score")
        below_threshold = (
            isinstance(numeric_score, (int, float))
            and not isinstance(numeric_score, bool)
            and float(numeric_score) < score_threshold
        )
        if score.get("passed") is True and not below_threshold:
            continue

        details = score.get("details") or {}
        poor.append(
            {
                "scenario_id": result.get("scenario_id"),
                "run_id": result.get("run_id"),
                "model": result.get("model"),
                "score": numeric_score,
                "strict_exact_match_accuracy": details.get(
                    "strict_exact_match_accuracy"
                ),
                "missing_keys": details.get("missing_keys", []),
                "extra_keys": details.get("extra_keys", []),
                "rationale": score.get("rationale", ""),
                "answer": result.get("answer", ""),
            }
        )

    return {
        "generated_at": report.get("generated_at"),
        "score_threshold": score_threshold,
        "scenarios_evaluated": len(results),
        "poor_scenario_count": len(poor),
        "poor_scenarios": poor,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--score-threshold", type=float, default=1.0)
    args = parser.parse_args()

    report = json.loads(args.input.read_text(encoding="utf-8"))
    poor_report = build_poor_performance_report(
        report, score_threshold=args.score_threshold
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(poor_report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(poor_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
