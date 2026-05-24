# Towards Multi-Turn Dialog Systems for Industrial Asset Operations and Maintenance

## 1. Problem Statement

Industrial operations and maintenance (O&M) question answering is naturally multi-turn: users refine queries, ask follow-up questions, and expect the system to reuse previous evidence while invoking specialized tools. The baseline Plan-Execute single-agent workflow is fragile in this setting because it plans mostly linearly, repeats expensive tool calls, struggles with tool-argument hallucination, and expands context rapidly after failures.

This project targets **inference-time system performance** for a tool-centric industrial diagnostic agent. The primary bottleneck is not GPU training throughput, but end-to-end inference latency and cost across remote LLM calls, MCP tool execution, CouchDB retrieval, and multi-agent routing. We optimize the runtime by adding memory-aware artifact reuse, Supervisor-Specialist routing, and optional parallel MCP tool execution.

---

## 2. Model/Application Description

- **Application:** Multi-turn industrial asset operations assistant for fault diagnosis, predictive maintenance, operational monitoring, maintenance planning, and end-to-end remediation workflows.
- **LLM backend:** LiteLLM wrapper over IBM WatsonX. The default model in the CLI is `watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8`.
- **Agent architectures compared:**
  - **Baseline:** Plan-Execute single-agent workflow with sequential MCP tool calls.
  - **SS:** Supervisor-Specialist architecture implemented with LangGraph.
  - **SSA:** Supervisor-Specialist Advanced with parallel MCP tool batches.
- **Specialist agents:** Data Collection, Time Series Analysis, Failure Reasoning, and Maintenance Planning, routed by a Supervisor agent.
- **Forecasting/anomaly models:** IBM Granite-TSFM / TinyTimeMixer artifacts under `src/servers/tsfm/artifacts/tsfm_models/`; conformal anomaly detection and TSFM forecasting are exposed through the TSFM MCP server.
- **Frameworks and libraries:** Python 3.12+, LangGraph, LiteLLM, FastMCP/MCP, CouchDB, PyTorch/Transformers/Granite-TSFM, pandas, NumPy, SciPy, Pydantic, Weights & Biases.
- **Dataset:** 16 multi-turn industrial diagnosis scenarios in `eval/scenarios.py`, derived from the AssetOpsBench-style workflow design in `DESIGN.md`.
- **Operational data:** IoT time-series data for MAIN site chillers 3, 4, 6, and 9; work orders, events, alerts, and failure-code mappings loaded into CouchDB.
- **Hardware target:** Remote IBM WatsonX inference for LLM calls plus local Python/MCP/CouchDB execution. The performance study measures system-level inference latency rather than model training throughput on a fixed GPU.

---

## 3. Final Results Summary

Measurements below are from the presentation results over 16 benchmark dialogs using IBM WatsonX / Llama-4-Maverick-17B-FP8.

**Headline numbers**

| Result | Baseline | Optimized / SS | Improvement |
| --- | ---: | ---: | --- |
| End-to-end dialog latency | 323.5 s avg/dialog | 265.5 s avg/dialog | **1.9x faster end-to-end** |
| TSFM tool latency | 159.5 s avg/dialog | 37.4 s avg/dialog | **4.3x TSFM tool speedup** |
| Follow-up turn latency | 145 s on SS turn 1 | 34 s avg on SS turns 2-5 | **4.2x faster after turn 1** |

**Profiler run-level summary**

| Metric | Baseline | SS | SSA |
| --- | ---: | ---: | ---: |
| Total wall time | 83.9 min | 65.2 min | 73.3 min |
| Total tokens consumed | 2,553,150 | 3,322,234 | 3,623,430 |
| Total LLM API calls | 841 | 941 | 751 |

**Latency breakdown by architecture**

| Architecture | LLM Time | Tool Time | Routing / Other |
| --- | ---: | ---: | ---: |
| Baseline Plan-Execute | 43.0% | 47.3% | 9.7% |
| SS | 69.3% | 26.3% | 4.4% |
| SSA | 72.3% | 23.9% | 3.8% |

