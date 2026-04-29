# AssetOpsBench MCP Environment

This directory contains the MCP servers and infrastructure for the AssetOpsBench project.

## Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [MCP Servers](#mcp-servers)
  - [iot](#iot)
  - [utilities](#utilities)
  - [fmsr](#fmsr)
  - [tsfm](#tsfm)
  - [wo](#wo)
  - [vibration](#vibration)
- [Plan-Execute Runner](#plan-execute-runner)
  - [How it works](#how-it-works)
  - [CLI](#cli)
  - [End-to-end examples](#end-to-end-examples)
  - [Python API](#python-api)
  - [Bring your own LLM](#bring-your-own-llm)
  - [Add more MCP servers](#add-more-mcp-servers)
- [Supervisor-Specialist Runner](#supervisor-specialist-runner)
  - [How it works](#how-it-works-1)
  - [CLI](#cli-1)
  - [Multi-turn dialog](#multi-turn-dialog)
  - [Parallel Specialist tool calls](#parallel-specialist-tool-calls)
  - [Behavior logs](#behavior-logs)
  - [Python API](#python-api-1)
- [Connect to Claude Desktop](#connect-to-claude-desktop)
- [Running Tests](#running-tests)
- [Architecture](#architecture)

---

## Prerequisites

- **Python 3.12+** — required by `pyproject.toml`
- **[uv](https://docs.astral.sh/uv/)** — dependency and environment manager

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
  # or: brew install uv
  ```

- **Docker** — for running CouchDB (IoT data store)

## Quick Start

### 1. Install dependencies

Run from the **repo root**:

```bash
uv sync
```

`uv sync` creates a virtual environment at `.venv/`, installs all dependencies, and registers the CLI entry points (`plan-execute`, `*-mcp-server`). You can either prefix commands with `uv run` (no activation needed) or activate the venv once for your shell session:

```bash
source .venv/bin/activate   # macOS / Linux
```

### 2. Configure environment

Copy `.env.public` to `.env` and fill in the required values (see [Environment Variables](#environment-variables)):

```bash
cp .env.public .env
# Then edit .env and set WATSONX_APIKEY, WATSONX_PROJECT_ID
# CouchDB defaults work out of the box with the Docker setup
```

### 3. Start CouchDB

```bash
docker compose -f src/couchdb/docker-compose.yaml up -d
```

Verify CouchDB is running:

```bash
curl -X GET http://localhost:5984/
```

### 4. Run servers

> **Note:** MCP servers use stdio transport — they are spawned on-demand by clients (Claude Desktop, `plan-execute`) and exit when the client disconnects. They are not long-running daemons.

To start a server manually for testing:

```bash
uv run utilities-mcp-server
uv run iot-mcp-server
uv run fmsr-mcp-server
uv run tsfm-mcp-server
uv run wo-mcp-server
uv run vibration-mcp-server
```

---

## Environment Variables

**CouchDB** — `iot` and `wo` servers

| Variable           | Default                 | Description              |
| ------------------ | ----------------------- | ------------------------ |
| `COUCHDB_URL`      | `http://localhost:5984` | CouchDB connection URL   |
| `COUCHDB_USERNAME` | `admin`                 | CouchDB admin username   |
| `COUCHDB_PASSWORD` | `password`              | CouchDB admin password   |
| `IOT_DBNAME`         | `chiller`               | IoT sensor database name      |
| `WO_DBNAME`          | `workorder`             | Work order database name      |
| `VIBRATION_DBNAME`   | `vibration`             | Vibration sensor database name |

**WatsonX** — plan-execute and supervisor-specialist runners (when `--model-id` starts with `watsonx/`)

| Variable             | Default                             | Description                 |
| -------------------- | ----------------------------------- | --------------------------- |
| `WATSONX_APIKEY`     | _(required)_                        | IBM WatsonX API key         |
| `WATSONX_PROJECT_ID` | _(required)_                        | IBM WatsonX project ID      |
| `WATSONX_URL`        | `https://us-south.ml.cloud.ibm.com` | WatsonX endpoint (optional) |

**LiteLLM** — plan-execute and supervisor-specialist runners (when `--model-id` does not start with `watsonx/`, e.g. `litellm_proxy/…`)

| Variable           | Default      | Description                                                          |
| ------------------ | ------------ | -------------------------------------------------------------------- |
| `LITELLM_API_KEY`  | _(required)_ | LiteLLM proxy API key                                                |
| `LITELLM_BASE_URL` | _(required)_ | LiteLLM proxy base URL, e.g. `https://your-litellm-host.example.com` |

**Supervisor-Specialist** — optional runtime controls

| Variable                              | Default                                                                  | Description                                                                 |
| ------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `SS_MODEL_ID`                         | `watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8`              | Default model for `supervisor-specialist`                                   |
| `SS_MAX_STEPS`                        | `12`                                                                     | Maximum graph/specialist steps per turn                                     |
| `SUPERVISOR_SPECIALIST_PARALLELISM`   | `4`                                                                      | Maximum concurrent tool calls inside one Specialist parallel batch          |

---

## MCP Servers

### iot — IoT Sensor Data

**Path:** `src/servers/iot/main.py`
**Requires:** CouchDB (`COUCHDB_URL`, `COUCHDB_USERNAME`, `COUCHDB_PASSWORD`, `IOT_DBNAME`)

| Tool      | Arguments                                  | Description                                                             |
| --------- | ------------------------------------------ | ----------------------------------------------------------------------- |
| `sites`   | —                                          | List all available sites                                                |
| `assets`  | `site_name`                                | List all asset IDs for a site                                           |
| `sensors` | `site_name`, `asset_id`                    | List sensor names for an asset                                          |
| `history` | `site_name`, `asset_id`, `start`, `final?` | Fetch historical sensor readings for a time range (ISO 8601 timestamps) |

### utilities — Utilities

**Path:** `src/servers/utilities/main.py`
**Requires:** nothing (no external services)

| Tool                   | Arguments   | Description                                            |
| ---------------------- | ----------- | ------------------------------------------------------ |
| `json_reader`          | `file_name` | Read and parse a JSON file from disk                   |
| `current_date_time`    | —           | Return the current UTC date and time as JSON           |
| `current_time_english` | —           | Return the current UTC time as a human-readable string |

### fmsr — Failure Mode and Sensor Relations

**Path:** `src/servers/fmsr/main.py`
**Requires:** `WATSONX_APIKEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL` for unknown assets; curated lists for `chiller` and `ahu` work without credentials.
**Failure-mode data:** `src/servers/fmsr/failure_modes.yaml` (edit to add/change asset entries)

| Tool                              | Arguments                                | Description                                                                                                                                             |
| --------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_failure_modes`               | `asset_name`                             | Return known failure modes for an asset. Uses a curated YAML list for chillers and AHUs; falls back to the LLM for other types.                         |
| `get_failure_mode_sensor_mapping` | `asset_name`, `failure_modes`, `sensors` | For each (failure mode, sensor) pair, determine relevancy via LLM. Returns bidirectional `fm→sensors` and `sensor→fms` maps plus full per-pair details. |

### wo — Work Order

**Path:** `src/servers/wo/main.py`
**Requires:** CouchDB (`COUCHDB_URL`, `COUCHDB_USERNAME`, `COUCHDB_PASSWORD`, `WO_DBNAME`)
**Data init:** Handled automatically by `docker compose -f src/couchdb/docker-compose.yaml up` (runs `src/couchdb/init_wo.py` inside the CouchDB container on every start — database is dropped and reloaded each time)

| Tool                          | Arguments                                             | Description                                                                              |
| ----------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `get_work_orders`             | `equipment_id`, `start_date?`, `end_date?`            | Retrieve all work orders for an equipment within an optional date range                  |
| `get_preventive_work_orders`  | `equipment_id`, `start_date?`, `end_date?`            | Retrieve only preventive (PM) work orders                                                |
| `get_corrective_work_orders`  | `equipment_id`, `start_date?`, `end_date?`            | Retrieve only corrective (CM) work orders                                                |
| `get_events`                  | `equipment_id`, `start_date?`, `end_date?`            | Retrieve all events (work orders, alerts, anomalies)                                     |
| `get_failure_codes`           | —                                                     | List all failure codes with categories and descriptions                                  |
| `get_work_order_distribution` | `equipment_id`, `start_date?`, `end_date?`            | Count work orders per (primary, secondary) failure code pair, sorted by frequency        |
| `predict_next_work_order`     | `equipment_id`, `start_date?`, `end_date?`            | Predict next work order type via Markov transition matrix built from historical sequence |
| `analyze_alert_to_failure`    | `equipment_id`, `rule_id`, `start_date?`, `end_date?` | Probability that an alert rule leads to a work order; average hours to maintenance       |

### tsfm — Time Series Foundation Model

**Path:** `src/servers/tsfm/main.py`
**Requires:** `tsfm_public` (IBM Granite TSFM), `transformers`, `torch` for ML tools — imported lazily; static tools work without them.
**Model checkpoints:** resolved relative to `PATH_TO_MODELS_DIR` (default: `src/servers/tsfm/artifacts/output/tuned_models`)

| Tool                   | Arguments                                                                                                                   | Description                                                                                      |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `get_ai_tasks`         | —                                                                                                                           | List supported AI task types for time-series analysis                                            |
| `get_tsfm_models`      | —                                                                                                                           | List available pre-trained TinyTimeMixer (TTM) model checkpoints                                 |
| `run_tsfm_forecasting` | `dataset_path`, `timestamp_column`, `target_columns`, `model_checkpoint?`, `forecast_horizon?`, `frequency_sampling?`, ...  | Zero-shot TTM inference; returns path to a JSON predictions file                                 |
| `run_tsfm_finetuning`  | `dataset_path`, `timestamp_column`, `target_columns`, `model_checkpoint?`, `save_model_dir?`, `n_finetune?`, `n_test?`, ... | Few-shot fine-tune a TTM model; returns saved checkpoint path and metrics file                   |
| `run_tsad`             | `dataset_path`, `tsfm_output_json`, `timestamp_column`, `target_columns`, `task?`, `false_alarm?`, `ad_model_type?`, ...    | Conformal anomaly detection on top of a forecasting output JSON; returns CSV with anomaly labels |
| `run_integrated_tsad`  | `dataset_path`, `timestamp_column`, `target_columns`, `model_checkpoint?`, `false_alarm?`, `n_calibration?`, ...            | End-to-end forecasting + anomaly detection in one call; returns combined CSV                     |

### vibration — Vibration Diagnostics

**Path:** `src/servers/vibration/main.py`
**Requires:** CouchDB (`COUCHDB_URL`, `VIBRATION_DBNAME` (default `vibration`), `COUCHDB_USERNAME`, `COUCHDB_PASSWORD`); `numpy`, `scipy`
**DSP core:** `src/servers/vibration/dsp/` — adapted from [vibration-analysis-mcp](https://github.com/LGDiMaggio/claude-stwinbox-diagnostics/tree/main/mcp-servers/vibration-analysis-mcp) (Apache-2.0)

| Tool | Arguments | Description |
|---|---|---|
| `get_vibration_data` | `site_name`, `asset_id`, `sensor_name`, `start`, `final?` | Fetch vibration time-series from CouchDB and load into the analysis store. Returns a `data_id`. |
| `list_vibration_sensors` | `site_name`, `asset_id` | List available sensor fields for an asset. |
| `compute_fft_spectrum` | `data_id`, `window?`, `top_n?` | Compute FFT amplitude spectrum (top-N peaks + statistics). |
| `compute_envelope_spectrum` | `data_id`, `band_low_hz?`, `band_high_hz?`, `top_n?` | Compute envelope spectrum for bearing fault detection (Hilbert transform). |
| `assess_vibration_severity` | `rms_velocity_mm_s`, `machine_group?` | Classify vibration severity per ISO 10816 (Zones A–D). |
| `calculate_bearing_frequencies` | `rpm`, `n_balls`, `ball_diameter_mm`, `pitch_diameter_mm`, `contact_angle_deg?`, `bearing_name?` | Compute bearing characteristic frequencies (BPFO, BPFI, BSF, FTF). |
| `list_known_bearings` | — | List all bearings in the built-in database. |
| `diagnose_vibration` | `data_id`, `rpm?`, `bearing_designation?`, `bearing_*?`, `bpfo_hz?`, `bpfi_hz?`, `bsf_hz?`, `ftf_hz?`, `machine_group?`, `machine_description?` | Full automated diagnosis: FFT + shaft features + bearing envelope + ISO 10816 + fault classification + markdown report. |

---

## Plan-Execute Runner

`src/agent/` is a custom MCP client that implements a **plan-and-execute** workflow over the MCP servers. It replaces AgentHive's bespoke orchestration with the standard MCP protocol.

### How it works

```
PlanExecuteRunner.run(question)
  │
  ├─ 1. Discover   query each MCP server for its available tools
  │
  ├─ 2. Plan       LLM decomposes the question into ordered steps,
  │                each assigned to an MCP server
  │
  ├─ 3. Execute    for each step (in dependency order):
  │                  • LLM selects the right tool + generates arguments
  │                  • tool is called via MCP stdio protocol
  │                  • result is stored and passed as context to later steps
  │
  └─ 4. Summarise  LLM synthesises step results into a final answer
```

### CLI

After `uv sync`, the `plan-execute` command is available:

```bash
uv run plan-execute "What assets are available at site MAIN?"
```

> **Note:** `plan-execute` spawns MCP servers on-demand for each query — you do **not** need to start them manually first. Servers are launched as subprocesses, used, then exit automatically.

Flags:

| Flag                  | Description                                                                                                      |
| --------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `--model-id MODEL_ID` | litellm model string with provider prefix (default: `watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8`) |
| `--server NAME=SPEC`  | Override MCP servers with `NAME=SPEC` pairs (repeatable); SPEC is an entry-point name or path                    |
| `--show-plan`         | Print the generated plan before execution                                                                        |
| `--show-history`      | Print each step result after execution                                                                           |
| `--json`              | Output answer + plan + history as JSON                                                                           |

The provider is encoded in the `--model-id` prefix:

| Prefix           | Provider      | Required env vars                                                |
| ---------------- | ------------- | ---------------------------------------------------------------- |
| `watsonx/`       | IBM WatsonX   | `WATSONX_APIKEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL` (optional) |
| `litellm_proxy/` | LiteLLM proxy | `LITELLM_API_KEY`, `LITELLM_BASE_URL`                            |

Examples:

```bash
# WatsonX — default model
uv run plan-execute "What assets are at site MAIN?"

# WatsonX — different model, inspect the plan
uv run plan-execute --model-id watsonx/ibm/granite-3-3-8b-instruct --show-plan "List sensors for asset CH-1"

# LiteLLM proxy
uv run plan-execute --model-id litellm_proxy/GCP/claude-4-sonnet "What are the failure modes for a chiller?"

# Machine-readable output
uv run plan-execute --show-history --json "How many observations exist for CH-1?" | jq .answer
```

### End-to-end examples

All six servers (iot, utilities, fmsr, tsfm, wo, vibration) are registered by default.

#### Work order queries (requires CouchDB + populated `workorder` db)

Equipment IDs in the sample dataset: `CWC04014` (524 WOs), `CWC04013` (431 WOs), `CWC04009` (alert events).

```bash
# Work order count and most common failure code
uv run plan-execute "How many work orders does equipment CWC04014 have, and what is the most common failure code?"

# Preventive vs corrective split
uv run plan-execute "For equipment CWC04013, how many preventive vs corrective work orders were completed?"

# Alert-to-failure probability
uv run plan-execute "What is the probability that alert rule RUL0018 on equipment CWC04009 leads to a work order, and how long does it typically take?"

# Work order distribution + next prediction (multi-step)
uv run plan-execute --show-plan --show-history \
  "For equipment CWC04014, show the work order distribution and predict the next maintenance type"
```

#### Multi-server parallel query

Run a question that exercises three servers with independent parallel steps:

```bash
uv run plan-execute --show-plan --show-history \
  "What is the current date and time? Also list assets at site MAIN. Also get sensor list and failure mode list for any of the chiller at site MAIN."
```

Expected plan (3 parallel steps, no dependencies):

```
[1] utilities  : current_date_time()
[2] iot        : assets(site_name="MAIN")
[3] fmsr       : get_failure_modes(asset_name="chiller")
```

Expected execution output (trimmed):

```
[OK] Step 1 (utilities)
     {"currentDateTime": "2026-02-20T17:28:39Z", "currentDateTimeDescription": "Today's date is 2026-02-20 and time is 17:28:39."}

[OK] Step 2 (iot)
     {"site_name": "MAIN", "total_assets": 1, "assets": ["Chiller 6"], "message": "found 1 assets for site_name MAIN."}

[OK] Step 3 (fmsr)
     {"asset_name": "chiller", "failure_modes": ["Compressor Overheating: Failed due to Normal wear, overheating", ...]}
```

> **Note:** Curated assets (`chiller`, `ahu`) are served from `failure_modes.yaml` without any LLM call.

### Python API

```python
import asyncio
from agent import PlanExecuteRunner
from llm import LiteLLMBackend

runner = PlanExecuteRunner(llm=LiteLLMBackend("watsonx/meta-llama/llama-3-3-70b-instruct"))
result = asyncio.run(runner.run("What assets are available at site MAIN?"))
print(result.answer)
```

`OrchestratorResult` fields:

| Field     | Type               | Description                       |
| --------- | ------------------ | --------------------------------- |
| `answer`  | `str`              | Final synthesised answer          |
| `plan`    | `Plan`             | The generated plan with its steps |
| `history` | `list[StepResult]` | Per-step execution results        |

### Bring your own LLM

Implement `LLMBackend` to use any model:

```python
from llm import LLMBackend

class MyLLM(LLMBackend):
    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        ...  # call your model here

runner = PlanExecuteRunner(llm=MyLLM())
```

### Add more MCP servers

Pass `server_paths` to register additional servers. Keys must match the server names the planner assigns steps to:

```python
from agent import PlanExecuteRunner

runner = PlanExecuteRunner(
    llm=my_llm,
    server_paths={
        "iot":       "iot-mcp-server",
        "utilities": "utilities-mcp-server",
        "fmsr":      "fmsr-mcp-server",
        "tsfm":      "tsfm-mcp-server",
        "wo":        "wo-mcp-server",
        "vibration": "vibration-mcp-server",
    },
)
```

> **Note:** passing `server_paths` replaces the defaults entirely. Include all servers you need.

---

## Supervisor-Specialist Runner

`src/agent/supervisor_specialist/` is a LangGraph-based multi-agent runner for industrial asset operations. It is designed for closed-loop diagnostic workflows where one Supervisor routes work to domain Specialists and carries compact state across steps and, optionally, dialog turns.

### How it works

```
SupervisorSpecialistRunner.run(question) or run_turn(question)
  │
  ├─ 1. prepare_turn
  │      Parse the latest user message, merge active site/assets/time window,
  │      reset per-turn transient fields, and retain prior artifacts in memory.
  │
  ├─ 2. supervisor
  │      Inspect current case state, structured memory, artifact summaries,
  │      and the latest user request; choose the next Specialist or final answer.
  │
  ├─ 3. specialist
  │      Execute a compact ReAct loop over allowed MCP tools, save artifacts,
  │      and return compact tool-call summaries.
  │
  ├─ 4. supervisor loop
  │      Re-plan after each Specialist result until enough evidence exists.
  │
  └─ 5. respond_to_user
         Generate the final answer, update rolling conversation memory,
         and append JSONL behavior logs.
```

The current Specialists are:

| Specialist | Main responsibility |
| --- | --- |
| `data_collection_specialist` | Site/asset/sensor discovery and historical IoT CSV generation |
| `time_series_analysis_specialist` | Statistics, forecasting, anomaly detection, and TSFM outputs |
| `failure_reasoning_specialist` | Failure-mode reasoning using FMSR and prior artifacts |
| `maintenance_planning_specialist` | Work-order review and recommended maintenance actions |

The graph state includes `case_state`, `current_user_message`, `conversation_memory`, current task, recent artifacts, per-turn artifact IDs, per-turn tool summaries, and final response. Large CSV/JSON data is passed by artifact path; prompts receive summaries and references rather than full datasets.

### CLI

After `uv sync`, the `supervisor-specialist` command is available:

```bash
uv run supervisor-specialist --reference-date 2020-06-20 \
  "The temperature of our chiller at Site MAIN seems unusually high lately. Can you look into it?"
```

Flags:

| Flag | Description |
| --- | --- |
| `--model-id MODEL_ID` | LiteLLM model string with provider prefix. Defaults to `SS_MODEL_ID` or the built-in WatsonX model. |
| `--max-steps N` | Maximum graph/specialist steps per turn. Defaults to `SS_MAX_STEPS` or `12`. |
| `--reference-date YYYY-MM-DD` | Anchor date for relative time windows such as `past month`. |
| `--multi-turn` | Start a REPL and retain in-memory conversation state across turns. |
| `--parallel` | Enable parallel Specialist tool batches and deterministic multi-asset coverage guards. |
| `--no-stream` | Suppress streaming event output on stderr. |
| `--no-log` | Suppress persistent behavior logs under `logs/supervisor_specialist/`. |

Examples:

```bash
# Single-turn diagnosis
uv run supervisor-specialist --reference-date 2020-06-20 \
  "Investigate high temperature at Site MAIN over the past month."

# Multi-asset comparison with parallel Specialist tool calls
uv run supervisor-specialist --parallel --reference-date 2020-06-20 \
  "Compare Chiller 3, Chiller 4, Chiller 6, and Chiller 9 over the past month."

# Use another model
uv run supervisor-specialist --model-id watsonx/ibm/granite-3-3-8b-instruct \
  "List assets at site MAIN and summarize what data is available."
```

### Multi-turn dialog

`--multi-turn` starts a CLI REPL. The runner uses one LangGraph `thread_id` and an in-memory `MemorySaver` checkpoint for the whole REPL session. It does not persist sessions across processes.

```bash
uv run supervisor-specialist --multi-turn --reference-date 2020-06-20
> Which chillers at Site MAIN have temperature anomalies over the past month?
> What could be causing this?
> Use the same period and recommend maintenance actions.
> exit
```

Conversation memory tracks:

| Memory field | Purpose |
| --- | --- |
| active site/assets/time window | Lets follow-up questions reuse prior context such as `same period` or `this chiller`. |
| focus metrics | Carries metrics such as temperature, efficiency, power, load, tonnage, work orders, and alerts. |
| rolling summary | Compact summary of recent turns for future prompts. |
| recent turns | User message, assistant answer, artifact IDs, compact tool-call summaries, root cause, and actions. |
| active artifact IDs | References to datasets, analysis results, reasoning results, and plans already generated. |

Time-window parsing currently supports:

| User phrase | Behavior |
| --- | --- |
| `same period` | Reuses the previous active time window. |
| `past month`, `last month`, `recently` | Uses 30 days ending at `--reference-date` or current UTC date. |
| `last two months`, `past two months`, `last 2 months` | Uses 60 days ending at `--reference-date` or current UTC date. |
| `June 2020` | Uses `2020-06-01T00:00:00` to `2020-07-01T00:00:00`. |

### Parallel Specialist tool calls

Parallel execution is opt-in:

```bash
uv run supervisor-specialist --parallel --reference-date 2020-06-20 \
  "Run anomaly analysis for Chiller 3, Chiller 4, Chiller 6, and Chiller 9."
```

Without `--parallel`, Specialists are constrained to one tool call per ReAct step. If an LLM returns a batch unexpectedly, only the first call is executed.

With `--parallel`, a Specialist may return:

```json
{
  "tool_calls": [
    {"tool_name": "tsfm.run_integrated_tsad", "args": {"dataset_path": "/path/chiller_3.csv"}},
    {"tool_name": "tsfm.run_integrated_tsad", "args": {"dataset_path": "/path/chiller_4.csv"}}
  ]
}
```

The MCP client executes independent calls concurrently with `asyncio` and preserves result order. The concurrency limit defaults to `4` and can be changed with:

```bash
SUPERVISOR_SPECIALIST_PARALLELISM=2 uv run supervisor-specialist --parallel "..."
```

Parallel mode also enables deterministic multi-asset coverage guards. If asset discovery finds multiple chillers and later artifacts expose multiple CSV paths, the data-collection and time-series Specialists ensure each known asset receives the expected collection/statistics/TSFM coverage instead of silently narrowing to one asset.

### Behavior logs

Behavior logs are JSONL files written to:

```text
logs/supervisor_specialist/case_<timestamp>_<id>.jsonl
```

Single-turn and multi-turn logs use the same top-level schema:

```json
{
  "timestamp": "2026-04-28T00:00:00+00:00",
  "case_id": "case_20260428000000_ab12cd",
  "agent_role": "time_series_analysis_specialist",
  "task_type": "anomaly_analysis",
  "input_artifact_ids": ["..."],
  "tool_calls": [],
  "output_artifact_ids": ["..."],
  "status": "ok"
}
```

Multi-turn logs include `turn_id`:

```json
{"turn_id": "turn_001"}
```

Parallel tool calls include per-call metadata:

```json
{
  "tool_name": "tsfm.run_integrated_tsad",
  "parallel_group_id": "pg_1234abcd",
  "parallel_index": 1,
  "parallel_size": 4
}
```

The final response is also logged by the `respond_to_user` entry using `task_type: "final_response"`.

### Python API

```python
import asyncio

from agent.supervisor_specialist.runner import SupervisorSpecialistRunner
from llm import LiteLLMBackend

llm = LiteLLMBackend("watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8")
runner = SupervisorSpecialistRunner(
    llm=llm,
    reference_date="2020-06-20",
    parallel=True,
)

answer = asyncio.run(runner.run("Compare Chiller 6 and Chiller 9 over the past month."))
print(answer)
```

For multi-turn workflows, reuse the same runner and call `run_turn` repeatedly:

```python
async def main():
    runner = SupervisorSpecialistRunner(llm=llm, reference_date="2020-06-20")
    print(await runner.run_turn("Find anomalies at Site MAIN over the past month."))
    print(await runner.run_turn("What could be causing this?"))

asyncio.run(main())
```

---

## Connect to Claude Desktop

Add the following to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "utilities": {
      "command": "/path/to/uv",
      "args": [
        "run",
        "--project",
        "/path/to/AssetOpsBench",
        "utilities-mcp-server"
      ]
    },
    "iot": {
      "command": "/path/to/uv",
      "args": ["run", "--project", "/path/to/AssetOpsBench", "iot-mcp-server"]
    },
    "fmsr": {
      "command": "/path/to/uv",
      "args": ["run", "--project", "/path/to/AssetOpsBench", "fmsr-mcp-server"]
    },
    "tsfm": {
      "command": "/path/to/uv",
      "args": ["run", "--project", "/path/to/AssetOpsBench", "tsfm-mcp-server"]
    },
    "wo": {
      "command": "/path/to/uv",
      "args": ["run", "--project", "/path/to/AssetOpsBench", "wo-mcp-server"]
    },
    "vibration": {
      "command": "/path/to/uv",
      "args": ["run", "--project", "/path/to/AssetOpsBench", "vibration-mcp-server"]
    }
  }
}
```

---

## Running Tests

Run the full suite from the repo root (unit + integration where services are available):

```bash
uv run pytest src/ -v
```

Integration tests are auto-skipped when the required service is not available:

- IoT integration tests require `COUCHDB_URL` (set in `.env`)
- Work order integration tests require `COUCHDB_URL` (set in `.env`)
- FMSR integration tests require `WATSONX_APIKEY` (set in `.env`)
- TSFM integration tests require `PATH_TO_MODELS_DIR` and `PATH_TO_DATASETS_DIR` (set in `.env`)

### Unit tests only (no services required)

```bash
uv run pytest src/ -v -k "not integration"
```

### Per-server

```bash
uv run pytest src/servers/iot/tests/test_tools.py -k "not integration"
uv run pytest src/servers/utilities/tests/
uv run pytest src/servers/fmsr/tests/ -k "not integration"
uv run pytest src/servers/tsfm/tests/ -k "not integration"
uv run pytest src/servers/wo/tests/test_tools.py -k "not integration"
uv run pytest src/agent/tests/
uv run python -m pytest src/agent/supervisor_specialist -q
```

### Work order integration tests (requires CouchDB + populated `workorder` db)

```bash
docker compose -f src/couchdb/docker-compose.yaml up -d
uv run pytest src/servers/wo/tests/test_integration.py -v
```

### Integration tests (requires CouchDB + WatsonX)

```bash
docker compose -f src/couchdb/docker-compose.yaml up -d
uv run pytest src/ -v
```

---

## Architecture

Plan-Execute is the simpler planner/executor path:

```
┌──────────────────────────────────────────────────────┐
│                     agent/                          │
│                                                      │
│  PlanExecuteRunner.run(question)                     │
│  ┌────────────┐   ┌────────────┐   ┌──────────────┐ │
│  │  Planner   │ → │  Executor  │ → │  Summariser  │ │
│  │            │   │            │   │              │ │
│  │ LLM breaks │   │ Routes each│   │ LLM combines │ │
│  │ question   │   │ step to the│   │ step results │ │
│  │ into steps │   │ right MCP  │   │ into answer  │ │
│  └────────────┘   │ server via │   └──────────────┘ │
│                   │ stdio      │                     │
└───────────────────┼────────────┼─────────────────────┘
                    │ MCP protocol (stdio)
         ┌──────────┼──────────┬──────────┬──────┬───────────┐
         ▼          ▼          ▼          ▼      ▼           ▼
        iot     utilities    fmsr       tsfm    wo      vibration
      (tools)    (tools)    (tools)   (tools) (tools)    (tools)
```

Supervisor-Specialist is the LangGraph multi-agent path:

```
┌────────────────────────────────────────────────────────────────┐
│              agent/supervisor_specialist/                      │
│                                                                │
│  prepare_turn → supervisor ─┬→ data_collection_specialist ─┐   │
│                             ├→ time_series_analysis         │   │
│                             ├→ failure_reasoning            │   │
│                             ├→ maintenance_planning         │   │
│                             └→ respond_to_user              │   │
│                                      ▲                       │   │
│                                      └──── artifact store,   │   │
│                                            memory, logs      │   │
└──────────────────────────────────────┬─────────────────────────┘
                                       │ MCP protocol (stdio)
         ┌─────────────────────────────┼──────────┬──────┬───────────┐
         ▼                             ▼          ▼      ▼           ▼
        iot                        utilities    fmsr   tsfm          wo
      (data)                       (helpers)  (reason) (analysis) (orders)
```

Use `plan-execute` for general MCP planning and simple tool orchestration. Use `supervisor-specialist` for asset-operations dialogs where memory, artifacts, domain Specialists, behavior logs, and optional multi-asset parallel analysis matter.
