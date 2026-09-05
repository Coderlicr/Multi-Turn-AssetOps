"""Run versioned multi-turn scenarios through one persistent Stirrup session."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent.runner import DEFAULT_SERVER_PATHS
from agent.stirrup_agent.runner import StirrupAgentRunner
from benchmark.multi_turn_schema import MultiTurnScenario, load_scenarios
from observability import init_tracing, set_run_context

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIOS = ROOT / "src/couchdb/scenarios_data"
DEFAULT_OUTPUT = ROOT / "traces/trajectories/multi_turn"
DEFAULT_MODEL = "tokenrouter/z-ai/glm-5.3-free"
SERVER_ENTRYPOINTS = {**DEFAULT_SERVER_PATHS, "maintie": "maintie-mcp-server"}


def select_scenarios(
    scenarios: list[MultiTurnScenario], selector: str
) -> list[MultiTurnScenario]:
    if selector.strip().lower() == "all":
        return scenarios
    requested = [item.strip() for item in selector.split(",") if item.strip()]
    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    missing = [scenario_id for scenario_id in requested if scenario_id not in by_id]
    if missing:
        raise ValueError(f"Unknown scenario IDs: {', '.join(missing)}")
    if not requested:
        raise ValueError("At least one scenario ID is required")
    return [by_id[scenario_id] for scenario_id in requested]


def server_paths_for(scenario: MultiTurnScenario) -> dict[str, Path | str]:
    missing = [
        name for name in scenario.required_tools if name not in SERVER_ENTRYPOINTS
    ]
    if missing:
        raise ValueError(
            f"{scenario.scenario_id} requires unavailable MCP servers: {', '.join(missing)}"
        )
    return {name: SERVER_ENTRYPOINTS[name] for name in scenario.required_tools}


def scenario_manifest(scenarios_path: Path, scenario_id: str) -> dict | None:
    """Return a folder scenario's CouchDB manifest, or ``None`` for JSONL input."""
    if not scenarios_path.is_dir():
        return None
    path = scenarios_path / f"scenario_{scenario_id}" / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def prepare_couchdb_state(
    scenarios_path: Path, scenario_id: str, *, dry_run: bool = False
) -> bool:
    """Reset and load CouchDB when a folder scenario declares DB collections.

    An empty manifest is an explicit declaration that the scenario uses only
    non-CouchDB tools (WTB01 uses the bundled read-only MaintIE server), so no
    local database is required for that case.
    """
    manifest = scenario_manifest(scenarios_path, scenario_id)
    if not manifest:
        return False

    env = os.environ.copy()
    env["SCENARIOS_DATA_DIR"] = str(scenarios_path.resolve())
    commands = [
        [sys.executable, "src/couchdb/init_data.py", "--reset-only"],
        [sys.executable, "src/couchdb/init_data.py", scenario_id],
    ]
    if not dry_run:
        for command in commands:
            subprocess.run(command, check=True, cwd=ROOT, env=env)
    return True


async def run_scenario(
    scenario: MultiTurnScenario,
    *,
    model_id: str,
    max_turns: int,
    reasoning_effort: str | None,
    temperature: float | None,
) -> dict:
    if not scenario.executable:
        raise ValueError(
            f"{scenario.scenario_id} failed the dataset audit and is not executable: "
            f"{scenario.notes}"
        )
    runner = StirrupAgentRunner(
        model=model_id,
        server_paths=server_paths_for(scenario),
        code_enabled=False,
        max_turns=max_turns,
        reasoning_effort=reasoning_effort,
        temperature=temperature,
    )
    if len(scenario.turns) == 1:
        result = await runner.run(scenario.turns[0].user_message)
        return {
            "answers": [result.answer],
            "trajectory": dataclasses.asdict(result.trajectory),
        }
    result = await runner.run_conversation(
        [turn.user_message for turn in scenario.turns]
    )
    return dataclasses.asdict(result)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument(
        "--scenario-ids",
        default="A16-06,WTB01",
        help="Comma-separated IDs, or 'all' (default: the two-scenario pilot).",
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL,
    )
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--trajectory-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument(
        "--router-env-prefix",
        default=None,
        metavar="PREFIX",
        help=(
            "Map PREFIX_BASE_URL/PREFIX_API_KEY to LITELLM_BASE_URL/"
            "LITELLM_API_KEY without copying secrets (for example DEEPSEEK)."
        ),
    )
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    scenarios = select_scenarios(load_scenarios(args.scenarios), args.scenario_ids)
    args.trajectory_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AGENT_TRAJECTORY_DIR"] = str(args.trajectory_dir)
    failures = 0
    for scenario in scenarios:
        run_id = f"stirrup_mt_{scenario.scenario_id}"
        needs_couchdb = bool(scenario_manifest(args.scenarios, scenario.scenario_id))
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "scenario_id": scenario.scenario_id,
                        "user_turns": len(scenario.turns),
                        "servers": list(server_paths_for(scenario)),
                        "model": args.model_id,
                        "code_enabled": False,
                        "temperature": args.temperature,
                        "reasoning_effort": args.reasoning_effort,
                        "max_steps_per_user_turn": args.max_turns,
                        "state_setup": "couchdb" if needs_couchdb else "none",
                        "final_scorer": "static_json",
                    },
                    ensure_ascii=False,
                )
            )
            continue
        try:
            prepare_couchdb_state(args.scenarios, scenario.scenario_id)
            set_run_context(run_id=run_id, scenario_id=scenario.scenario_id)
            result = await run_scenario(
                scenario,
                model_id=args.model_id,
                max_turns=args.max_turns,
                reasoning_effort=args.reasoning_effort,
                temperature=args.temperature,
            )
            print(
                json.dumps(
                    {
                        "scenario_id": scenario.scenario_id,
                        "answers": result["answers"],
                        "trajectory": str(args.trajectory_dir / f"{run_id}.json"),
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
    args = _build_parser().parse_args()
    if args.env_file is not None:
        load_dotenv(args.env_file)
    else:
        load_dotenv()
    if args.router_env_prefix:
        prefix = args.router_env_prefix.strip().upper()
        base_url = os.environ.get(f"{prefix}_BASE_URL")
        api_key = os.environ.get(f"{prefix}_API_KEY")
        if not base_url or not api_key:
            raise SystemExit(f"{prefix}_BASE_URL and {prefix}_API_KEY must both be set")
        os.environ["LITELLM_BASE_URL"] = base_url
        os.environ["LITELLM_API_KEY"] = api_key
    init_tracing("stirrup-agent-multi-turn")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
