# Profiling & Instrumentation — Multi-Turn AssetOps

This document describes every metric collected during evaluation runs, where each metric comes from, and how to interpret it in the WandB and LangSmith dashboards.

---

## Branches covered

| Branch | Agent architecture |
|---|---|
| `base_multi_turn_advanced_profiling` | Plan-Execute (LLM plans steps → MCP tool calls sequentially) |
| `supervisor-specialist` | LangGraph supervisor routes turns to specialist agents |
| `supervisor-specialist-advanced` | LangGraph supervisor + parallel MCP tool calling within specialists |

All three branches share `eval/run_eval.py` and the same MCP server instrumentation. The only differences are in the agent runtime files under `src/agent/`.

---

## Instrumentation layers

### Layer 1 — LLM call metrics (`LITELLM_METRICS_FILE`)

**Source:** `src/llm/litellm.py` — `_MetricsFileLogger` (a `CustomLogger` subclass registered as a LiteLLM callback, active on all three branches).

One JSON record is appended per LLM completion:

```json
{"timestamp": "2026-05-04T12:00:00Z", "model": "watsonx/...",
 "prompt_tokens": 1234, "completion_tokens": 56,
 "total_tokens": 1290, "latency_s": 1.87}
```

The eval harness reads all records for a dialog and aggregates them.

---

### Layer 2 — MCP tool call metrics (`TOOL_METRICS_FILE`)

**Source:**
- `src/agent/plan_execute/executor.py` → `_write_tool_metric()` wrapping `_call_tool()`
- `src/agent/supervisor_specialist/runtime/mcp_tools.py` → same pattern wrapping `_call_tool_on_server()`

One JSON record per tool invocation:

```json
{"server": "iot", "tool": "history", "latency_s": 0.42, "status": "ok"}
```

---

### Layer 3 — CouchDB query metrics (`COUCHDB_METRICS_FILE`)

**Source:** `_write_couchdb_metric()` helper defined in each MCP server, wrapping every `db.find()` call:

- `src/servers/iot/main.py`
- `src/servers/wo/data.py`
- `src/servers/vibration/couchdb_client.py`

One JSON record per database query:

```json
{"server": "iot", "query": "history", "latency_s": 0.18,
 "status": "ok", "docs_returned": 1000}
```

---

## WandB metrics reference

All metrics are logged via `wandb.log()` in `eval/run_eval.py` after each dialog completes. The x-axis for all `dialog/*`, `latency/*`, `tokens/*`, `llm/*`, `tool/*`, `couchdb/*`, and `run/*` metrics is **`dialog/id`** (set via `wandb.define_metric`). The x-axis for `turn/*` metrics is **`turn/index`** (a globally unique counter across all dialogs in the run). The x-axis for `llm_call/*` metrics is **`llm_call/index`** (globally unique across all LLM calls in the run).

---

### `dialog/*` — per-dialog identity and success

| Metric | Type | Description |
|---|---|---|
| `dialog/id` | int | Dialog number (1–16). Also the x-axis step for all dialog-level metrics. |
| `dialog/category` | string | Scenario category (e.g. `"single_asset"`, `"cross_asset"`). |
| `dialog/status` | string | Outcome: `"completed"`, `"crashed"`, or `"timed_out"`. |
| `dialog/turns_ok` | int | Number of turns that completed without error. |
| `dialog/turns_total` | int | Total number of turns attempted. |
| `dialog/turn_success_rate` | float | `turns_ok / turns_total`. |

---

### `latency/*` — wall-clock time and 3-way breakdown

These are the primary comparison metrics across branches.

| Metric | Description |
|---|---|
| `latency/wall_s` | Total wall-clock duration of the dialog (seconds). |
| `latency/wall_per_turn_s` | `wall_s / turns_ok` — average time per successful turn. |
| `latency/llm_s` | Total time spent blocked on LLM API calls (summed across all calls in the dialog). |
| `latency/llm_fraction` | `llm_s / wall_s` — share of wall time spent in the LLM. |
| `latency/tool_s` | Total time spent executing MCP tool calls (summed across all tool invocations). |
| `latency/tool_fraction` | `tool_s / wall_s` — share of wall time spent in tool calls. |
| `latency/routing_s` | `max(wall_s − llm_s − tool_s, 0)` — residual time: orchestration, planning, serialisation, and LangGraph graph transitions. |
| `latency/routing_fraction` | `routing_s / wall_s` — share of wall time spent on orchestration. |

The three fractions (`llm_fraction + tool_fraction + routing_fraction`) sum to approximately 1. Comparing these across branches reveals where each architecture spends its time — for example, whether the parallel tool calling in `supervisor-specialist-advanced` reduces `latency/tool_fraction` relative to the sequential branches.

