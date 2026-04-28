## Quick Start
You need to put the downloaded `main.json` in the `src/couchdb/sample_data/iot` directory before running Docker Compose.

```
uv sync
source .venv/bin/activate
docker compose -f src/couchdb/docker-compose.yaml up -d
uv run plan-execute --show-plan --show-history "What is the current date and time? Also list assets at site MAIN."
```

`docker compose` initializes the IoT CouchDB database from `src/couchdb/sample_data/iot/main.json`, filtered to `Chiller 3`, `Chiller 4`, `Chiller 6`, and `Chiller 9`.

To verify the imported sample data:
```
python src/couchdb/check_couchdb_data.py
```

Supervisor-Specialist architecture examples:
```
uv run supervisor-specialist --reference-date 2020-06-20 "The temperature of our chiller at Site MAIN seems unusually high lately. Can you look into it?"
uv run supervisor-specialist --reference-date 2020-06-20 "I want to compare the efficiency of Chiller 6 and Chiller 9 at the MAIN site over the past month."
```

Multi-turn dialog keeps one in-memory LangGraph session and writes JSONL behavior logs:
```
uv run supervisor-specialist --multi-turn --reference-date 2020-06-20
```

Enable Specialist-level parallel tool batches and deterministic multi-asset coverage with `--parallel`:
```
uv run supervisor-specialist --parallel --reference-date 2020-06-20 "Compare Chiller 3, Chiller 4, Chiller 6, and Chiller 9 over the past month."
uv run supervisor-specialist --parallel --multi-turn --reference-date 2020-06-20
```

Logs are written to `logs/supervisor_specialist/case_<timestamp>_<id>.jsonl`. The log schema matches single-turn and multi-turn runs; multi-turn records also include `turn_id`, and parallel tool calls include `parallel_group_id`, `parallel_index`, and `parallel_size`.

Your `.env` file should be like (fill `WATSONX_APIKEY` and `WATSONX_PROJECT_ID` first):
```
# ── CouchDB (IoTAgent server) ────────────────────────────────────────────────
COUCHDB_URL=http://localhost:5984
IOT_DBNAME=chiller
WO_DBNAME=workorder
COUCHDB_USERNAME=admin
COUCHDB_PASSWORD=password

# ── IBM WatsonX (plan-execute and supervisor-specialist runners) ─────────────
WATSONX_APIKEY=
WATSONX_PROJECT_ID=
WATSONX_URL=https://us-south.ml.cloud.ibm.com   # optional

# ── LiteLLM (plan-execute and supervisor-specialist runners) ─────────────────
LITELLM_API_KEY=
LITELLM_BASE_URL=

# ── Supervisor-Specialist optional controls ──────────────────────────────────
SS_MODEL_ID=watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8
SS_MAX_STEPS=12
SUPERVISOR_SPECIALIST_PARALLELISM=4
```

## Repository Layout

### MCP Servers — `src/servers/`

| Directory | Entry point | External dependencies |
| --- | --- | --- |
| `src/servers/iot/` | `iot-mcp-server` | CouchDB |
| `src/servers/utilities/` | `utilities-mcp-server` | None |
| `src/servers/fmsr/` | `fmsr-mcp-server` | WatsonX (optional) |
| `src/servers/tsfm/` | `tsfm-mcp-server` | PyTorch (optional) |
| `src/servers/wo/` | `wo-mcp-server` | CouchDB |
| `src/servers/vibration/` | `vibration-mcp-server` | CouchDB |

### Plan-Execute Runner — `src/agent/`

- `cli.py` — entry point for the `plan-execute` command
- `runner.py` — main `PlanExecuteRunner` logic
- `plan_execute/` — `Planner` / `Executor` / `Summariser` submodules
- `models.py` — data models (`Plan`, `StepResult`, etc.)

### Supervisor-Specialist Runner — `src/agent/supervisor_specialist/`

- `cli.py` — entry point for the `supervisor-specialist` command
- `runner.py` — LangGraph-backed runner and in-memory multi-turn session management
- `graph.py` — graph state, turn preparation, routing, final response, and memory updates
- `agents/` — Supervisor plus data collection, time-series analysis, failure reasoning, and maintenance planning specialists
- `runtime/` — artifact store, MCP tool client, behavior logger, and streaming event output
- `schemas.py` — shared state, artifact, tool-call, memory, and log models

Run focused Supervisor-Specialist tests:
```
uv run python -m pytest src/agent/supervisor_specialist -q
```

### LLM Backends — `src/llm/`

- `litellm.py` — LiteLLM / WatsonX backend implementation
- `base.py` — abstract `LLMBackend` interface

### Infrastructure

- `src/couchdb/` — Docker Compose files and data initialization scripts
- `pyproject.toml` — project configuration and CLI entry point registration
- `uv.lock` — dependency lockfile
