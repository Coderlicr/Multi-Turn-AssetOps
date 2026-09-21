"""
Run multi-turn scenarios through supervisor-specialist and keep only behavior logs.

Usage:
  uv run python eval/run_supervisor_specialist_eval.py
  uv run python eval/run_supervisor_specialist_eval.py --dialogs 1 4 6
  uv run python eval/run_supervisor_specialist_eval.py --log-dir logs/supervisor_specialist_eval
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import pathlib
import shutil
import sys
from typing import Optional

REPO_ROOT = pathlib.Path(__file__).parent.parent
BASE_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_LOG_ROOT = REPO_ROOT / "logs" / "supervisor_specialist_eval"
#: Measured over 75 turns / 20 dialogues on gpt-5.6-luna and gpt-4o-mini:
#: a turn ran 44s at the median, 285s at p90 and 793s at the longest; a whole
#: dialogue ran 314s at the median and 1154s at the longest. The previous
#: 360s/1500s left almost no headroom above those maxima, and three of sixteen
#: scenarios were cut off mid-dialogue with the work discarded. Reasoning models
#: spend far longer per turn than the defaults were originally sized for.
PER_TURN_TIMEOUT = 1200    # seconds
PER_DIALOG_TIMEOUT = 5400  # seconds (90 min hard cap)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if BASE_ENV_FILE.exists():
        load_dotenv(BASE_ENV_FILE)


def _child_env() -> dict[str, str]:
    return os.environ.copy()


def _supervisor_specialist_command() -> list[str]:
    uv = shutil.which("uv")
    if uv is not None:
        return [uv, "run", "supervisor-specialist"]

    cli = shutil.which("supervisor-specialist")
    if cli is not None:
        return [cli]

    venv_cli = REPO_ROOT / ".venv" / "bin" / "supervisor-specialist"
    if venv_cli.exists():
        return [str(venv_cli)]

    raise RuntimeError("supervisor-specialist not found. Run `uv sync` first.")


#: A real REPL prompt is followed by silence, because the child is blocked on
#: stdin. Give the stream this long to prove otherwise.
_PROMPT_IDLE_S = 1.5


async def _prompt_confirmed(stream: asyncio.StreamReader, buf: bytearray) -> bool:
    """Distinguish the REPL prompt from a markdown blockquote in an answer.

    A line such as "> **Chiller 9: possible fouling**" ends with the same three
    bytes as the prompt ("\n> "). Matching on those alone made the harness think
    a turn had finished while the model was still printing it, so it ran ahead,
    closed stdin early and lost the final turn's answer.
    """
    try:
        extra = await asyncio.wait_for(stream.read(1), timeout=_PROMPT_IDLE_S)
    except asyncio.TimeoutError:
        return True  # nothing followed: genuine prompt
    if not extra:
        return True  # EOF
    buf.extend(extra)  # more text followed: it was blockquote markup
    return False


async def _read_until_prompt(
    stream: asyncio.StreamReader,
    timeout: int = PER_TURN_TIMEOUT,
) -> None:
    """Read stdout until the supervisor-specialist REPL prompt (`\\n> `) appears."""
    buf = bytearray()
    start = asyncio.get_event_loop().time()

    while True:
        if asyncio.get_event_loop().time() - start > timeout:
            raise TimeoutError(f"Timed out waiting for prompt after {timeout}s")

        try:
            chunk = await asyncio.wait_for(stream.read(1), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if not chunk:
            break

        buf.extend(chunk)
        if buf.endswith(b"\n> ") and await _prompt_confirmed(stream, buf):
            break


async def run_dialog(
    scenario: dict,
    log_dir: pathlib.Path,
    model_id: Optional[str],
    reuse_mode: str = "full",
    max_repeat_dispatch: int = 0,
    per_turn_timeout: int = PER_TURN_TIMEOUT,
) -> pathlib.Path | None:
    dialog_id = scenario["id"]
    turns = scenario["turns"]
    ref_date = scenario["reference_date"]
    existing_logs = set(log_dir.glob("case_*.jsonl"))

    print(f"Dialog {dialog_id:02d}: {scenario['title']} ({len(turns)} turns)")

    cmd = [
        *_supervisor_specialist_command(),
        "--reference-date", ref_date,
        "--log-dir", str(log_dir),
        "--no-stream",
        "--multi-turn",
        turns[0],
    ]
    if model_id:
        cmd.extend(["--model-id", model_id])
    cmd.extend(["--reuse-mode", reuse_mode])
    cmd.extend(["--max-repeat-dispatch", str(max_repeat_dispatch)])

    # Keep stderr: discarding it left agent-side exceptions undiagnosable, and a
    # turn can end with no answer and no message anywhere.
    stderr_path = log_dir / f"dialog_{dialog_id:02d}_stderr.txt"
    stderr_file = open(stderr_path, "wb")
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_file,
            cwd=REPO_ROOT,
            env=_child_env(),
        )

        for i, turn_text in enumerate(turns):
            if i > 0:
                assert proc.stdin is not None
                proc.stdin.write((turn_text + "\n").encode())
                await proc.stdin.drain()

            assert proc.stdout is not None
            await _read_until_prompt(proc.stdout, timeout=per_turn_timeout)
            print(f"  turn {i + 1}/{len(turns)} done")

        if proc.returncode is None:
            assert proc.stdin is not None
            proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout=15)
    finally:
        # asyncio.wait_for() cancels this coroutine at the dialog deadline.
        # CancelledError inherits BaseException, so an ``except Exception``
        # cleanup would miss it and leave the child running.
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
        stderr_file.close()

    new_logs = set(log_dir.glob("case_*.jsonl")) - existing_logs
    if not new_logs:
        print("  no behavior log found")
        return None

    newest = max(new_logs, key=lambda path: path.stat().st_mtime)
    print(f"  behavior log: {newest}")
    return newest


async def run_all(
    scenarios: list[dict],
    log_dir: pathlib.Path,
    dialog_ids: Optional[list[int]],
    model_id: Optional[str],
    reuse_mode: str = "full",
    max_repeat_dispatch: int = 0,
    per_turn_timeout: int = PER_TURN_TIMEOUT,
    per_dialog_timeout: int = PER_DIALOG_TIMEOUT,
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    if dialog_ids:
        scenarios = [s for s in scenarios if s["id"] in dialog_ids]
    if not scenarios:
        print("No matching scenarios found.")
        return

    print(f"Behavior log dir: {log_dir}")
    print(f"Reuse mode: {reuse_mode}")
    print(f"Timeouts: {per_turn_timeout}s/turn, {per_dialog_timeout}s/dialog")
    print(f"Dialogs: {[s['id'] for s in scenarios]}")

    for scenario in scenarios:
        try:
            await asyncio.wait_for(
                run_dialog(scenario, log_dir, model_id,
                           reuse_mode=reuse_mode,
                           max_repeat_dispatch=max_repeat_dispatch,
                           per_turn_timeout=per_turn_timeout),
                timeout=per_dialog_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            # asyncio.TimeoutError stringifies to "", which hides the cause.
            detail = str(exc) or f"{type(exc).__name__} (no message)"
            print(f"Dialog {scenario['id']:02d} failed: {detail}")


def main() -> None:
    _load_env()

    parser = argparse.ArgumentParser(
        description="Run supervisor-specialist scenarios and write behavior logs only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dialogs", nargs="+", type=int, metavar="N",
                        help="Dialog IDs to run (default: all 16).")
    parser.add_argument("--model-id", default=None,
                        help="Override LiteLLM model ID.")
    parser.add_argument("--log-dir", default=None,
                        help="Behavior log directory (default: logs/supervisor_specialist_eval/<timestamp>).")
    parser.add_argument("--reuse-mode", choices=["full", "none", "stateless"], default="full",
                        help="Cross-turn evidence reuse policy (default: full).")
    parser.add_argument("--max-repeat-dispatch", type=int, default=0,
                        help="Reject a specialist dispatched this many times in a row "
                             "within one turn (0 = off). Guards against the supervisor "
                             "looping on one specialist; every arm of a comparison must "
                             "use the same value.")
    parser.add_argument("--per-turn-timeout", type=int, default=PER_TURN_TIMEOUT,
                        help="Seconds allowed per turn (default: %(default)s). Raise this for "
                             "reuse ablations: without reuse every turn redoes the expensive "
                             "work, and truncation would bias both cost and completion metrics.")
    parser.add_argument("--per-dialog-timeout", type=int, default=PER_DIALOG_TIMEOUT,
                        help="Seconds allowed per dialog (default: %(default)s).")
    args = parser.parse_args()

    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from scenarios import SCENARIOS

    log_dir = (
        pathlib.Path(args.log_dir)
        if args.log_dir
        else DEFAULT_LOG_ROOT / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    )

    asyncio.run(run_all(SCENARIOS, log_dir, args.dialogs, args.model_id, args.reuse_mode,
                        args.max_repeat_dispatch,
                        args.per_turn_timeout, args.per_dialog_timeout))


if __name__ == "__main__":
    main()