**Headline result:** The Supervisor-Specialist system shifts the dominant bottleneck away from redundant tool execution: tool time drops from 47.3% to 26.3% of wall time, TSFM latency drops from 159.5 s to 37.4 s per dialog, and end-to-end evaluation wall time improves from 83.9 min to 65.2 min across the benchmark. 

---

## 4. Repository Structure

```text
.
|-- README.md
|-- DESIGN.md / DESIGN_annotated.md
|-- PROFILING.md
|-- pyproject.toml
|-- uv.lock
|-- eval/
|   |-- run_eval.py
|   |-- scenarios.py
|   `-- results/
|-- logs/
|   `-- supervisor_specialist/
|-- src/
|   |-- agent/
|   |   |-- cli.py
|   |   |-- plan_execute/
|   |   `-- supervisor_specialist/
|   |       |-- cli.py
|   |       |-- graph.py
|   |       |-- runner.py
|   |       |-- agents/
|   |       `-- runtime/
|   |-- couchdb/
|   |   |-- docker-compose.yaml
|   |   |-- init_asset_data.py
|   |   |-- init_wo.py
|   |   `-- sample_data/
|   |-- llm/
|   |   |-- base.py
|   |   `-- litellm.py
|   `-- servers/
|       |-- iot/
|       |-- wo/
|       |-- tsfm/
|       |-- fmsr/
|       |-- utilities/
|       `-- vibration/
`-- wandb/
```

---

## 5. Reproducibility Instructions

### A. Environment Setup

```bash
git clone https://github.com/Coderlicr/Multi-Turn-AssetOps.git
cd Multi-Turn-AssetOps

uv sync
source .venv/bin/activate
```

The project uses `uv` and requires Python 3.12+. Optional TSFM dependencies include PyTorch, Transformers, and `granite-tsfm`.

Create a `.env` file from `.env.example` and fill the WatsonX credentials:

```bash
cp .env.example .env
```

Important environment variables:

```text
COUCHDB_URL=http://localhost:5984
IOT_DBNAME=chiller
WO_DBNAME=workorder
COUCHDB_USERNAME=admin
COUCHDB_PASSWORD=password

WATSONX_APIKEY=<your key>
WATSONX_PROJECT_ID=<your project id>
WATSONX_URL=https://us-south.ml.cloud.ibm.com

SS_MODEL_ID=watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8
SS_MAX_STEPS=12
SUPERVISOR_SPECIALIST_PARALLELISM=4
```

### B. Data Setup

Place the downloaded IoT `main.json` at:

```text
src/couchdb/sample_data/iot/main.json
```

Start CouchDB and initialize the databases:

```bash
docker compose -f src/couchdb/docker-compose.yaml up -d
python src/couchdb/check_couchdb_data.py
```

The setup imports:

- IoT sensor data for Chiller 3, Chiller 4, Chiller 6, and Chiller 9 into the `chiller` database.
- Work-order and alert data from `src/couchdb/sample_data/work_order/` into the `workorder` database.
- Optional vibration data into the `vibration` database.

### C. Run the Baseline

```bash
uv run plan-execute --show-plan --show-history \
  "What is the current date and time? Also list assets at site MAIN."
```

### D. Run Supervisor-Specialist

Single-turn example:

```bash
uv run supervisor-specialist --reference-date 2020-06-20 \
  "The temperature of our chiller at Site MAIN seems unusually high lately. Can you look into it?"
```

Multi-turn session:

```bash
uv run supervisor-specialist --multi-turn --reference-date 2020-06-20
```

Parallel tool batches:

```bash
uv run supervisor-specialist --parallel --reference-date 2020-06-20 \
  "Compare Chiller 3, Chiller 4, Chiller 6, and Chiller 9 over the past month."
```

### E. Run the Benchmark Evaluation

Run all 16 dialogs:

```bash
uv run python eval/run_eval.py --system supervisor-specialist
```

Run a subset:

```bash
uv run python eval/run_eval.py --system supervisor-specialist --dialogs 1 2
```

Override the model:

```bash
uv run python eval/run_eval.py \
  --system supervisor-specialist \
  --model-id watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8
