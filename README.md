## Quick Start
```
uv sync
source .venv/bin/activate
docker compose -f src/couchdb/docker-compose.yaml up -d
uv run plan-execute --show-plan --show-history "What is the current date and time? Also list assets at site MAIN."
```

Your `.env` file should be like (fill `WATSONX_APIKEY` and `WATSONX_PROJECT_ID` first):
```
# ── CouchDB (IoTAgent server) ────────────────────────────────────────────────
COUCHDB_URL=http://localhost:5984
IOT_DBNAME=chiller
WO_DBNAME=workorder
COUCHDB_USERNAME=admin
COUCHDB_PASSWORD=password

# ── IBM WatsonX (plan-execute runner) ────────────────────────────────────────
WATSONX_APIKEY=
WATSONX_PROJECT_ID=
WATSONX_URL=https://us-south.ml.cloud.ibm.com   # optional

# ── LiteLLM (plan-execute runner) ────────────────────────────────────────────
LITELLM_API_KEY=
LITELLM_BASE_URL=
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

### LLM Backends — `src/llm/`

- `litellm.py` — LiteLLM / WatsonX backend implementation
- `base.py` — abstract `LLMBackend` interface

### Infrastructure

- `src/couchdb/` — Docker Compose files and data initialization scripts
- `pyproject.toml` — project configuration and CLI entry point registration
- `uv.lock` — dependency lockfile
