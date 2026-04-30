"""
Profiling harness for the supervisor-specialist system.

Drives each dialog scenario from scenarios.py through the supervisor-specialist
CLI, captures per-turn responses and timing, and writes structured results.

Usage:
    # Run all 16 dialogs
    uv run python eval/run_eval.py

    # Run specific dialogs
    uv run python eval/run_eval.py --dialogs 1 4 6

    # Tag the system being profiled (for WandB run grouping)
    uv run python eval/run_eval.py --system supervisor-specialist --dialogs 6

    # Override model or output directory
    uv run python eval/run_eval.py --model-id watsonx/meta-llama/llama-4-...
    uv run python eval/run_eval.py --output-dir eval/results/my_run

Profiling integrations (all opt-in via env vars):

    LangSmith  — set LANGCHAIN_API_KEY (+ optionally LANGCHAIN_PROJECT).
                 LiteLLM sends one trace per LLM call automatically.
                 On the supervisor-specialist branch, LangGraph adds graph-level
                 traces (per supervisor step, per specialist node) on top.

    WandB      — set WANDB_API_KEY. The harness calls wandb.log() after each
                 dialog with token counts, latency, and turn statistics.
                 Install with: uv add wandb

Output per run (in --output-dir):
    dialog_01.json  ... dialog_16.json   one JSON record per dialog
    summary.json                         aggregated stats + WandB run URL
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import pathlib
import shutil
import sys
import time
from typing import Optional

REPO_ROOT = pathlib.Path(__file__).parent.parent
EVAL_OUT_ROOT = REPO_ROOT / "eval" / "results"
BEHAVIOR_LOG_DIR = REPO_ROOT / "logs" / "supervisor_specialist"

PER_TURN_TIMEOUT = 360    # seconds
PER_DIALOG_TIMEOUT = 1500  # seconds (25 min hard cap)


# ── WandB helper ──────────────────────────────────────────────────────────────

def _wandb_init(run_id: str, system: str, dialog_ids: Optional[list[int]]) -> Optional[object]:
    """Initialize a WandB run if wandb is installed and WANDB_API_KEY is set."""
    if not os.environ.get("WANDB_API_KEY"):
        return None
    try:
        import wandb
        run = wandb.init(
            project=os.environ.get("WANDB_PROJECT", "multi-turn-assetops"),
            name=f"{system}__{run_id}",
            group=system,
            tags=[system] + ([f"dialog_{d}" for d in dialog_ids] if dialog_ids else ["all"]),
            config={"system": system, "run_id": run_id, "dialog_ids": dialog_ids or "all"},
        )
        print(f"WandB run: {run.url}")
        return wandb
    except ImportError:
        print("WandB not installed — skipping. Run `uv add wandb` to enable.")
        return None
    except Exception as exc:
        print(f"WandB init failed: {exc}")
        return None


def _wandb_log_dialog(wandb, result: dict, llm_metrics: dict) -> None:
    turns_ok = sum(1 for t in result.get("turns", []) if t.get("status") == "ok")
    turns_total = len(result.get("turns", []))
    wall_s = result.get("duration_seconds") or 0.0
    llm_s = llm_metrics.get("llm_latency_s", 0.0)

    wandb.log(
        {
            # identity
            "dialog/id": result["dialog_id"],
            "dialog/category": result["category"],
            "dialog/status": result["status"],
            # turn counts
            "dialog/turns_ok": turns_ok,
            "dialog/turns_total": turns_total,
            "dialog/turn_success_rate": turns_ok / turns_total if turns_total else 0,
            # wall-clock latency
            "latency/wall_s": wall_s,
            "latency/wall_per_turn_s": wall_s / turns_ok if turns_ok else 0,
            # LLM call metrics (from LITELLM_METRICS_FILE)
            "tokens/prompt": llm_metrics.get("prompt_tokens", 0),
            "tokens/completion": llm_metrics.get("completion_tokens", 0),
            "tokens/total": llm_metrics.get("total_tokens", 0),
            "tokens/per_turn": llm_metrics.get("total_tokens", 0) / turns_ok if turns_ok else 0,
            "llm/calls": llm_metrics.get("llm_calls", 0),
            "llm/calls_per_turn": llm_metrics.get("llm_calls", 0) / turns_ok if turns_ok else 0,
            "llm/latency_s": llm_s,
            # derived: how much of wall time was LLM vs tool/routing overhead
            "llm/fraction_of_wall": llm_s / wall_s if wall_s else 0,
            "llm/tool_overhead_s": max(wall_s - llm_s, 0),
        },
        step=result["dialog_id"],
    )


# ── LLM metrics file helpers ──────────────────────────────────────────────────

def _read_llm_metrics(path: pathlib.Path) -> dict:
    """Aggregate per-call records written by _MetricsFileLogger in litellm.py."""
    empty = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "total_tokens": 0, "llm_latency_s": 0.0}
    if not path.exists():
        return empty
    calls = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                calls.append(json.loads(line))
    except Exception:
        return empty
    return {
        "llm_calls": len(calls),
        "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in calls),
        "completion_tokens": sum(c.get("completion_tokens", 0) for c in calls),
        "total_tokens": sum(c.get("total_tokens", 0) for c in calls),
        "llm_latency_s": round(sum(c.get("latency_s", 0.0) for c in calls), 3),
    }


# ── subprocess helpers ────────────────────────────────────────────────────────

async def _read_until_prompt(reader: asyncio.StreamReader, timeout: float) -> str:
    """
    Read stdout until the CLI's '> ' input prompt appears or until EOF.

    The supervisor-specialist REPL uses Python's input("> "), which writes
    '> ' to stdout before blocking on stdin.  After each agent response the
    stream looks like:

        <response text>\n> <next response text>\n> ...

    We accumulate bytes until we see b"\\n> " at the tail, then return the
    accumulated text with the trailing prompt marker stripped.  EOF is handled
    the same way (last turn, process is about to exit).
    """
    buf = bytearray()
    deadline = asyncio.get_event_loop().time() + timeout
    last_data_at = asyncio.get_event_loop().time()

    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"Turn timed out after {timeout}s")

        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=min(remaining, 2.0))
        except asyncio.TimeoutError:
            idle = asyncio.get_event_loop().time() - last_data_at
            if idle >= 2.0 and buf[-2:] == b"> ":
                del buf[-2:]
                break
            continue

        if not chunk:  # EOF
            break

        last_data_at = asyncio.get_event_loop().time()
        buf.extend(chunk)

        if buf.endswith(b"\n> "):
            del buf[-3:]
            break

    return buf.decode("utf-8", errors="replace").strip()


# ── per-dialog runner ─────────────────────────────────────────────────────────

async def run_dialog(
    scenario: dict,
    output_dir: pathlib.Path,
    model_id: Optional[str],
    verbose: bool,
) -> tuple[dict, dict]:
    """Run one dialog. Returns (result_record, llm_metrics)."""
    dialog_id = scenario["id"]
    turns = scenario["turns"]
    ref_date = scenario["reference_date"]

    print(f"\n{'─'*70}")
    print(f"Dialog {dialog_id:02d} [{scenario['category']}]  {scenario['title']}")
    print(f"  {len(turns)} turns  |  reference date: {ref_date}")
    print(f"{'─'*70}")

    ss_cmd = shutil.which("supervisor-specialist")
    if ss_cmd is None:
        venv_bin = REPO_ROOT / ".venv" / "bin" / "supervisor-specialist"
        if venv_bin.exists():
            ss_cmd = str(venv_bin)
    if ss_cmd is None:
        raise RuntimeError(
            "supervisor-specialist not found in PATH or .venv/bin/. Run `uv sync` first."
        )

    cmd: list[str] = [
        ss_cmd,
        "--multi-turn",
        "--no-stream",
        "--reference-date", ref_date,
        turns[0],
    ]
    if model_id:
        cmd.extend(["--model-id", model_id])

    stderr_path = output_dir / f"dialog_{dialog_id:02d}_stderr.txt"
    metrics_path = output_dir / f"dialog_{dialog_id:02d}_llm_metrics.jsonl"

    # Pass metrics file path so LiteLLMBackend writes per-call records.
    child_env = {**os.environ, "LITELLM_METRICS_FILE": str(metrics_path)}

    result: dict = {
        "dialog_id": dialog_id,
        "title": scenario["title"],
        "category": scenario["category"],
        "reference_date": ref_date,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "completed_at": None,
        "duration_seconds": None,
        "status": "running",
        "error": None,
        "turns": [],
        "llm_metrics": None,
        "behavior_log": None,
        "stderr_file": str(stderr_path.relative_to(REPO_ROOT)),
        "llm_metrics_file": str(metrics_path.relative_to(REPO_ROOT)),
    }

    existing_logs = set(BEHAVIOR_LOG_DIR.glob("case_*.jsonl"))
    dialog_start = time.monotonic()

    try:
        with open(stderr_path, "wb") as stderr_fh:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr_fh,
                cwd=REPO_ROOT,
                env=child_env,
            )

        for i, turn_text in enumerate(turns):
            turn_start = time.monotonic()
            turn_record: dict = {
                "turn_index": i + 1,
                "user_message": turn_text,
                "response": None,
                "duration_seconds": None,
                "status": "running",
                "error": None,
            }

            preview = turn_text[:72] + ("…" if len(turn_text) > 72 else "")
            print(f"  T{i+1}/{len(turns)}  {preview}")

            if i > 0:
                try:
                    proc.stdin.write((turn_text + "\n").encode())
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError) as exc:
                    turn_record.update(status="error", error=f"stdin write failed: {exc}",
                                       duration_seconds=round(time.monotonic() - turn_start, 2))
                    result["turns"].append(turn_record)
                    result.update(status="crashed", error=str(exc))
                    break

            try:
                response = await asyncio.wait_for(
                    _read_until_prompt(proc.stdout, timeout=PER_TURN_TIMEOUT),
                    timeout=PER_TURN_TIMEOUT + 5,
                )
                elapsed = round(time.monotonic() - turn_start, 2)
                turn_record.update(response=response, duration_seconds=elapsed, status="ok")
                print(f"        ✓  {elapsed}s  |  {len(response):,} chars")
                if verbose:
                    print(f"        {response[:200]}{'…' if len(response) > 200 else ''}")

            except (TimeoutError, asyncio.TimeoutError) as exc:
                elapsed = round(time.monotonic() - turn_start, 2)
                turn_record.update(status="timed_out", error=str(exc), duration_seconds=elapsed)
                print(f"        ✗  TIMEOUT after {elapsed}s")
                result["turns"].append(turn_record)
                result.update(status="timed_out", error=f"Turn {i+1} timed out after {elapsed}s")
                proc.kill()
                break

            result["turns"].append(turn_record)

        # Close subprocess cleanly.
        if proc.returncode is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

        if result["status"] == "running":
            result["status"] = "completed" if proc.returncode == 0 else "crashed"
            if proc.returncode not in (0, None):
                result["error"] = f"Process exited with code {proc.returncode}"

    except Exception as exc:  # noqa: BLE001
        result.update(status="crashed", error=str(exc))
        print(f"  ERROR: {exc}")

    # Finalize.
    total = round(time.monotonic() - dialog_start, 2)
    result["duration_seconds"] = total
    result["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    new_logs = set(BEHAVIOR_LOG_DIR.glob("case_*.jsonl")) - existing_logs
    if new_logs:
        newest = max(new_logs, key=lambda p: p.stat().st_mtime)
        result["behavior_log"] = str(newest.relative_to(REPO_ROOT))

    llm_metrics = _read_llm_metrics(metrics_path)
    result["llm_metrics"] = llm_metrics

    ok_turns = sum(1 for t in result["turns"] if t["status"] == "ok")
    icon = {"completed": "✓", "crashed": "✗", "timed_out": "⏱"}.get(result["status"], "?")
    print(
        f"  {icon}  {result['status'].upper()}  {total}s  |  "
        f"{ok_turns}/{len(turns)} turns  |  "
        f"{llm_metrics['total_tokens']} tokens  |  "
        f"{llm_metrics['llm_calls']} LLM calls"
    )
    return result, llm_metrics


# ── top-level runner ──────────────────────────────────────────────────────────

async def run_all(
    scenarios: list,
    output_dir: pathlib.Path,
    model_id: Optional[str],
    dialog_ids: Optional[list[int]],
    system: str,
    verbose: bool,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    if dialog_ids:
        scenarios = [s for s in scenarios if s["id"] in dialog_ids]
    if not scenarios:
        print("No matching scenarios found.")
        return {}

    run_id = f"run_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    print(f"\nEval run : {run_id}")
    print(f"System   : {system}")
    print(f"Output   : {output_dir}")
    print(f"Dialogs  : {[s['id'] for s in scenarios]}")

    wandb = _wandb_init(run_id, system, dialog_ids)

    all_results: list[dict] = []
    all_llm_metrics: list[dict] = []
    overall_start = time.monotonic()

    for scenario in scenarios:
        try:
            result, llm_metrics = await asyncio.wait_for(
                run_dialog(scenario, output_dir, model_id, verbose),
                timeout=PER_DIALOG_TIMEOUT,
            )
        except asyncio.TimeoutError:
            result = {
                "dialog_id": scenario["id"], "title": scenario["title"],
                "category": scenario["category"], "reference_date": scenario["reference_date"],
                "status": "timed_out", "error": f"Dialog-level timeout ({PER_DIALOG_TIMEOUT}s)",
                "turns": [], "duration_seconds": PER_DIALOG_TIMEOUT,
                "llm_metrics": None, "behavior_log": None, "stderr_file": None,
            }
            llm_metrics = {}
            print(f"  ⏱  Dialog {scenario['id']} hit {PER_DIALOG_TIMEOUT}s hard cap")

        out_file = output_dir / f"dialog_{scenario['id']:02d}.json"
        out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        all_results.append(result)
        all_llm_metrics.append(llm_metrics)

        if wandb and llm_metrics:
            _wandb_log_dialog(wandb, result, llm_metrics)

    # ── summary ───────────────────────────────────────────────────────────────
    counts = {s: sum(1 for r in all_results if r["status"] == s)
              for s in ("completed", "crashed", "timed_out")}
    total_turns_ok = sum(
        sum(1 for t in r.get("turns", []) if t.get("status") == "ok")
        for r in all_results
    )
    total_turns = sum(len(s["turns"]) for s in scenarios)
    total_tokens = sum(m.get("total_tokens", 0) for m in all_llm_metrics)
    total_llm_calls = sum(m.get("llm_calls", 0) for m in all_llm_metrics)

    if wandb:
        wandb.log({
            "run/dialogs_completed": counts["completed"],
            "run/dialogs_crashed": counts["crashed"],
            "run/dialogs_timed_out": counts["timed_out"],
            "run/turns_ok": total_turns_ok,
            "run/turns_total": total_turns,
            "run/total_tokens": total_tokens,
            "run/total_llm_calls": total_llm_calls,
            "run/wall_time_s": round(time.monotonic() - overall_start, 2),
        })
        wandb.finish()

    summary = {
        "run_id": run_id,
        "system": system,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_dialogs": len(all_results),
        **counts,
        "turns_ok": total_turns_ok,
        "turns_total": total_turns,
        "total_tokens": total_tokens,
        "total_llm_calls": total_llm_calls,
        "wall_time_seconds": round(time.monotonic() - overall_start, 2),
        "output_dir": str(output_dir),
        "dialogs": [
            {
                "id": r["dialog_id"],
                "title": r["title"],
                "category": r["category"],
                "status": r["status"],
                "duration_seconds": r.get("duration_seconds"),
                "turns_ok": sum(1 for t in r.get("turns", []) if t.get("status") == "ok"),
                "turns_total": len(r.get("turns", [])),
                "llm_metrics": r.get("llm_metrics"),
                "behavior_log": r.get("behavior_log"),
                "error": r.get("error"),
            }
            for r in all_results
        ],
    }
    summary_file = output_dir / "summary.json"
    summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"\n{'='*70}")
    print(f"Run complete : {run_id}  [{system}]")
    print(f"  Completed  : {counts['completed']}/{len(all_results)}")
    print(f"  Crashed    : {counts['crashed']}")
    print(f"  Timed out  : {counts['timed_out']}")
    print(f"  Turns ok   : {total_turns_ok}/{total_turns}")
    print(f"  Tokens     : {total_tokens:,}")
    print(f"  LLM calls  : {total_llm_calls}")
    print(f"  Summary    : {summary_file}")
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run evaluation harness with profiling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dialogs", nargs="+", type=int, metavar="N",
                        help="Dialog IDs to run (default: all 16).")
    parser.add_argument("--system", default="supervisor-specialist",
                        help="System name tag for WandB grouping (default: supervisor-specialist).")
    parser.add_argument("--model-id", default=None,
                        help="Override LiteLLM model ID.")
    parser.add_argument("--output-dir", default=None,
                        help="Results directory (default: eval/results/<timestamp>).")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print a short preview of each turn response.")
    args = parser.parse_args()

    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from scenarios import SCENARIOS

    out_dir = (
        pathlib.Path(args.output_dir) if args.output_dir
        else EVAL_OUT_ROOT / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    )

    asyncio.run(run_all(SCENARIOS, out_dir, args.model_id, args.dialogs, args.system, args.verbose))


if __name__ == "__main__":
    main()