```

Each evaluation writes `dialog_XX.json`, per-dialog metrics JSONL files, and `summary.json` into `eval/results/<timestamp>/`.

### F. Profiling and Tracking

Profiling is implemented at three layers:

1. **LLM call metrics:** `src/llm/litellm.py` writes prompt tokens, completion tokens, total tokens, model name, and latency when `LITELLM_METRICS_FILE` is set.
2. **MCP tool metrics:** Plan-Execute and Supervisor-Specialist tool wrappers write tool name, server, latency, and success status when `TOOL_METRICS_FILE` is set.
3. **CouchDB query metrics:** IoT, WO, and vibration servers write query latency, status, and document counts when `COUCHDB_METRICS_FILE` is set.

For WandB and LangSmith, copy `.env.profiling.example` to `.env.profiling` and fill:

```text
WANDB_API_KEY=<your key>
WANDB_PROJECT=multi-turn-assetops
LANGCHAIN_API_KEY=<your key>
LANGCHAIN_PROJECT=<your project>
```

Then run:

```bash
uv run python eval/run_eval.py --system supervisor-specialist
```

The evaluation harness logs per-dialog latency, token usage, LLM calls, tool calls, CouchDB query metrics, per-turn success, and run-level summaries.

---

## 6. Results and Observations

- **Artifact reuse improves multi-turn efficiency.** The Supervisor-Specialist graph stores structured artifacts and rolling conversation memory so follow-up turns can reuse prior site, asset, sensor, time-window, anomaly, and failure-mode context.
- **Tool execution was the initial bottleneck.** In the baseline, tool calls account for 47.3% of wall time. SS reduces this to 26.3%, and SSA reduces it further to 23.9%.
- **TSFM dominates baseline latency.** Time-series forecasting and anomaly tools drop from 159.5 s per dialog in Plan-Execute to 37.4 s in SS and 36.1 s in SSA.
- **LLM latency becomes the new ceiling.** After reducing redundant tool work, LLM API time accounts for about 69-72% of wall time in the Supervisor-Specialist variants.
- **Parallelism helps selectively, but routing and reuse matter more.** SSA has the lowest tool fraction and fewer LLM calls than SS, but higher total tokens and longer total wall time than SS in the reported run.
- **Reliability improves with structured routing.** Tool-name validity reaches 100%, schema failures drop by 68.7%, execution failures drop by 59.0%, and recovery failures are eliminated in the reported benchmark.

Representative per-server tool latency:

| Server | Baseline | SS | SSA |
| --- | ---: | ---: | ---: |
| TSFM | 159.5 s | 37.4 s | 36.1 s |
| IoT | 24.9 s | 12.9 s | 11.8 s |
| WO | 12.4 s | 13.4 s | 12.9 s |
| Utilities | 4.0 s | 4.6 s | 4.1 s |
| FMSR | 9.9 s | 12.1 s | 19.7 s |

---

## 7. Implementation Notes

- MCP servers live in `src/servers/` and expose IoT, work-order, time-series, failure-mode, utility, and vibration tools.
- The Plan-Execute baseline is implemented under `src/agent/plan_execute/`.
- The Supervisor-Specialist system is implemented under `src/agent/supervisor_specialist/`.
- `src/agent/supervisor_specialist/runtime/artifact_store.py` holds in-memory artifacts for cross-turn reuse.
- `src/agent/supervisor_specialist/runtime/mcp_tools.py` implements MCP routing and both sequential and parallel tool-call execution.
- `eval/scenarios.py` defines the 16 benchmark dialogs and reference dates.
- `PROFILING.md` documents all profiling metrics and dashboard semantics.

---

## Acknowledgements

We are grateful to Dr. Dhaval Patel and Dr. Kaoutar El Maghraoui from IBM Research for their valuable guidance and mentorship throughout this work.

---

## License

Released under the Apache-2.0 License. See [`LICENSE`](LICENSE).
