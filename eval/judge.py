"""Score a run's answers against the dataset reference, turn by turn.

    uv run python eval/judge.py --run logs/.../gpt-5.6-luna_full16_20260919 --dialogs 1

The dataset separates facts (data-verified), expectations (what an answer must
address) and pitfalls (claims that signal hallucination); the rubric below keeps
the six criteria used by assetopsbench's llm_judge so scores stay comparable in
shape, but grounds them in that structure rather than in a prose answer key.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "eval" / "dataset"))

RUBRIC = (
    "task_completion",
    "data_retrieval_accuracy",
    "generalized_result_verification",
    "agent_sequence_correct",
    "clarity_and_justification",
    "hallucinations",
)

_PROMPT = """You are grading one turn of a multi-turn industrial O&M dialogue.

Grade ONLY this turn's answer. Earlier turns are given for context.

## User's question this turn
{user}

## The agent's answer
{answer}

## What the agent actually did this turn

Tool calls made ({n_calls}):
{actual_calls}

Evidence reused from earlier turns ({n_reused}):
{reused}

## Reference for this turn

Evidence this turn's conclusions must rest on: {expected_domains}

IMPORTANT — how to apply that: the requirement is satisfied EITHER by calling a
tool in that domain this turn OR by reusing an artifact an earlier turn produced.
A turn that makes no tool calls because the evidence was already gathered is
behaving correctly; do NOT mark agent_sequence_correct down for it. Mark it down
only when a conclusion rests on evidence that was neither gathered nor reused.

Verified facts about the data (each re-checked against the live system today —
treat these as true; an answer contradicting one is wrong):
{facts}

The answer must address:
{expectations}

Signals of hallucination or a skipped step — if the answer does any of these,
say so explicitly and score hallucinations low:
{pitfalls}

Data caveats that constrain any numeric claim:
{caveats}

## Conversation so far
{history}

## How to score
Give each criterion 0.0-1.0 (1.0 = fully satisfied). Be strict: an answer that is
fluent but unsupported by the verified facts scores low on data_retrieval_accuracy
and hallucinations. An answer that correctly refuses or flags ambiguity is NOT
penalised — surfacing a limitation is a correct behaviour here.

Criteria:
- task_completion: did it do what the user asked this turn
- data_retrieval_accuracy: are the assets, sensors, periods and values right
- generalized_result_verification: is the result of the right kind, and checked
- agent_sequence_correct: is every conclusion backed by evidence that was either
  gathered this turn or reused from an earlier one, obtained in a sensible order
- clarity_and_justification: is the reasoning traceable to evidence
- hallucinations: 1.0 = nothing invented; 0.0 = key claims unsupported or contradicted

