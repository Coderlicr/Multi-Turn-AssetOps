# Supervisor-specialist tests

Tests are separated by responsibility. All LLM responses and MCP server calls
are mocked, so no API credentials or Docker are required.

```text
tests/
├── core/                          # Agent flows, state, evidence, and results
├── test_execution_constraints.py  # Runtime limits and validation
├── test_decision_boundaries.py    # Agent decision boundaries
├── parallel_support.py           # Fake clients and scripted LLMs
├── specialist_support.py         # Specialist factories
├── conftest.py                    # Async backend and isolated CSV inputs
└── README.md
```

## Core flows

| File in `core/` | Coverage |
| --- | --- |
| `test_artifact_store.py` | Artifact IDs, storage, and lookup |
| `test_graph_routing.py` | Supervisor dispatch, specialist return, and result persistence |
| `test_mcp_tool_routing.py` | MCP routing, schema filtering, and error results |
| `test_multi_turn.py` | Conversation memory, time-window continuity, evidence reuse, and explicitly selected artifacts |
| `test_parallel_execution.py` | Concurrent tool execution, ordered results, aggregation, and batch metadata |
| `test_runner_smoke.py` | Complete runner flow and final response at the step limit |
| `test_specialist_protocol.py` | ReAct sequencing, result feedback, artifact envelopes, and dataset path normalization |

## Execution constraints

| File in `tests/` | Coverage |
| --- | --- |
| `test_execution_constraints.py` | Step and tool-call budgets, oversized batches, concurrency limits, same-batch deduplication, permissions, file arguments, and sequential mode |
| `test_decision_boundaries.py` | Respect `done`, allow explicit repeat calls, and avoid implicit data collection, analysis, or synthesized coverage |

## Running tests

From the repository root, run everything:

```sh
uv run --no-sync pytest src/agent/supervisor_specialist/tests -q
```

Each group can also be run independently:

```sh
uv run --no-sync pytest src/agent/supervisor_specialist/tests/core -q
uv run --no-sync pytest src/agent/supervisor_specialist/tests/test_execution_constraints.py src/agent/supervisor_specialist/tests/test_decision_boundaries.py -q
```

The GitHub Actions `unit-tests` job runs the entire `tests/` directory, including the core subdirectory and the constraint files. New `test_*.py` files are collected automatically.
Runner logs and CSV inputs use temporary directories. Shared support code is imported by tests and is not collected as a test suite.