> **Note on `routing_s`:** Despite the name, this metric does not exclusively capture supervisor routing time — it is the same residual formula (`wall - llm - tool`) on all three branches and captures different things per architecture:
> - **Plan-execute:** prompt assembly, JSON parsing, step scheduling, asyncio overhead.
> - **SS / SSA:** LangGraph graph transitions, supervisor decision parsing, artifact store I/O, conversation memory serialisation, asyncio overhead — plus the same prompt assembly and JSON parsing as plan-execute.
>
> The supervisor routing decision itself (the LLM call where the supervisor decides which specialist to invoke) is counted inside `latency/llm_s`, not `routing_s`, since it is an LLM API call like any other. `routing_s` is better understood as **unaccounted overhead**.

---

### `tokens/*` — token usage (per dialog)

Aggregated from `LITELLM_METRICS_FILE` across all LLM calls in the dialog.

| Metric | Description |
|---|---|
| `tokens/prompt` | Total prompt tokens consumed. |
| `tokens/completion` | Total completion tokens generated. |
| `tokens/total` | `prompt + completion`. |
| `tokens/per_turn` | `total_tokens / turns_ok` — token efficiency per successful turn. |

---

### `llm/*` — LLM call summary (per dialog)

| Metric | Description |
|---|---|
| `llm/calls` | Number of LLM API calls made during the dialog. |
| `llm/calls_per_turn` | `calls / turns_ok`. |
| `llm/latency_s` | Same value as `latency/llm_s` (duplicated here for grouping convenience). |
| `llm/tokens_per_second` | `completion_tokens / llm_latency_s` — throughput of the LLM backend. |
| `llm/fraction_of_wall` | Same as `latency/llm_fraction`. |

---

### `llm_call/*` — per-call LLM detail (one point per LLM call)

Each individual LLM call is logged separately on the `llm_call/index` x-axis, allowing inspection of how token counts and latency vary call-by-call within and across dialogs.

| Metric | Description |
|---|---|
| `llm_call/index` | Globally unique call counter across the whole run. |
| `llm_call/dialog_id` | Which dialog this call belongs to. |
| `llm_call/model` | Model string used (e.g. `watsonx/meta-llama/...`). |
| `llm_call/prompt_tokens` | Prompt tokens for this call. |
| `llm_call/completion_tokens` | Completion tokens for this call. |
| `llm_call/total_tokens` | Total tokens for this call. |
| `llm_call/latency_s` | Latency of this single call (seconds). |
| `llm_call/tokens_per_second` | `completion_tokens / latency_s` for this call. |

---

### `tool/*` — MCP tool call breakdown (per dialog)

Aggregated from `TOOL_METRICS_FILE`. The `<server>` placeholder is the MCP server name (`iot`, `wo`, `fmsr`, `tsfm`, `utilities`).

| Metric | Description |
|---|---|
| `tool/total_calls` | Total MCP tool invocations across all servers. |
| `tool/total_latency_s` | Sum of all tool call latencies. |
| `tool/<server>/calls` | Calls to a specific MCP server. |
| `tool/<server>/latency_s` | Total latency for calls to that server. |
| `tool/<server>/errors` | Number of failed calls to that server. |

---

### `couchdb/*` — database query breakdown (per dialog)

Aggregated from `COUCHDB_METRICS_FILE`. The `<server>` placeholder is the MCP server that issued the query (`iot`, `wo`, `vibration`).

| Metric | Description |
|---|---|
| `couchdb/total_queries` | Total CouchDB `find()` calls across all servers. |
| `couchdb/total_latency_s` | Sum of all query latencies. |
| `couchdb/<server>/queries` | Number of queries issued by that MCP server. |
| `couchdb/<server>/latency_s` | Total time spent in CouchDB for that server. |
| `couchdb/<server>/docs_returned` | Total documents fetched by that server. |
| `couchdb/<server>/errors` | Number of failed queries from that server. |

---

### `turn/*` — per-turn metrics (one point per turn, across all dialogs)

Each turn in every dialog is logged on the global `turn/index` x-axis, making it possible to see how turn duration and success rate evolve over the course of a multi-turn session.

| Metric | Description |
|---|---|
| `turn/index` | Globally unique turn counter (`turn_offset + turn_index_in_dialog`). |
| `turn/dialog_id` | Which dialog this turn belongs to. |
| `turn/turn_in_dialog` | Position of this turn within its dialog (1-based). |
| `turn/duration_s` | Wall time for this turn (seconds). |
| `turn/status_ok` | 1 if the turn completed successfully, 0 otherwise. |
| `turn/response_chars` | Character length of the agent's response. |
| `turn/cumulative_success_rate` | Fraction of turns so far in this dialog that succeeded. |
| `turn/status` | Raw status string (`"ok"`, `"error"`, `"timed_out"`). |

#### `per_dialog/dialog_XX/*` (per-dialog turn view)

In addition to the cross-dialog `turn/*` series, each turn is also logged under a dialog-specific key so you can plot turn-level metrics for a single dialog in isolation:

| Metric | Description |
|---|---|
| `per_dialog/dialog_XX/duration_s` | Turn duration within dialog XX. |
| `per_dialog/dialog_XX/status_ok` | 1/0 success for that turn. |
| `per_dialog/dialog_XX/response_chars` | Response length for that turn. |
| `per_dialog/dialog_XX/cumulative_success_rate` | Running success rate within dialog XX. |

