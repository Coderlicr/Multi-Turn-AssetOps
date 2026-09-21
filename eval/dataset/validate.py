"""Re-verify dataset facts against the live tools.

Reference answers derived from a system's own transcript are circular: score the
system against them and it wins by construction. This script breaks that loop by
re-checking every factual claim against the data the tools actually return.

    uv run python eval/dataset/validate.py            # all dialogs
    uv run python eval/dataset/validate.py --dialogs 1

Facts carrying `expect_contains` are checked automatically. Facts carrying only
`manual` are printed as outstanding — they need a human or a purpose-written
check, and are not counted as verified.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from schema import Dialog, load_all  # noqa: E402


async def check_fact(client, fact) -> tuple[str, str]:
    """Return (status, detail) for one fact."""
    if fact.check is None:
        return "no-check", "no check specified"
    if not fact.check.expect_contains and not fact.check.fn:
        return "manual", fact.check.manual or "manual verification required"

    result = await client.call(fact.check.tool, fact.check.args)
    if result.status != "ok":
        return "error", f"{fact.check.tool} failed: {result.error}"

    if fact.check.fn:
        import json

        import pandas as pd

        import checks

        try:
            payload = json.loads(str(result.result))
        except json.JSONDecodeError:
            return "error", f"{fact.check.tool} did not return JSON"
        csv_path = payload.get("csv_path") or payload.get("results_file")
        if not csv_path:
            return "error", f"{fact.check.tool} returned no csv_path"
        try:
            ok, detail = checks.get(fact.check.fn)(pd.read_csv(csv_path))
        except (KeyError, StopIteration, ValueError) as exc:
            return "error", f"check {fact.check.fn} raised {type(exc).__name__}: {exc}"
        return ("pass" if ok else "fail"), detail

    body = str(result.result)
    missing = [s for s in fact.check.expect_contains if s not in body]
    if missing:
        return "fail", f"missing from {fact.check.tool} response: {missing}"
    return "pass", f"{len(fact.check.expect_contains)} substring(s) confirmed"


async def run(dialogs: list[Dialog]) -> int:
    from agent.supervisor_specialist.runtime.mcp_tools import (
        DEFAULT_SERVER_PATHS,
        MCPToolClient,
    )

    client = MCPToolClient(server_paths=DEFAULT_SERVER_PATHS)
    counts = {"pass": 0, "fail": 0, "manual": 0, "error": 0, "no-check": 0}
    failures = []

    for dialog in dialogs:
        print(f"\n=== Dialog {dialog.id}: {dialog.title} ===")
        for turn in dialog.turns:
            for fact in turn.facts:
                status, detail = await check_fact(client, fact)
                counts[status] += 1
                mark = {"pass": "PASS", "fail": "FAIL", "manual": "MANUAL",
                        "error": "ERROR", "no-check": "SKIP"}[status]
                print(f"  [{mark:6s}] turn {turn.index} · {fact.id}")
                if status != "pass":
                    print(f"           {detail}")
                if status in ("fail", "error"):
                    failures.append(f"dialog {dialog.id} turn {turn.index} {fact.id}: {detail}")

    total = sum(counts.values())
    print(f"\n{'─' * 60}")
    print(f"{total} facts: {counts['pass']} pass, {counts['fail']} fail, "
          f"{counts['manual']} manual, {counts['error']} error")
    if counts["manual"]:
        print("Manual facts are NOT verified — treat them as provisional.")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dialogs", nargs="+", type=int, help="Dialog ids (default: all).")
    args = parser.parse_args()

    dialogs = load_all()
    if args.dialogs:
        dialogs = [d for d in dialogs if d.id in args.dialogs]
    if not dialogs:
        print("No dialogs matched.")
        raise SystemExit(1)
    print(f"Validating {len(dialogs)} dialog(s) on {datetime.date.today()}")
    raise SystemExit(asyncio.run(run(dialogs)))


if __name__ == "__main__":
    main()
