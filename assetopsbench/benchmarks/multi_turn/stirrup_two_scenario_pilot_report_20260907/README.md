# Stirrup Multi-Turn Benchmark: Two-Scenario Pilot Report

> Correction: A16-06's original chiller golden answer was introduced for the
> pilot and is not independently validated. Its recorded pass is a pipeline
> check, not a validated diagnostic result. The bundled inputs are being
> migrated to the three-file contract: numbered user turns are read directly
> from question.txt, with no conversation.json. Results below remain historical
> evidence of the September 7 run; do not treat them as rerun results.

**Run date:** September 7, 2026  
**Agent:** Stirrup multi-turn runner  
**Model:** `tokenrouter/z-ai/glm-5.3-free`

## Executive Summary

We constructed and executed two multi-turn benchmark scenarios: one adapted
from the original 16-dialog set (`A16-06`) and one selected from the new
50-scenario set (`WTB01`). Both scenarios passed strict final-answer evaluation:
the model's final JSON output matched the corresponding static ground truth.

| Scenario | Source set | User turns | Static JSON score | Duration | Tool calls, including `finish` | Input / output tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `A16-06` | Original 16-dialog set | 3 | 1.0 (pass) | 225.7 s | 10 | 146,759 / 2,063 |
| `WTB01` | New 50-scenario set | 4 | 1.0 (pass) | 506.8 s | 26 | 141,828 / 4,914 |

The combined conversation time was approximately 12 minutes and 12 seconds,
excluding environment preparation. Total usage was 288,587 input tokens and
6,977 output tokens. The evaluation report did not provide an actual billed
cost.

## Agent and Evaluation Configuration

The pilot used the following fixed configuration:

| Setting | Value |
| --- | --- |
| Agent implementation | Stirrup through `StirrupAgentRunner` |
| Conversation execution | One persistent Stirrup and MCP session per scenario |
| Model | `tokenrouter/z-ai/glm-5.3-free` |
| Temperature | `0` |
| Reasoning effort | Not explicitly set; provider default |
| Code execution | Disabled |
| Agent-step budget | Maximum 12 steps per user turn |
| Final evaluator | AssetOpsBench `static_json` scorer |
| Pass criterion | Strict structured match with `groundtruth.txt` |

The runner supplies one user message at a time and preserves the live Stirrup
conversation and tool context for later turns. Future user turns are not shown
to the agent in advance.

## Scenario Construction

Both cases use the standard AssetOpsBench scenario-directory contract and add
one multi-turn extension file:

```text
scenario_<id>/
├── manifest.json       Environment state required by the scenario
├── question.txt        Human-readable multi-turn transcript
├── groundtruth.txt     Static JSON used for final-answer evaluation
└── conversation.json   Ordered turns, dependencies, tool expectations, and truth
```

The loader checks that the final turn's `ground_truth` in `conversation.json`
exactly matches `groundtruth.txt`, preventing the two truth sources from
drifting apart.

### Scenario A16-06: Knowledge Discovery and Onboarding

This three-turn scenario is an executable pilot adaptation of `A16-06` from the
original 16-dialog set.

1. The user asks which sites and assets are available for monitoring.
2. The user refers to the discovered `Chiller 6` and asks for its installed
   sensors and available time-series analyses.
3. The user refers to "these sensors" and requests the matching failure modes
   as JSON only.

The scenario tests reference resolution, information accumulation, and
cross-turn tool use across the `iot`, `tsfm`, and `fmsr` MCP servers. Its
scenario-local manifest loads the Chiller 6 telemetry and asset registry,
model and feature catalogs, and a curated chiller failure-mode record into
CouchDB.

The final static ground truth is:

```json
{
  "failure_modes": [
    "condenser fouling",
    "refrigerant leakage",
    "compressor oil pressure loss"
  ]
}
```

This should be treated as a pilot adaptation: the original development dialog
did not provide a directly executable scenario manifest or static final-answer
ground truth. Those elements were curated for this run while preserving the
dialog's original task progression.

### Scenario WTB01: Replacement and Repair Analysis

This four-turn scenario comes from the new 50-scenario set and runs against the
bundled read-only MaintIE corpus.

1. The user asks for replacement versus repair job counts.
2. The user narrows the previous replacement set and asks which equipment class
   occurs most often.
3. The user asks whether "change out" is included in the replacement category.
4. The user reuses the established replacement semantics and asks for the top
   three equipment classes as JSON only.

The scenario tests reference resolution, information accumulation, constraint
updates, clarification, and cross-turn tool use. It uses the `maintie` MCP
server and requires no CouchDB state.

The final static ground truth is:

```json
{
  "top3": [
    ["Lines & drives", 89],
    ["Engines & motors", 44],
    ["Structural/mounting parts", 36]
  ]
}
```

## Final Model Outputs

`A16-06`:

```json
{"failure_modes":["condenser fouling","refrigerant leakage","compressor oil pressure loss"]}
```

`WTB01`:

```json
{"top3":[["Lines & drives",89],["Engines & motors",44],["Structural/mounting parts",36]]}
```

Both outputs received a strict exact-match score of `1.0`, with no missing or
extra keys.

## Trajectory Observations

- In `A16-06`, the agent did not call the expected TSFM `list_tasks` tool during
  the second user turn. It called `installed_sensors`, `measured_sensors`, and
  `stream_extent` instead. Passing the final-answer check does not imply that
  every intermediate response or expected tool path was satisfied.
- In `WTB01`, two `rank` calls in the second user turn failed validation because
  of a nested-list value supplied to a filter field. The agent recovered and
  continued successfully.
- In `WTB01`, the clarification about "change out" triggered 12 `count` calls,
  creating substantial avoidable tool overhead. The final turn then reused the
  earlier ranking and only called `finish`.
- The poor-performance report filters scenarios only by final static-JSON
  failure. It is therefore empty even though the trajectories reveal efficiency
  and intermediate-path issues.

## Interpretation

The pilot demonstrates that the multi-turn runner can preserve context across
user turns and produce the required final structured answers for both an
AssetOps-style equipment scenario and a MaintIE work-order scenario.

The result should be reported as a **100% final-answer pass rate on this
two-scenario pilot**, not as evidence that all intermediate reasoning and tool
behavior were optimal. A larger evaluation would need separate scoring for
intermediate-turn correctness and tool-path efficiency.

## Included Evidence

This package contains:

- the complete scenario definitions, manifests, questions, and static truths;
- the full Stirrup trajectories for both runs;
- the complete AssetOpsBench aggregate static-JSON report; and
- the poor-performance-only report, whose scenario list is empty because both
  final answers passed.

Before the successful run, an initial launch was stopped after discovering that
configuration loaded through `.env.public` was not visible to the MCP
subprocesses. The configuration was copied to a local `.env`, and both scenarios
were then rerun completely. Only the complete rerun trajectories are included
in this report.