---

### `run/*` — end-of-run summary (one log call per run)

Logged once after all dialogs complete.

| Metric | Description |
|---|---|
| `run/dialogs_completed` | Dialogs that finished normally. |
| `run/dialogs_crashed` | Dialogs that raised an unhandled exception. |
| `run/dialogs_timed_out` | Dialogs that exceeded `PER_DIALOG_TIMEOUT`. |
| `run/turns_ok` | Total successful turns across all dialogs. |
| `run/turns_total` | Total turns attempted across all dialogs. |
| `run/total_tokens` | Total tokens consumed across all dialogs. |
| `run/total_llm_calls` | Total LLM API calls across all dialogs. |
| `run/wall_time_s` | Total wall-clock time for the entire eval run. |

---

## LangSmith tracing

LangSmith tracing is enabled when `LANGCHAIN_API_KEY` is set in `.env.profiling`. Two trace sources exist depending on the branch.

### LiteLLM → LangSmith (all three branches)

In `src/llm/litellm.py`, `_register_callbacks()` adds `"langsmith"` to `litellm.success_callback` if `LANGCHAIN_API_KEY` is present. This sends **one trace per LLM API call** to LangSmith, including:

- Model name
- Prompt and completion token counts
- Latency
- The full prompt/response payload (visible in the LangSmith trace detail view)

This is the only LangSmith trace source on `base_multi_turn_advanced_profiling`, which does not use LangGraph.

### LangGraph → LangSmith (supervisor-specialist and supervisor-specialist-advanced only)

Both supervisor branches use LangGraph (`StateGraph` in `src/agent/supervisor_specialist/graph.py`). LangGraph automatically sends graph-level traces to LangSmith whenever `LANGCHAIN_API_KEY` is set in the environment — no additional configuration is required.

These graph-level traces capture:
- Each **node invocation** (supervisor decision, specialist execution) as a named span
- The **routing decision** made by the supervisor at each turn
- **State transitions** and the data flowing between nodes
- The full **graph run** as a parent trace, with each node as a child span

This means each dialog turn produces a richer trace tree in LangSmith on the supervisor branches: a root `langgraph` span containing supervisor and specialist node spans, each of which in turn contains the LiteLLM span for the LLM call made inside that node.

On `supervisor-specialist-advanced`, parallel tool calls within a specialist node appear as concurrent child spans under that node's trace entry, making it easy to see which tools ran in parallel and their individual durations.

> **Note:** LangGraph traces use the thread_id from `{"configurable": {"thread_id": ...}}` to group multi-turn dialog history. Each dialog session gets a unique thread ID, so turns within a dialog are linked in LangSmith.

---

## Credential isolation

Profiling credentials (`WANDB_API_KEY`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `WANDB_PROJECT`) are loaded from `.env.profiling`, not `.env`. The eval harness sets `WANDB_DISABLED=true` in the child process environment before launching the agent subprocess, so these keys are never forwarded into MCP server processes. This was the root cause of WandB banner output corrupting the MCP stdio transport before the fix.

---

## Files changed

| File | Change |
|---|---|
| `eval/run_eval.py` | Full profiling harness: WandB init, all `wandb.log()` calls, JSONL readers, child env setup |
| `src/agent/plan_execute/executor.py` | `env=dict(os.environ)` in `_make_stdio_params()`; `_write_tool_metric()` + timing in `_call_tool()` |
| `src/agent/supervisor_specialist/runtime/mcp_tools.py` | Same fixes for both supervisor branches |
| `src/llm/litellm.py` | `_MetricsFileLogger` custom callback + LangSmith `success_callback` registration |
| `src/servers/iot/main.py` | `_write_couchdb_metric()` wrapping all `db.find()` calls |
| `src/servers/wo/data.py` | `_write_couchdb_metric()` wrapping all `db.find()` calls |
| `src/servers/vibration/couchdb_client.py` | `_write_couchdb_metric()` wrapping all `db.find()` calls |
| `.gitignore` | Added `eval/results/` and `tuned_models/` |

---

## Root cause fixed: MCP subprocess environment inheritance

The MCP library's `stdio_client` calls `get_default_environment()` when no `env` argument is provided. This only forwards six shell variables (`HOME`, `PATH`, `SHELL`, `TMPDIR`, `USER`, `LOGNAME`) and silently drops all custom variables.

**Consequence before the fix:**
- `COUCHDB_METRICS_FILE` never reached MCP servers → CouchDB metrics were missing entirely.
- `WANDB_DISABLED` was not forwarded → MCP servers attempted to initialise WandB, printing banners that corrupted the stdio transport and broke tool calls.

**Fix** — `env=dict(os.environ)` added to every `StdioServerParameters` construction:

- `src/agent/plan_execute/executor.py` (`base_multi_turn_advanced_profiling`)
- `src/agent/supervisor_specialist/runtime/mcp_tools.py` (`supervisor-specialist`, `supervisor-specialist-advanced`)
