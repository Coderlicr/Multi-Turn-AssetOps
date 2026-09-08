# Stirrup Multi-Turn Benchmark

## Current three-file input contract

The runner now reads each user turn directly from `question.txt` using sequential
`User turn 1:`, `User turn 2:`, etc. headers. Messages may span multiple lines.
`conversation.json` is no longer read or required. Only `manifest.json`,
`question.txt`, and `groundtruth.txt` are required for a scenario; supporting
environment data belongs outside the scenario folder and is referenced by the
manifest. Final truth is read only from `groundtruth.txt`.

The three-file format contains no intermediate answer or optimal-path labels.
Use final `static_json` scoring, not the legacy annotated JSONL evaluator, for
these folders. MCP servers are selected from the manifest's IoT/asset, TSFM
catalog, and failure-mode collections; empty WTB manifests select MaintIE.

The A16-06 chiller truth from the first pilot is not independently validated.
The upstream shared FMEA sample contains only pump modes and explicitly labels
them synthetic and non-exhaustive. It must not be relabeled as verified chiller
diagnostic data. A16-06 keeps its original Chiller 6 questions, references that
unchanged shared sample, and has `null` in `groundtruth.txt`. Its formal run is
suspended before any database/model activity; the evaluator excludes it. `null`
means unavailable truth, not an expected null answer or an empty failure list.

Run the currently scoreable scenario with:

```bash
SCENARIO_IDS=WTB01 ENV_FILE=.env ./benchmarks/run_multi_turn.sh
```

The default two-scenario run intentionally reports that A16-06 is suspended.
Free TokenRouter models are paced at one request every 8 seconds after the
gateway returned its 8-requests/minute limit. Earlier results remain historical.

This directory implements the work guide's new project boundary: AssetOpsBench
is the environment, Stirrup is the only agent under test, and conversations are
the benchmark cases. The former Supervisor/Specialist architecture is not part
of this implementation.

## What the upstream Stirrup runner does

The upstream `StirrupAgentRunner` is an in-process adapter around Stirrup 0.2.0:

1. It routes `litellm_proxy/*` and `tokenrouter/*` model IDs through an
   OpenAI-compatible chat client, and native `provider/model` IDs through
   Stirrup's LiteLLM client.
2. It starts selected AssetOpsBench MCP servers as stdio subprocesses and
   exposes their tools as `{server}__{tool}`.
3. In the code track it also adds `code_exec`; in the tools-only track used here
   it exposes only domain MCP tools.
4. A Stirrup agent loop alternates model generations and tool execution until
   the custom `finish` tool returns the user-facing answer.
5. Every assistant generation becomes an AssetOpsBench agent-step record with
   text, tool inputs/outputs, tokens, and timing.

Upstream `run(question)` creates one Stirrup agent session for one question.
That is a multi-step tool loop, but it is not a multi-user-turn conversation.

## The multi-turn extension

`StirrupAgentRunner.run_conversation()` keeps one Stirrup session and its MCP
providers open for the whole scenario. It sends exactly one user message at a
time, carries the live returned message context into the next call, and never
reveals future user turns. The saved shape explicitly separates:

```text
conversation trajectory
└── user_turns[]                  actual User/Conversation Turns
    ├── user_message
    ├── answer
    └── trajectory.turns[]       internal Stirrup Agent Steps
        └── tool_calls[]
```

This is the central invariant of the benchmark. Tool-provider state, code
workspace state, context summaries, tool results, and assistant messages can
cross user turns, while evaluation can still identify the exact failing user
turn and internal agent step.

## Scenario format

The versioned schema is implemented in
`src/benchmark/multi_turn_schema.py`. A scenario has:

- scenario level: `scenario_id`, `source`, `split`, `description`,
  `overall_user_goal`, `overall_expected_outcome`, `context_dependency`,
  `required_tools`, `executable`, `valid_multi_turn`, and audit notes;
- turn level: `user_message`, `dependency_on_previous_turns`,
  `dependency_types`, `expected_information`, `expected_tool_behavior`,
  accepted equivalent tool plans, and `ground_truth`.

`dependency_types` uses the five guide categories: reference resolution,
information accumulation, constraint update, cross-turn tool use, and
correction/clarification.

The current two-scenario pilot uses the repository's canonical folder layout:

```text
src/couchdb/scenarios_data/
├── scenario_A16-06/
│   ├── manifest.json
│   ├── question.txt
│   └── groundtruth.txt
└── scenario_WTB01/
    ├── manifest.json
    ├── question.txt
    └── groundtruth.txt
```

`manifest.json` references shared environment files, `question.txt` contains
numbered user messages, and `groundtruth.txt` is the single final-truth source.
Each header must be on its own line, numbered consecutively from 1. Empty turns
and text before the first header are rejected. Intermediate scoring metadata
remains available only in the legacy JSONL datasets.

Only two cases are selected for the pilot:

- `A16-06`, retained from the old 16-dialog set, with formal scoring suspended
  until validated Chiller 6 ground truth is available;
- `WTB01`, selected from the new 50-dialog set and backed by the bundled,
  read-only MaintIE corpus.

The legacy JSONL files remain available for dataset audit and full-set
experiments. The folder scenarios are the executable, static-JSON pilot.

## Dataset audit result

Run the reproducible audit:

```bash
uv run python scripts/build_multi_turn_dataset.py
```

The candidate pool contains 66 conversations and 215 user turns. All 66 have a
real cross-turn dependency and no exact duplicates were found. The execution
and truth gates reduce the formal evaluation set to 50:

