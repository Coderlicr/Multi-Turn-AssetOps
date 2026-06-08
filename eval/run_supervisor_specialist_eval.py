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
PER_TURN_TIMEOUT = 360
PER_DIALOG_TIMEOUT = 1500


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
        if buf.endswith(b"\n> "):
            break


async def run_dialog(
    scenario: dict,
    log_dir: pathlib.Path,
    model_id: Optional[str],
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

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=REPO_ROOT,
        env=_child_env(),
    )

    try:
        for i, turn_text in enumerate(turns):
            if i > 0:
                assert proc.stdin is not None
                proc.stdin.write((turn_text + "\n").encode())
                await proc.stdin.drain()

            assert proc.stdout is not None
            await _read_until_prompt(proc.stdout, timeout=PER_TURN_TIMEOUT)
            print(f"  turn {i + 1}/{len(turns)} done")

        if proc.returncode is None:
            assert proc.stdin is not None
            proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout=15)
    except Exception:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise

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
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    if dialog_ids:
        scenarios = [s for s in scenarios if s["id"] in dialog_ids]
    if not scenarios:
        print("No matching scenarios found.")
        return

    print(f"Behavior log dir: {log_dir}")
    print(f"Dialogs: {[s['id'] for s in scenarios]}")

    for scenario in scenarios:
        try:
            await asyncio.wait_for(
                run_dialog(scenario, log_dir, model_id),
                timeout=PER_DIALOG_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Dialog {scenario['id']:02d} failed: {exc}")


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
    args = parser.parse_args()

    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from scenarios import SCENARIOS

    log_dir = (
        pathlib.Path(args.log_dir)
        if args.log_dir
        else DEFAULT_LOG_ROOT / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    )

    asyncio.run(run_all(SCENARIOS, log_dir, args.dialogs, args.model_id))


if __name__ == "__main__":
    main()
