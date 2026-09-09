"""CLI entry point for the Multi-Turn AssetOps Stirrup runner."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_FALLBACK_MODEL = "watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8"


def _default_model() -> str:
    return os.environ.get("DEFAULT_MODEL_ID") or _FALLBACK_MODEL


def _build_parser() -> argparse.ArgumentParser:
    default_model = _default_model()
    parser = argparse.ArgumentParser(
        prog="stirrup-agent",
        description="Run a question with Stirrup and the Multi-Turn AssetOps MCP servers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
model-id format:
  litellm_proxy/<model>   OpenAI-compatible LiteLLM proxy
  tokenrouter/<model>     OpenAI-compatible TokenRouter
  <provider>/<model>      Native through Stirrup's LiteLLM client

environment variables:
  LITELLM_API_KEY / LITELLM_BASE_URL
  TOKENROUTER_API_KEY / TOKENROUTER_BASE_URL
  WATSONX_APIKEY / WATSONX_PROJECT_ID / WATSONX_URL
  STIRRUP_CODE_IMAGE      Docker image for code execution (default assetops-code)

examples:
  stirrup-agent --no-code "What assets are at site MAIN?"
  stirrup-agent --reference-date 2020-06-20 --model-id tokenrouter/MiniMax-M3 \\
    "Analyze Chiller 6 over the past month"
  stirrup-agent --code-backend local --show-trajectory "Analyze work orders"
""",
    )
    parser.add_argument("question", help="The question to answer.")
    parser.add_argument(
        "--model-id",
        default=default_model,
        metavar="MODEL_ID",
        help=f"Model identifier (default: {default_model}).",
    )
    parser.add_argument(
        "--server",
        action="append",
        dest="servers",
        default=[],
        metavar="NAME=COMMAND",
        help=(
            "Override the default MCP servers with NAME=COMMAND. "
            "Repeat once per server."
        ),
    )
    parser.add_argument(
        "--show-trajectory",
        action="store_true",
        help="Print turns, tool calls, and token usage.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Print the complete result as JSON.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable INFO-level logs.",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Disable automatic trajectory log file writing.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Trajectory log directory (default: logs/stirrup_agent).",
    )

    code_group = parser.add_mutually_exclusive_group()
    code_group.add_argument(
        "--code-enabled",
        dest="code_enabled",
        action="store_true",
        default=True,
        help="Enable sandboxed code execution (default).",
    )
    code_group.add_argument(
        "--no-code",
        dest="code_enabled",
        action="store_false",
        help="Expose MCP tools only.",
    )
    parser.add_argument(
        "--code-backend",
        choices=["docker", "local"],
        default="docker",
        help="Code-execution backend (default: docker).",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=30,
        metavar="N",
        help="Maximum agent turns (default: 30).",
    )
    parser.add_argument(
        "--reference-date",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Anchor date for relative time expressions "
            "(default: today's UTC date)."
        ),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        metavar="T",
        help="Optional model sampling temperature.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=[
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "default",
        ],
        default=None,
        metavar="LEVEL",
        help="Optional reasoning effort forwarded to the model client.",
    )
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Host base directory for the code-execution workspace.",
    )
    parser.add_argument(
        "--preserve-workspace",
        action="store_true",
        help="Copy final code-execution files into --workspace-dir.",
    )
    return parser


def _parse_servers(entries: list[str]) -> dict[str, str] | None:
    if not entries:
        return None
    servers: dict[str, str] = {}
    for entry in entries:
        name, separator, command = entry.partition("=")
        if not separator or not name.strip() or not command.strip():
            raise ValueError(
                f"--server requires NAME=COMMAND, received {entry!r}"
            )
        servers[name.strip()] = command.strip()
    return servers


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def _print_trajectory(trajectory) -> None:
    print("\n" + "─" * 60)
    print("  Trace")
    print("─" * 60)
    for turn in trajectory.turns:
        print(
            f"\n  [Turn {turn.index}] in={turn.input_tokens} "
            f"out={turn.output_tokens} tokens"
        )
        if turn.text:
            print(f"    text: {turn.text[:200]}")
        for call in turn.tool_calls:
            print(f"    tool: {call.name}  input: {call.input}")
            if call.output is not None:
                print(f"    output: {str(call.output)[:200]}")
    print(
        f"\n  Total: {trajectory.total_input_tokens} input / "
        f"{trajectory.total_output_tokens} output tokens; "
        f"{len(trajectory.all_tool_calls)} tool calls"
    )


async def _run(args: argparse.Namespace):
    from .runner import StirrupAgentRunner

    runner = StirrupAgentRunner(
        server_paths=_parse_servers(args.servers),
        model=args.model_id,
        code_enabled=args.code_enabled,
        code_backend=args.code_backend,
        workspace_dir=args.workspace_dir,
        preserve_workspace=args.preserve_workspace,
        max_turns=args.max_turns,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        reference_date=args.reference_date,
        log_dir=args.log_dir,
        log_enabled=not args.no_log,
    )
    return await runner.run(args.question)


def main() -> None:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logging(args.verbose)
    try:
        result = asyncio.run(_run(args))
    except (ValueError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "interrupted\n")

    if args.output_json:
        print(json.dumps(dataclasses.asdict(result), indent=2, default=str))
        return
    if args.show_trajectory:
        _print_trajectory(result.trajectory)
    print("\n" + "─" * 60)
    print("  Answer")
    print("─" * 60)
    print(result.answer)


if __name__ == "__main__":
    main()
