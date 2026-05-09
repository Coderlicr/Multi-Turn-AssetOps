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
                 dialog and each turn with token counts, latency, and turn
                 statistics.
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
BASE_ENV_FILE = REPO_ROOT / ".env"
PROFILING_ENV_FILE = REPO_ROOT / ".env.profiling"

PER_TURN_TIMEOUT = 360    # seconds
PER_DIALOG_TIMEOUT = 1500  # seconds (25 min hard cap)

PROFILE_ENV_KEYS = (
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_PROJECT",
    "WANDB_API_KEY",
    "WANDB_PROJECT",
)


# ── environment helpers ───────────────────────────────────────────────────────

def _load_eval_env() -> None:
    """Load runtime env first, then profiling-only env for the harness."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    if BASE_ENV_FILE.exists():
        load_dotenv(BASE_ENV_FILE)
        _warn_profile_keys_in_base_env()
    if PROFILING_ENV_FILE.exists():
        load_dotenv(PROFILING_ENV_FILE, override=True)


def _warn_profile_keys_in_base_env() -> None:
    """Warn when profiling keys are still stored in .env."""
    try:
        text = BASE_ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    present = [
        key for key in PROFILE_ENV_KEYS
        if any(line.strip().startswith(f"{key}=") for line in text.splitlines())
    ]
    if present:
        print(
            "Warning: profiling key(s) still appear in .env: "
            f"{', '.join(present)}. Move them to .env.profiling so MCP "
            "subprocesses do not reload profiling credentials."
        )


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
        wandb.define_metric("dialog/id")
        wandb.define_metric("dialog/*", step_metric="dialog/id")
        wandb.define_metric("latency/*", step_metric="dialog/id")
        wandb.define_metric("tokens/*",  step_metric="dialog/id")
        wandb.define_metric("llm/*",     step_metric="dialog/id")
        wandb.define_metric("tool/*",    step_metric="dialog/id")
        wandb.define_metric("couchdb/*", step_metric="dialog/id")
        wandb.define_metric("run/*",     step_metric="dialog/id")
        wandb.define_metric("turn/index")
        wandb.define_metric("turn/*", step_metric="turn/index")
        wandb.define_metric("llm_call/index")
        wandb.define_metric("llm_call/*", step_metric="llm_call/index")
        print(f"WandB run: {run.url}")
        return wandb
    except ImportError:
        print("WandB not installed — skipping. Run `uv add wandb` to enable.")
        return None
    except Exception as exc:
        print(f"WandB init failed: {exc}")
        return None


def _wandb_log_dialog(wandb, result: dict, llm_metrics: dict, tool_metrics: dict | None = None) -> None:
    turns_ok = sum(1 for t in result.get("turns", []) if t.get("status") == "ok")
    turns_total = len(result.get("turns", []))
    wall_s = result.get("duration_seconds") or 0.0
    llm_s = llm_metrics.get("llm_latency_s", 0.0)
    tool_s = (tool_metrics or {}).get("total_latency_s", 0.0)
    routing_s = max(wall_s - llm_s - tool_s, 0.0)

    wandb.log({
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
        # 3-way latency breakdown: llm / tool / routing
        "latency/llm_s": llm_s,
        "latency/llm_fraction": llm_s / wall_s if wall_s else 0,
        "latency/tool_s": tool_s,
        "latency/tool_fraction": tool_s / wall_s if wall_s else 0,
        "latency/routing_s": routing_s,
        "latency/routing_fraction": routing_s / wall_s if wall_s else 0,
    })


def _wandb_log_turns(wandb, result: dict, turn_offset: int = 0) -> None:
    """Log per-turn metrics using a globally unique turn index.

    turn_offset is the total number of turns already logged across all
    previous dialogs, so turn/index is unique across the whole run and
    turn/* keys stay one level deep (matching the define_metric glob).
    """
    ok_so_far = 0
    dialog_id = result["dialog_id"]

    for turn in result.get("turns", []):
        turn_index = turn.get("turn_index", 0)
        status = turn.get("status", "unknown")
        if status == "ok":
            ok_so_far += 1

        response = turn.get("response") or ""
        duration_s = turn.get("duration_seconds") or 0.0
        dialog_key = f"dialog_{dialog_id:02d}"
        wandb.log({
            # cross-dialog view: all turns on one continuous x-axis
            "turn/index": turn_offset + turn_index,
            "turn/dialog_id": dialog_id,
            "turn/turn_in_dialog": turn_index,
            "turn/duration_s": duration_s,
            "turn/status_ok": 1 if status == "ok" else 0,
            "turn/response_chars": len(response),
            "turn/cumulative_success_rate": (
                ok_so_far / turn_index if turn_index else 0
            ),
            "turn/status": status,
            # per-dialog view: each dialog gets its own charts, x-axis is 1..N
            f"per_dialog/{dialog_key}/duration_s": duration_s,
            f"per_dialog/{dialog_key}/status_ok": 1 if status == "ok" else 0,
            f"per_dialog/{dialog_key}/response_chars": len(response),
            f"per_dialog/{dialog_key}/cumulative_success_rate": (
                ok_so_far / turn_index if turn_index else 0
            ),
        })


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


def _read_llm_calls(path: pathlib.Path) -> list:
    """Return raw per-call records from the LLM metrics JSONL file."""
    if not path.exists():
        return []
    calls = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                calls.append(json.loads(line))
    except Exception:
        pass
    return calls


def _wandb_log_llm_calls(wandb, calls: list, call_offset: int, dialog_id: int) -> None:
    """Log one WandB point per LLM call with a globally unique llm_call/index."""
    for i, call in enumerate(calls):
        latency = call.get("latency_s", 0.0)
        completion = call.get("completion_tokens", 0)
        wandb.log({
            "llm_call/index":            call_offset + i + 1,
            "llm_call/dialog_id":        dialog_id,
            "llm_call/prompt_tokens":    call.get("prompt_tokens", 0),
            "llm_call/completion_tokens": completion,
            "llm_call/total_tokens":     call.get("total_tokens", 0),
            "llm_call/latency_s":        latency,
            "llm_call/tokens_per_second": call.get("tokens_per_second",
                round(completion / latency, 2) if latency > 0 else 0),
            "llm_call/model":            call.get("model", ""),
        })


def _read_tool_metrics(path: pathlib.Path) -> dict:
    """Aggregate tool-call records from TOOL_METRICS_FILE by server."""
    if not path.exists():
        return {}
    by_server: dict = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            srv = rec.get("server", "unknown")
            s = by_server.setdefault(srv, {"calls": 0, "latency_s": 0.0, "errors": 0})
            s["calls"] += 1
            s["latency_s"] = round(s["latency_s"] + rec.get("latency_s", 0.0), 4)
            if rec.get("status") != "ok":
                s["errors"] += 1
    except Exception:
        pass
    total_calls = sum(s["calls"] for s in by_server.values())
    total_latency = round(sum(s["latency_s"] for s in by_server.values()), 4)
    return {"by_server": by_server, "total_calls": total_calls, "total_latency_s": total_latency}


def _wandb_log_tool_metrics(wandb, tool_metrics: dict, dialog_id: int) -> None:
    if not tool_metrics:
        return
    payload = {
        "dialog/id": dialog_id,
        "tool/total_calls":   tool_metrics.get("total_calls", 0),
        "tool/total_latency_s": tool_metrics.get("total_latency_s", 0.0),
    }
    for server, stats in tool_metrics.get("by_server", {}).items():
        payload[f"tool/{server}/calls"]     = stats["calls"]
        payload[f"tool/{server}/latency_s"] = stats["latency_s"]
        payload[f"tool/{server}/errors"]    = stats["errors"]
    wandb.log(payload)


def _read_couchdb_metrics(path: pathlib.Path) -> dict:
    """Aggregate CouchDB query records from COUCHDB_METRICS_FILE by server."""
    if not path.exists():
        return {}
    by_server: dict = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            srv = rec.get("server", "unknown")
            s = by_server.setdefault(srv, {"queries": 0, "latency_s": 0.0,
                                           "docs_returned": 0, "errors": 0})
            s["queries"] += 1
            s["latency_s"] = round(s["latency_s"] + rec.get("latency_s", 0.0), 4)
            s["docs_returned"] += rec.get("docs_returned", 0)
            if rec.get("status") != "ok":
                s["errors"] += 1
    except Exception:
        pass
    total_queries = sum(s["queries"] for s in by_server.values())
    total_latency = round(sum(s["latency_s"] for s in by_server.values()), 4)
    return {"by_server": by_server, "total_queries": total_queries, "total_latency_s": total_latency}


def _wandb_log_couchdb_metrics(wandb, couchdb_metrics: dict, dialog_id: int) -> None:
    if not couchdb_metrics:
        return
    payload = {
        "dialog/id": dialog_id,
        "couchdb/total_queries":   couchdb_metrics.get("total_queries", 0),
        "couchdb/total_latency_s": couchdb_metrics.get("total_latency_s", 0.0),
    }
    for server, stats in couchdb_metrics.get("by_server", {}).items():
        payload[f"couchdb/{server}/queries"]       = stats["queries"]
        payload[f"couchdb/{server}/latency_s"]     = stats["latency_s"]
        payload[f"couchdb/{server}/docs_returned"] = stats["docs_returned"]
        payload[f"couchdb/{server}/errors"]        = stats["errors"]
    wandb.log(payload)


# ── child process environment helpers ─────────────────────────────────────────

def _make_child_env(metrics_path: pathlib.Path) -> dict[str, str]:
    """
    Build the supervisor-specialist subprocess env.

    The eval harness may use WandB/LangSmith itself, but MCP servers communicate
    over stdio and expect stdout to contain only JSON-RPC. Prevent WandB console
    banners from leaking into those streams.
    """
    child_env = dict(os.environ)
    for key in list(child_env):
        if key.startswith("WANDB_"):
            del child_env[key]

    for key in (
        "WANDB_API_KEY",
        "WANDB_BASE_URL",
        "WANDB_ENTITY",
        "WANDB_PROJECT",
        "WANDB_RUN_ID",
        "WANDB_RUN_GROUP",
        "WANDB_RUN_NAME",
        "WANDB_TAGS",
    ):
        child_env[key] = ""

    child_env["LITELLM_METRICS_FILE"] = str(metrics_path)
    child_env["TOOL_METRICS_FILE"] = str(metrics_path).replace("llm_metrics", "tool_metrics")
    child_env["COUCHDB_METRICS_FILE"] = str(metrics_path).replace("llm_metrics", "couchdb_metrics")
    child_env["WANDB_DISABLED"] = "true"
    child_env["WANDB_SILENT"] = "true"
    child_env["WANDB_CONSOLE"] = "off"
    child_env["WANDB_MODE"] = "disabled"
    return child_env


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

    # Pass metrics file path while keeping WandB output out of MCP stdio.
    child_env = _make_child_env(metrics_path)

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
    turn_offset = 0   # globally unique turn counter across all dialogs
    call_offset = 0   # globally unique LLM call counter across all dialogs

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

        dialog_id = result["dialog_id"]
        metrics_path = output_dir / f"dialog_{dialog_id:02d}_llm_metrics.jsonl"
        llm_calls = _read_llm_calls(metrics_path)
        tool_metrics_path = output_dir / f"dialog_{dialog_id:02d}_tool_metrics.jsonl"
        couchdb_metrics_path = output_dir / f"dialog_{dialog_id:02d}_couchdb_metrics.jsonl"

        if wandb and llm_metrics:
            tool_metrics = _read_tool_metrics(tool_metrics_path)
            _wandb_log_dialog(wandb, result, llm_metrics, tool_metrics)
            _wandb_log_turns(wandb, result, turn_offset)
            _wandb_log_llm_calls(wandb, llm_calls, call_offset, dialog_id)
            _wandb_log_tool_metrics(wandb, tool_metrics, dialog_id)
            _wandb_log_couchdb_metrics(wandb, _read_couchdb_metrics(couchdb_metrics_path), dialog_id)
        turn_offset += len(result.get("turns", []))
        call_offset += len(llm_calls)

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
    _load_eval_env()

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
