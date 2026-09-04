"""Run standalone multi-turn scenarios through one persistent Stirrup session."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .maintie.data import load_records
from .runner import PROJECT_ROOT, StirrupMultiTurnRunner
from .schema import MultiTurnScenario, load_scenarios

DEFAULT_SCENARIOS = PROJECT_ROOT / "data/wtb50.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "results/trajectories"
SUPPORTED_SERVERS = {"maintie"}


def select_scenarios(
    scenarios: list[MultiTurnScenario], selector: str
) -> list[MultiTurnScenario]:
    if selector.strip().lower() == "all":
        return scenarios
    requested = [value.strip() for value in selector.split(",") if value.strip()]
    if not requested:
        raise ValueError("At least one scenario ID is required")
    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    missing = [scenario_id for scenario_id in requested if scenario_id not in by_id]
    if missing:
        raise ValueError(f"Unknown scenario IDs: {', '.join(missing)}")
    return [by_id[scenario_id] for scenario_id in requested]


def validate_scenario(scenario: MultiTurnScenario) -> None:
    if not scenario.executable:
        raise ValueError(f"{scenario.scenario_id} is not executable: {scenario.notes}")
    missing = [
        tool for tool in scenario.required_tools if tool not in SUPPORTED_SERVERS
    ]
    if missing:
        raise ValueError(
            f"{scenario.scenario_id} requires unsupported servers: {', '.join(missing)}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument(
        "--scenario-ids",
        default="WTB01",
        help="Comma-separated scenario IDs or 'all' (default: WTB01).",
    )
    parser.add_argument("--model-id", default="litellm_proxy/deepseek-v4-flash")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--trajectory-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument(
        "--router-env-prefix",
        default=None,
        metavar="PREFIX",
        help=(
            "Map PREFIX_BASE_URL/PREFIX_API_KEY to LITELLM_BASE_URL/"
            "LITELLM_API_KEY in memory."
        ),
    )
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def configure_environment(args: argparse.Namespace) -> None:
    load_dotenv(args.env_file if args.env_file is not None else PROJECT_ROOT / ".env")
    if not args.router_env_prefix:
        return
    prefix = args.router_env_prefix.strip().upper()
    base_url = os.environ.get(f"{prefix}_BASE_URL")
    api_key = os.environ.get(f"{prefix}_API_KEY")
    if not base_url or not api_key:
        raise SystemExit(f"{prefix}_BASE_URL and {prefix}_API_KEY must both be set")
    os.environ["LITELLM_BASE_URL"] = base_url
    os.environ["LITELLM_API_KEY"] = api_key


def _write_record(
    *,
    output_dir: Path,
    scenario: MultiTurnScenario,
    model: str,
    result,
) -> Path:
    run_id = f"stirrup_mt_{scenario.scenario_id}"
    answers = result.answers if hasattr(result, "answers") else [result.answer]
    record = {
        "run_id": run_id,
        "scenario_id": scenario.scenario_id,
        "runner": "stirrup-agent-multi-turn",
        "model": model,
        "question": "\n".join(
            f"User turn {turn.turn_id}: {turn.user_message}" for turn in scenario.turns
        ),
        "answer": answers[-1],
        "trajectory": dataclasses.asdict(result.trajectory),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}.json"
    output_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return output_path


async def run(args: argparse.Namespace) -> int:
    scenarios = select_scenarios(load_scenarios(args.scenarios), args.scenario_ids)
    failures = 0
    for scenario in scenarios:
        validate_scenario(scenario)
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "run_id": f"stirrup_mt_{scenario.scenario_id}",
                        "scenario_id": scenario.scenario_id,
                        "user_turns": len(scenario.turns),
                        "servers": scenario.required_tools,
                        "maintie_records": len(load_records()),
                        "model": args.model_id,
                    },
                    ensure_ascii=False,
                )
            )
            continue
        runner = StirrupMultiTurnRunner(
            model=args.model_id,
            max_turns=args.max_turns,
            reasoning_effort=args.reasoning_effort,
            temperature=args.temperature,
        )
        try:
            if len(scenario.turns) == 1:
                result = await runner.run_single(scenario.turns[0].user_message)
            else:
                result = await runner.run_conversation(
                    [turn.user_message for turn in scenario.turns]
                )
            output_path = _write_record(
                output_dir=args.trajectory_dir,
                scenario=scenario,
                model=args.model_id,
                result=result,
            )
            answers = result.answers if hasattr(result, "answers") else [result.answer]
            print(
                json.dumps(
                    {
                        "scenario_id": scenario.scenario_id,
                        "answers": answers,
                        "trajectory": str(output_path),
                    },
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            failures += 1
            print(f"error: {scenario.scenario_id}: {exc}", file=sys.stderr)
            if not args.continue_on_error:
                raise
    return 1 if failures else 0


def main() -> None:
    args = build_parser().parse_args()
    configure_environment(args)
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
