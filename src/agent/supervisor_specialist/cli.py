"""CLI entry point for the Supervisor-Specialist system.

Usage:
  supervisor-specialist "question"
  supervisor-specialist --model-id watsonx/... "question"
  supervisor-specialist --no-stream --no-log "question"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_DEFAULT_MODEL = "watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="supervisor-specialist",
        description="Multi-agent industrial asset operations system (Supervisor-Specialist).",
    )
    p.add_argument("question", help="The user question to answer.")
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
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

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

    runner = SupervisorSpecialistRunner(
        llm=llm,
        max_steps=args.max_steps,
        quiet=args.no_stream,
        log_dir=log_dir,
        reference_date=args.reference_date,
    )

    try:
        response = asyncio.run(runner.run(args.question))
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        sys.exit(1)

    print(response)


if __name__ == "__main__":
    main()