Return ONLY raw JSON:
{{"scores": {{{score_keys}}}, "evidence": "<2-3 sentences citing what you saw>", "pitfalls_hit": ["<pitfall text>", ...]}}
"""


def load_dataset_dialog(did: int):
    from schema import load_all
    for d in load_all():
        if d.id == did:
            return d
    raise SystemExit(f"dialog {did} not in dataset")


def extract_turns(log: pathlib.Path) -> list[dict]:
    """Per turn: the answer, the concrete calls made, and evidence reused.

    Domain names alone were not enough — the judge could not tell whether the
    inventory had actually been discovered and invented pitfalls instead. It also
    needs the reused artifacts, or it scores a turn that correctly answers from
    retained evidence as having skipped the work.
    """
    recs = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    turns = collections.defaultdict(
        lambda: {"answer": "", "domains": set(), "calls": [], "reused": [], "produced": []}
    )
    produced_by_turn: dict[str, str] = {}
    summaries: dict[str, str] = {}

    for r in recs:
        t = r.get("turn_id")
        if not t:
            continue
        for tc in (r.get("tool_calls") or []):
            name = tc["tool_name"]
            turns[t]["domains"].add(name.split(".")[0] if "." in name else name)
            key = {k: v for k, v in (tc.get("args") or {}).items()
                   if k in ("asset_id", "site_name", "start", "final", "group_by", "sort_by")}
            turns[t]["calls"].append(
                f"{name}({', '.join(f'{k}={v}' for k, v in key.items())})"
                + ("" if tc.get("status") == "ok" else " [FAILED]")
            )
        for a in (r.get("output_artifacts") or []):
            produced_by_turn[a["artifact_id"]] = t
            summaries[a["artifact_id"]] = (a.get("summary") or "")[:160]
            turns[t]["produced"].append(a["artifact_id"])
        for aid in (r.get("input_artifact_ids") or []):
            origin = produced_by_turn.get(aid)
            if origin and origin != t:
                entry = f"{aid} (from {origin}): {summaries.get(aid, '')}"
                if entry not in turns[t]["reused"]:
                    turns[t]["reused"].append(entry)
        if r["task_type"] == "final_response":
            turns[t]["answer"] = r.get("final_response") or ""
    return [turns[k] for k in sorted(turns)]


def find_log(run_dirs: list[pathlib.Path], dialog) -> pathlib.Path | None:
    """Match by the dialog's first user message, not by file order.

    Several directories may be given; later ones win. A run is often completed by
    a retry pass covering the dialogs that were truncated, and scoring the
    truncated original would penalise the arm for a run failure rather than for
    answer quality.
    """
    opening = dialog.turns[0].user[:60]
    found = None
    for run_dir in run_dirs:
        for p in sorted(run_dir.glob("case_*.jsonl"), key=lambda x: x.stat().st_mtime):
            first = p.read_text().splitlines()[0]
            if opening in json.loads(first).get("user_message", ""):
                found = p
    return found


def bullets(items) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, nargs="+",
                    help="One or more run directories; later ones override earlier.")
    ap.add_argument("--dialogs", nargs="+", type=int, required=True)
    ap.add_argument("--judge-model", default=None,
                    help="Defaults to DEFAULT_MODEL_ID. Using the same model that "
                         "produced the answers is self-evaluation; prefer a different one.")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    import os
    from llm.litellm import LiteLLMBackend
    from agent.supervisor_specialist._utils import parse_json_from_llm

    model = args.judge_model or os.environ["DEFAULT_MODEL_ID"]
    llm = LiteLLMBackend(model_id=model)
    run_dirs = [pathlib.Path(r) for r in args.run]
    print(f"judge model: {model}\nruns: {[str(r) for r in run_dirs]}\n")

    results = []
    for did in args.dialogs:
        dialog = load_dataset_dialog(did)
        log = find_log(run_dirs, dialog)
        if log is None:
            print(f"dialog {did}: no matching log in {run_dirs}")
            continue
        actual = extract_turns(log)
        print(f"=== Dialog {dialog.id}: {dialog.title} ({log.name}) ===")
        history = ""
        for turn in dialog.turns:
            got = (actual[turn.index - 1] if turn.index - 1 < len(actual)
                   else {"answer": "", "domains": set(), "calls": [], "reused": []})
            prompt = _PROMPT.format(
                user=turn.user,
                answer=got["answer"][:6000] or "(no answer produced)",
                n_calls=len(got["calls"]),
                actual_calls=bullets(got["calls"][:40]) if got["calls"]
                             else "- (no tool calls this turn)",
                n_reused=len(got["reused"]),
                reused=bullets(got["reused"]) if got["reused"]
                       else "- (no evidence reused from earlier turns)",
                expected_domains=", ".join(turn.evidence_domains) or "(unconstrained)",
                facts=bullets(f"{f.claim}" for f in turn.facts),
                expectations=bullets(turn.expectations),
                pitfalls=bullets(turn.pitfalls),
                caveats=bullets(dialog.data_caveats),
                history=history[:3000] or "(this is the first turn)",
                score_keys=", ".join(f'"{k}": 0.0' for k in RUBRIC),
            )
            raw = llm.generate(prompt)
            parsed = parse_json_from_llm(raw) or {}
            scores = {k: float(parsed.get("scores", {}).get(k, 0.0)) for k in RUBRIC}
            mean = statistics.mean(scores.values())
            print(f"  turn {turn.index}: [{len(got['calls'])} calls, "
                  f"{len(got['reused'])} reused] mean={mean:.2f}  " +
                  "  ".join(f"{k.split('_')[0]}={v:.2f}" for k, v in scores.items()))
            if parsed.get("pitfalls_hit"):
                for p in parsed["pitfalls_hit"]:
                    print(f"      pitfall hit: {p[:110]}")
            if parsed.get("evidence"):
                print(f"      {parsed['evidence'][:200]}")
            results.append({"dialog": did, "turn": turn.index, "scores": scores,
                            "mean": mean, "pitfalls_hit": parsed.get("pitfalls_hit", []),
                            "evidence": parsed.get("evidence", "")})
            history += f"\nTurn {turn.index} user: {turn.user}\nTurn {turn.index} answer: {got['answer'][:600]}\n"

    if results:
        print(f"\n{'─'*60}")
        for k in RUBRIC:
            print(f"  {k:34s} {statistics.mean(r['scores'][k] for r in results):.3f}")
        print(f"  {'OVERALL':34s} {statistics.mean(r['mean'] for r in results):.3f}")
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
