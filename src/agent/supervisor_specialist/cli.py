"""CLI entry point for the Supervisor-Specialist system.

Usage:
  supervisor-specialist "question"
  supervisor-specialist --parallel "question"
  supervisor-specialist --multi-turn "question"
  supervisor-specialist --model-id watsonx/... "question"
  supervisor-specialist --no-stream --no-log "question"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_DEFAULT_MODEL = "watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="supervisor-specialist",
        description="Multi-agent industrial asset operations system (Supervisor-Specialist).",
    )
    p.add_argument("question", nargs="?", help="The user question to answer.")
    p.add_argument(
        "--model-id",
        default=os.environ.get("SS_MODEL_ID", _DEFAULT_MODEL),
        help="LiteLLM model ID (default: %(default)s)",
    )
    p.add_argument(
        "--max-steps",
        type=int,
        default=int(os.environ.get("SS_MAX_STEPS", "12")),
        help="Maximum number of agent steps (default: %(default)s)",
    )
    p.add_argument(
        "--max-specialist-dispatches",
        type=int,
        default=int(os.environ.get("SS_MAX_SPECIALIST_DISPATCHES", "2")),
        help="Maximum specialist dispatches per turn (default: %(default)s)",
    )
    p.add_argument(
        "--max-tool-calls",
        type=int,
        default=int(os.environ.get("SS_MAX_TOOL_CALLS", "6")),
        help="Maximum tool calls per turn, including failures (default: %(default)s)",
    )
    p.add_argument(
        "--mode",
        choices=("auto", "maintie", "assetops"),
        default=os.environ.get("SS_MODE", "auto"),
        help="Execution path selection (default: %(default)s)",
    )
    p.add_argument(
        "--no-stream",
        action="store_true",
        help="Suppress streaming event log output to stderr",
    )
    p.add_argument(
        "--no-log",
        action="store_true",
        help="Disable behavior log file writing",
    )
    p.add_argument(
        "--reference-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Anchor date for time window computation (default: today UTC). E.g. 2020-06-20",
    )
    p.add_argument(
        "--multi-turn",
        action="store_true",
        help="Enter a REPL and retain supervisor-specialist memory across turns.",
    )
    p.add_argument(
        "--parallel",
        action="store_true",
        help=(
            "Enable parallel specialist tool batches and deterministic multi-asset "
            "coverage guards."
        ),
    )
    p.add_argument(
        "--server",
        action="append",
        default=[],
        dest="servers",
        metavar="NAME=PATH",
        help=(
            "Register an MCP server as NAME=PATH. Repeating this option "
            "overrides the default server set."
        ),
    )
    p.add_argument(
        "--save-output",
        type=Path,
        default=None,
        help="Append structured turn records as JSONL.",
    )
    p.add_argument(
        "--output-json",
        action="store_true",
        help="Print each structured turn record as JSON.",
    )
    return p


def _parse_servers(entries: list[str]) -> dict[str, Path | str] | None:
    if not entries:
        return None
    result: dict[str, Path | str] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"--server requires NAME=PATH, got {entry!r}")
        name, value = entry.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name or not value:
            raise ValueError(f"--server requires NAME=PATH, got {entry!r}")
        result[name] = value if "/" not in value and "\\" not in value else Path(value)
    return result


async def _run(args: argparse.Namespace) -> None:
    from llm.litellm import LiteLLMBackend
    from agent.supervisor_specialist.runner import SupervisorSpecialistRunner

    llm = LiteLLMBackend(model_id=args.model_id)

    log_dir = None
    if args.no_log:
        import tempfile
        log_dir = None  # BehaviorLog will still write; pass a temp dir to suppress
        # Use /dev/null-like approach: write to a temp dir that we ignore
        import pathlib
        log_dir = pathlib.Path(tempfile.mkdtemp(prefix="ss_nolog_"))

    try:
        server_paths = _parse_servers(getattr(args, "servers", []))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    runner = SupervisorSpecialistRunner(
        llm=llm,
        max_steps=args.max_steps,
        quiet=args.no_stream,
        log_dir=log_dir,
        reference_date=args.reference_date,
        parallel=args.parallel,
        server_paths=server_paths,
        mode=getattr(args, "mode", "auto"),
        max_specialist_dispatches=getattr(args, "max_specialist_dispatches", 2),
        max_tool_calls=getattr(args, "max_tool_calls", 6),
    )

    async def execute(question: str):
        if hasattr(runner, "run_turn_result"):
            return await runner.run_turn_result(question)
        answer = await runner.run_turn(question)
        from agent.supervisor_specialist.schemas import SupervisorTurnResult
        return SupervisorTurnResult(question=question, answer=answer)

    def render(result) -> None:
        record = result.model_dump(mode="json")
        save_output = getattr(args, "save_output", None)
        if save_output is not None:
            save_output.parent.mkdir(parents=True, exist_ok=True)
            with save_output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if getattr(args, "output_json", False):
            print(json.dumps(record, ensure_ascii=False))
        else:
            print(result.answer)

    if not args.multi_turn:
        render(await execute(args.question))
        return

    if args.question:
        render(await execute(args.question))

    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            print()
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break
        render(await execute(question))


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.question and not args.multi_turn:
        parser.error("the following arguments are required: question")

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
