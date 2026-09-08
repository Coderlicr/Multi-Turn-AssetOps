## Quick Start
You need to put downloaded`main.json` in `src/couchdb/sample_data/iot` directory before running Docker Compose.

```
uv sync
source .venv/bin/activate
docker compose -f src/couchdb/docker-compose.yaml up -d
uv run plan-execute --show-plan --show-history "What is the current date and time? Also list assets at site MAIN."
```

Stirrup can use the same MCP servers through TokenRouter. Its default server
set is `iot`, `utilities`, `fmsr`, `tsfm`, and `wo` (`vibration` is excluded):

```bash
uv run stirrup-agent --no-code \
  --reference-date 2020-06-20 \
  --model-id tokenrouter/<model-name> \
  "List the assets available at site MAIN."
```

The Stirrup code-execution track is enabled by default. See
[`INSTRUCTIONS.md`](INSTRUCTIONS.md#stirrup-agent) for Docker/local backend and
workspace-preservation options.

`docker compose` initializes the IoT CouchDB database from `src/couchdb/sample_data/iot/main.json`, filtered to `Chiller 3`, `Chiller 4`, `Chiller 6`, and `Chiller 9`.

To verify the imported sample data:
```
python src/couchdb/check_couchdb_data.py
```

Supervisor-Specialists Architecture Examples:
```
uv run supervisor-specialist --reference-date 2020-06-20 "The temperature of our chiller at Site MAIN seems unusually high lately. Can you look into it?"
uv run supervisor-specialist --reference-date 2020-06-20 "I want to compare the efficiency of Chiller 6 and Chiller 9 at the MAIN site over the past month."
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

### Stirrup Runner — `src/agent/stirrup_agent/`

- `cli.py` — entry point for the `stirrup-agent` command
- `runner.py` — TokenRouter-aware Stirrup runner and five-server MCP defaults
- `workspace_bridge.py` — makes file-producing MCP results available to code execution

### LLM Backends — `src/llm/`

- `litellm.py` — LiteLLM / WatsonX backend implementation
- `routers.py` — LiteLLM Proxy / TokenRouter prefix and credential resolution
- `base.py` — abstract `LLMBackend` interface

### Infrastructure

- `src/couchdb/` — Docker Compose files and data initialization scripts
- `pyproject.toml` — project configuration and CLI entry point registration
- `uv.lock` — dependency lockfile