- `data/wtb50.jsonl`: 50 executable Mentor scenarios and 152 turns, with
  objective truth for score-bearing turns and accepted MaintIE tool paths;
  28 conversational chat/clarify turns intentionally have no objective answer
  score and are represented as `ground_truth: null`. This is the main set.
- `data/wtb50_single_turn.jsonl`: 50 paired controls with all information and
  subgoals presented in one prompt, used to compute multi-turn degradation.
- `data/assetops16.jsonl`: 16 valid multi-turn dialogs, 63 turns; retained as a
  development set, but excluded from formal scores because the current
  checkout lacks scenario-specific manifests/data and curated per-turn truth.
- `data/audit.csv` and `data/audit_summary.json`: the full audit trail.

The WTB set runs against the bundled read-only MaintIE MCP server over the 1,076
record manually corrected release. It does not use CouchDB and cannot mutate
the corpus.

## Run the two-scenario static-JSON pilot

The checked benchmark setting is:

| Setting | Value |
| --- | --- |
| Agent | Stirrup 0.2.0 through `StirrupAgentRunner` |
| Model | `tokenrouter/z-ai/glm-5.3-free` |
| TokenRouter endpoint | `https://api.tokenrouter.com/v1` |
| Sampling temperature | `0` |
| Reasoning effort | omitted; provider default |
| Code execution | disabled |
| Agent-step budget | 12 per real user turn |
| Conversation state | one persistent Stirrup and MCP session |
| Final scorer | `static_json`, strict structured match |

As of 2026-09-05, TokenRouter's model page lists `z-ai/glm-5.3-free` with
zero input and output price and the OpenAI-compatible chat-completions API:
<https://www.tokenrouter.com/models/z-ai/glm-5.3-free/>.

Set credentials locally (never commit them):

```bash
cp .env.public .env
# Set TOKENROUTER_API_KEY in .env. Keep the default TOKENROUTER_BASE_URL.
```

`A16-06` needs CouchDB because its state comes from `manifest.json`:

```bash
docker compose -f src/couchdb/docker-compose.yaml up -d
```

Review the exact run without model or database calls:

```bash
DRY_RUN=1 ./benchmarks/run_multi_turn.sh
```

Run only the two pilot scenarios and evaluate their final answers:

```bash
ENV_FILE=.env ./benchmarks/run_multi_turn.sh
```

The full static-JSON report is written under
`benchmarks/multi_turn/results/two_scenario_pilot/static-json-report/`. The
shareable report is `poor-performance.json`; it contains only scenarios that
fail strict static-JSON matching. If both pass, its `poor_scenarios` array is
empty.

## Legacy JSONL run

Validate configuration without a model call:

```bash
uv run stirrup-multi-turn \
  --scenarios benchmarks/multi_turn/data/wtb50.jsonl \
  --scenario-ids WTB01 \
  --trajectory-dir /tmp/assetopsbench-mt \
  --dry-run
```

Run one PoC and score it:

```bash
uv run stirrup-multi-turn \
  --env-file .env \
  --scenarios benchmarks/multi_turn/data/wtb50.jsonl \
  --scenario-ids WTB01 \
  --trajectory-dir benchmarks/multi_turn/results/trajectories \
  --model-id litellm_proxy/your-model

uv run evaluate-multi-turn \
  --scenarios benchmarks/multi_turn/data/wtb50.jsonl \
  --trajectories benchmarks/multi_turn/results/trajectories \
  --output benchmarks/multi_turn/results/report.json
```

For an environment whose credentials use another prefix, such as
`DEEPSEEK_BASE_URL`/`DEEPSEEK_API_KEY`, add
`--router-env-prefix DEEPSEEK`. Values are mapped in process and are never
copied into the repository.

For the JSONL path, run and evaluate with the legacy multi-turn evaluator:

```bash
uv run evaluate-multi-turn \
  --scenarios benchmarks/multi_turn/data/wtb50.jsonl \
  --trajectories benchmarks/multi_turn/results/trajectories \
  --output benchmarks/multi_turn/results/report.json
```

Run the paired control file into a separate output directory, evaluate it, and
then compare the two reports:

```bash
uv run compare-multi-turn \
  --multi-turn-report benchmarks/multi_turn/results/report.json \
  --single-turn-report benchmarks/multi_turn/control-results/report.json \
  --output benchmarks/multi_turn/degradation.json
```

## Evaluation

The report keeps outcome and path quality separate:

- turn-level: answer correctness, optimal tool path, no-tool decision, and the
  observed tool groups;
- conversation-level: context retention, dependency-type capability scores,
  error-propagation resilience, and overall task success;
- benchmark-level: Accomplish Progress Rate (APR), Optimal Path Rate (OPR), and
  overall task-success rate.

A correct answer reached through redundant calls counts as task success but
loses OPR. This prevents an efficiency failure from being mislabeled as a
context-understanding failure. Turns with `ground_truth: null` are reported as
unscored rather than automatically correct; their tool/no-tool decision remains
independently measurable.

## Recorded PoC

`poc/` contains the WTB01 trajectory and deterministic report from a real
Stirrup 0.2.0 run with `deepseek-v4-flash`. It completed all four user turns and
returned every expected result. APR and context retention were 1.0. OPR was
0.25 because the agent used redundant tools on turns 2 and 3 and reused an
over-fetched ranking on turn 4 instead of following the preferred minimal path.
