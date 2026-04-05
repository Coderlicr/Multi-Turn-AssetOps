# AssetOpsBench Upper-Level Agent Refactoring — Phased Implementation Guide

> **Purpose**: Step-by-step engineering roadmap for transforming the current `PlanExecuteRunner` into a closed-loop, multi-agent industrial orchestration system. Each phase is self-contained, testable, and backward-compatible.
>
> **Constraint**: MCP server layer (`iot-mcp-server`, `fmsr-mcp-server`, `tsfm-mcp-server`, `wo-mcp-server`, `utilities-mcp-server`, `vibration-mcp-server`) remains **unchanged** throughout all phases.

---

## Current Baseline

```
src/agent/
├── plan_execute/
│   ├── runner.py      # PlanExecuteRunner: Discover → Plan → Execute → Summarize
│   ├── planner.py     # LLM generates text-format plan, parsed via regex
│   ├── executor.py    # Sequential execution, short-lived MCP stdio sessions
│   └── models.py      # PlanStep, Plan, StepResult (dataclasses)
├── models.py          # OrchestratorResult
├── runner.py          # Abstract AgentRunner base class
└── cli.py             # CLI entry point
```

**Current workflow**: `PlanExecuteRunner.run(question)` → discover servers → LLM generates plan (text) → executor runs steps sequentially → LLM summarizes results → return `OrchestratorResult`.

**Current data models**: `PlanStep(step_number, task, server, tool, tool_args, dependencies, expected_output)`, `StepResult(step_number, task, server, response, error)`.

---

## Phase 1 — Structured Foundation (Week 1–3)

**Goal**: Replace fragile text-based plan with strong-typed data models. Add artifact tracking and basic error recovery. Zero architecture change — still a single orchestrator.

### 1.1 Structured Plan Schema

**What to build**: Replace the text-format plan output with JSON Schema-validated plans.

**File**: `src/agent/models.py` (extend existing)

```python
# === INPUT to Planner ===
# question: str              — user's natural language query
# server_descriptions: dict  — {server_name: tool_signatures_text}

# === OUTPUT from Planner (NEW — replaces text-parsed Plan) ===
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

class PlanStepV2(BaseModel):
    """A single step in the execution plan."""
    step_number: int
    task: str                                    # Natural language description
    server: str                                  # MCP server name (iot, fmsr, tsfm, wo)
    tool: str                                    # Exact tool name from MCP
    tool_args: dict = Field(default_factory=dict)
    dependencies: list[int] = Field(default_factory=list)
    expected_output: str = ""
    preconditions: list[str] = Field(default_factory=list)   # NEW
    postconditions: list[str] = Field(default_factory=list)  # NEW
    status: TaskStatus = TaskStatus.PENDING                  # NEW
    max_retries: int = 2                                     # NEW

class PlanV2(BaseModel):
    """Structured execution plan with dependency graph."""
    steps: list[PlanStepV2]
    original_question: str
    
    def independent_groups(self) -> list[list[PlanStepV2]]:
        """Return groups of steps that can execute in parallel."""
        # Steps with no unmet dependencies form a parallel group
        ...
```

**Planner prompt change**: Force LLM to output raw JSON matching the schema. Add a `json_mode` flag to the LLM call if supported, or post-validate with Pydantic.

**Acceptance test**: Run all 152 single-turn benchmark scenarios. Every plan must parse without error. Success rate must not decrease from baseline.

### 1.2 Artifact Registry

**What to build**: A registry that stores metadata about intermediate results (not the raw data).

**File**: `src/agent/artifacts.py` (new)

```python
# === Artifact lifecycle ===
# CREATED BY:  executor, after each successful tool call
# READ BY:     executor (to resolve cross-step dependencies),
#              summarizer (to build final answer)
# STORED IN:   in-memory dict (Phase 1), later can be swapped for Redis/S3

from pydantic import BaseModel, Field
from typing import Any, Optional
import uuid

class Artifact(BaseModel):
    """Metadata wrapper for any intermediate result."""
    id: str = Field(default_factory=lambda: f"ART-{uuid.uuid4().hex[:8]}")
    artifact_type: str          # "sensor_list", "timeseries_df", "anomaly_report", 
                                # "failure_modes", "work_order", "raw_json"
    created_by_step: int        # Which plan step produced this
    created_by_server: str      # Which MCP server
    summary: str                # ≤200 chars, safe for LLM context
    raw_data: Any               # Full data (kept OUT of LLM prompts)
    depends_on: list[str] = Field(default_factory=list)  # Artifact IDs of upstream deps

class ArtifactRegistry:
    """In-memory artifact store with lineage tracking."""
    
    def __init__(self):
        self._store: dict[str, Artifact] = {}
    
    def register(self, artifact: Artifact) -> str:
        self._store[artifact.id] = artifact
        return artifact.id
    
    def get(self, artifact_id: str) -> Optional[Artifact]:
        return self._store.get(artifact_id)
    
    def get_summary(self, artifact_id: str) -> str:
        """Return summary only — this is what goes into LLM context."""
        art = self._store.get(artifact_id)
        return art.summary if art else ""
    
    def get_raw(self, artifact_id: str) -> Any:
        """Return raw data — for code execution, NOT for LLM prompts."""
        art = self._store.get(artifact_id)
        return art.raw_data if art else None
    
    def lineage(self, artifact_id: str) -> list[str]:
        """Trace back through depends_on to build full evidence chain."""
        ...
```

**Integration point**: After each `_call_tool()` in `executor.py`, wrap the result:

```python
# BEFORE (current code):
result_text = await _call_tool(server_path, tool_name, args)
step_result = StepResult(step_number=step.step_number, ..., response=result_text)

# AFTER (Phase 1):
result_text = await _call_tool(server_path, tool_name, args)
artifact = Artifact(
    artifact_type=infer_type(tool_name),  # heuristic from tool name
    created_by_step=step.step_number,
    created_by_server=step.server,
    summary=truncate_for_llm(result_text, max_chars=200),
    raw_data=result_text,
    depends_on=[...],  # artifact IDs from dependency steps
)
registry.register(artifact)
step_result = StepResultV2(..., response=result_text, artifact_id=artifact.id)
```

### 1.3 Step-Level Validator

**What to build**: A simple post-execution check for each step.

**File**: `src/agent/validator.py` (new)

```python
# === INPUT ===
# step: PlanStepV2         — what was planned
# result: StepResultV2     — what was returned
# artifact: Artifact       — the registered artifact

# === OUTPUT ===
# ValidationResult(passed: bool, reason: str, action: "continue"|"retry"|"replan")

class ValidationResult(BaseModel):
    passed: bool
    reason: str
    action: str = "continue"  # "continue" | "retry" | "replan"

def validate_step(step: PlanStepV2, result: StepResultV2, artifact: Artifact) -> ValidationResult:
    """Rule-based validation — no LLM needed."""
    
    # Check 1: Tool call succeeded (no error)
    if result.error:
        return ValidationResult(passed=False, reason=result.error, action="retry")
    
    # Check 2: Response is non-empty
    if not result.response or result.response.strip() == "":
        return ValidationResult(passed=False, reason="Empty response", action="retry")
    
    # Check 3: If response is JSON, it's valid
    if looks_like_json(result.response):
        try:
            json.loads(result.response)
        except json.JSONDecodeError:
            return ValidationResult(passed=False, reason="Invalid JSON", action="retry")
    
    return ValidationResult(passed=True, reason="OK")
```

### 1.4 Retry and Re-plan

**What to build**: When a step fails validation, retry with adjusted parameters. After max retries, trigger re-plan for remaining steps.

**Integration in executor.py**:

```python
# === Retry flow ===
# For each step:
#   attempt = 0
#   while attempt < step.max_retries:
#     result = call_tool(...)
#     validation = validate_step(step, result, artifact)
#     if validation.passed:
#       break
#     elif validation.action == "retry":
#       attempt += 1
#       # LLM regenerates tool_args with error context appended
#     elif validation.action == "replan":
#       # Return control to Planner with partial results
#       break

# === Re-plan INPUT ===
# original_question: str
# completed_steps: list[StepResultV2]   — steps that succeeded
# failed_step: StepResultV2             — the step that failed
# remaining_steps: list[PlanStepV2]     — steps not yet attempted

# === Re-plan OUTPUT ===
# new_plan: PlanV2  — replacement plan for remaining work only
```

### 1.5 Phase 1 Deliverables Checklist

| Deliverable | File(s) | Test |
|---|---|---|
| Pydantic plan schema | `src/agent/models.py` | All 152 scenarios produce valid JSON plans |
| Artifact registry | `src/agent/artifacts.py` | Unit tests for register/get/lineage |
| Step validator | `src/agent/validator.py` | Unit tests for each validation rule |
| Retry logic | `src/agent/plan_execute/executor.py` | Integration test: mock tool failure → retry succeeds |
| Re-plan logic | `src/agent/plan_execute/planner.py` | Integration test: step 2 fails → re-plan steps 2-3 |
| Backward compat | `src/agent/plan_execute/runner.py` | CLI `uv run plan-execute` still works identically |

---

## Phase 2 — Blackboard, World Model Interface, and State Machine (Week 3–5)

**Goal**: Introduce the shared state layer that all future components will read/write. Add workflow phase tracking (state machine) and world model interface. Still a single orchestrator — multi-agent split comes in Phase 3.

### 2.1 Blackboard State

**What to build**: A single typed object that replaces ad-hoc context passing between steps.

**File**: `src/agent/blackboard.py` (new)

```python
# === WHO READS/WRITES EACH FIELD ===
# See access control column below

from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, Any

class WorkflowPhase(str, Enum):
    """State machine states for dialog-level workflow tracking."""
    INTAKE = "intake"               # Parsing intent, extracting entities
    INVESTIGATING = "investigating" # Gathering data, running analyses
    DIAGNOSING = "diagnosing"       # Root cause analysis
    ACTIONING = "actioning"         # Generating work orders / recommendations
    CLOSED = "closed"               # Final report delivered

class AssetBelief(BaseModel):
    """World model: what we believe about one physical asset."""
    asset_id: str
    site: str
    health_status: str = "unknown"    # "normal", "degraded", "critical", "unknown"
    active_hypotheses: list[dict] = Field(default_factory=list)
    # Each: {cause: str, confidence: float, evidence: list[artifact_id]}
    ruled_out: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)

class Blackboard(BaseModel):
    """Shared state for all agents. Single source of truth."""
    
    # --- Intent & Entities (written by IntentRouter, read by all) ---
    original_intent: str = ""
    intent_type: str = ""           # "fault_diagnosis", "predictive_maintenance", 
                                    # "comparative_analysis", "work_order_query", etc.
    identified_assets: list[dict] = Field(default_factory=list)
    # Each: {site: str, asset_id: str, asset_type: str}
    
    # --- Workflow Phase (state machine) ---
    workflow_phase: WorkflowPhase = WorkflowPhase.INTAKE
    phase_history: list[dict] = Field(default_factory=list)
    # Each: {from_phase: str, to_phase: str, reason: str, timestamp: str}
    
    # --- Global Constraints ---
    global_constraints: list[str] = Field(default_factory=list)
    # e.g. ["only analyze data after 2020-04-27", "unit must be KWH"]
    
    # --- Task Execution ---
    task_dag: list[dict] = Field(default_factory=list)
    execution_status: dict[str, str] = Field(default_factory=dict)
    # {step_number_str: TaskStatus value}
    
    # --- Artifact Registry Reference ---
    artifact_ids: list[str] = Field(default_factory=list)
    
    # --- World Model (asset beliefs) ---
    world_state: dict[str, AssetBelief] = Field(default_factory=dict)
    # Keyed by asset_id
    
    # --- Confidence & Diagnostics ---
    overall_confidence: float = 0.0
    replan_count: int = 0
    total_tool_calls: int = 0
    warnings: list[str] = Field(default_factory=list)
```

### 2.2 State Machine Transitions

**What to build**: A pure-function transition engine (no LLM) that governs workflow phases.

**File**: `src/agent/state_machine.py` (new)

```python
# === INPUT ===
# blackboard: Blackboard        — current state
# trigger: str                   — what just happened

# === OUTPUT ===
# new_phase: WorkflowPhase      — next phase (or same if transition not allowed)
# allowed_servers: list[str]     — which MCP servers can be called in this phase

# === TRANSITION TABLE ===
# INTAKE → INVESTIGATING:        when intent_type is resolved
# INVESTIGATING → DIAGNOSING:    when at least one anomaly artifact exists
# DIAGNOSING → ACTIONING:        when top hypothesis confidence ≥ 0.5
# ACTIONING → CLOSED:            when work order artifact exists and validated
# DIAGNOSING → INVESTIGATING:    when information_gaps found (backward transition)
# ACTIONING → DIAGNOSING:        when validator rejects work order (backward transition)

PHASE_ALLOWED_SERVERS: dict[WorkflowPhase, set[str]] = {
    WorkflowPhase.INTAKE:         {"utilities"},           # Only basic queries
    WorkflowPhase.INVESTIGATING:  {"iot", "tsfm", "utilities"},
    WorkflowPhase.DIAGNOSING:     {"iot", "tsfm", "fmsr", "utilities"},
    WorkflowPhase.ACTIONING:      {"wo", "iot", "utilities"},
    WorkflowPhase.CLOSED:         set(),                   # No more tool calls
}

def try_transition(blackboard: Blackboard, trigger: str) -> tuple[WorkflowPhase, str]:
    """Attempt a phase transition. Returns (new_phase, reason).
    
    This is a pure function — no LLM calls. 
    Guards read from blackboard.world_state and blackboard.artifact_ids.
    """
    current = blackboard.workflow_phase
    
    if current == WorkflowPhase.INTAKE and trigger == "intent_resolved":
        return WorkflowPhase.INVESTIGATING, "Intent parsed, beginning investigation"
    
    if current == WorkflowPhase.INVESTIGATING and trigger == "anomaly_found":
        # Guard: at least one anomaly artifact must exist
        has_anomaly = any(
            aid.startswith("ART-") for aid in blackboard.artifact_ids
            # In real impl, check artifact_type == "anomaly_report"
        )
        if has_anomaly:
            return WorkflowPhase.DIAGNOSING, "Anomaly confirmed, starting diagnosis"
    
    if current == WorkflowPhase.DIAGNOSING and trigger == "diagnosis_complete":
        # Guard: top hypothesis confidence must be ≥ 0.5
        for asset_belief in blackboard.world_state.values():
            if asset_belief.active_hypotheses:
                top = max(asset_belief.active_hypotheses, key=lambda h: h.get("confidence", 0))
                if top.get("confidence", 0) >= 0.5:
                    return WorkflowPhase.ACTIONING, f"Diagnosis confident: {top['cause']}"
        # Not confident enough — stay in DIAGNOSING
        return current, "Diagnosis confidence too low, continue investigating"
    
    if current == WorkflowPhase.DIAGNOSING and trigger == "info_gap_found":
        return WorkflowPhase.INVESTIGATING, "Information gap found, gathering more data"
    
    if current == WorkflowPhase.ACTIONING and trigger == "work_order_validated":
        return WorkflowPhase.CLOSED, "Work order validated, generating report"
    
    if current == WorkflowPhase.ACTIONING and trigger == "work_order_rejected":
        return WorkflowPhase.DIAGNOSING, "Work order rejected, re-diagnosing"
    
    return current, "No valid transition"

def get_allowed_servers(phase: WorkflowPhase) -> set[str]:
    """Return which MCP servers can be called in the given phase."""
    return PHASE_ALLOWED_SERVERS.get(phase, set())
```

### 2.3 World Model Interface

**What to build**: An interface (not a full engine) that maintains asset beliefs. Starts as a thin layer over the blackboard, replaceable later.

**File**: `src/agent/world_model.py` (new)

```python
# === INTERFACE CONTRACT ===
# All methods are synchronous in Phase 2 (no LLM calls).
# Phase 4+ may swap in an LLM-backed or knowledge-graph-backed implementation.

class WorldModelInterface:
    """Maintains beliefs about asset health, hypotheses, and information gaps.
    
    Phase 2 implementation: rule-based updates on blackboard.world_state.
    Future: can be swapped for LLM-based or knowledge-graph-backed engine.
    """
    
    def __init__(self, blackboard: Blackboard):
        self._bb = blackboard
    
    def update_beliefs(self, asset_id: str, artifact: Artifact) -> None:
        """Update asset health belief based on a new artifact.
        
        INPUT:  asset_id (str), artifact (Artifact from registry)
        OUTPUT: modifies blackboard.world_state[asset_id] in place
        
        Rules (Phase 2 — rule-based, no LLM):
        - If artifact_type == "anomaly_report" and anomaly detected:
            → set health_status = "degraded"
        - If artifact_type == "failure_modes":
            → populate active_hypotheses with equal confidence
        - If artifact_type == "work_order":
            → no health change
        """
        ...
    
    def predict_transition(self, proposed_action: str) -> dict:
        """Predict what would happen if we take an action.
        
        INPUT:  proposed_action (str), e.g. "condenser_cleaning"
        OUTPUT: {predicted_outcome: str, confidence: float}
        
        Phase 2: returns static templates.
        Phase 4+: LLM-generated predictions using VAGEN-style reasoning.
        """
        ...
    
    def get_information_gaps(self, asset_id: str) -> list[str]:
        """Return what we still don't know about this asset.
        
        INPUT:  asset_id (str)
        OUTPUT: list of gap descriptions
        
        Used by Supervisor to decide: continue investigating or proceed to action.
        """
        belief = self._bb.world_state.get(asset_id)
        if belief:
            return belief.information_gaps
        return ["No data collected for this asset yet"]
    
    def get_state_summary(self) -> str:
        """Compact text summary for LLM context injection.
        
        OUTPUT: ≤500 chars describing current world understanding.
        
        This replaces dumping raw artifacts into the LLM prompt.
        Inspired by VAGEN's <observation> block.
        """
        ...
```

### 2.4 Integration: Runner V2

**What to build**: Upgrade `PlanExecuteRunner` to use blackboard, state machine, and world model.

**File**: `src/agent/plan_execute/runner.py` (modify)

```python
# === NEW run() flow ===

async def run(self, question: str) -> OrchestratorResult:
    # 0. Initialize shared state
    blackboard = Blackboard(original_intent=question)
    registry = ArtifactRegistry()
    world_model = WorldModelInterface(blackboard)
    
    # 1. Discover
    server_descriptions = await self._executor.get_server_descriptions()
    
    # 2. Intent classification (simple LLM call)
    intent_result = classify_intent(self._llm, question)
    blackboard.intent_type = intent_result.intent_type
    blackboard.identified_assets = intent_result.assets
    blackboard.workflow_phase, _ = try_transition(blackboard, "intent_resolved")
    
    # 3. Plan (constrained by current phase)
    allowed = get_allowed_servers(blackboard.workflow_phase)
    plan = self._planner.generate_plan(
        question, 
        {k: v for k, v in server_descriptions.items() if k in allowed}
    )
    
    # 4. Execute with validation + retry + artifact tracking
    history = await self._executor.execute_plan_v2(
        plan, question, blackboard, registry, world_model
    )
    
    # 5. Check if state machine allows transition
    #    (e.g., anomaly found → move to DIAGNOSING)
    #    This is where multi-turn logic will plug in (Phase 3+)
    
    # 6. Summarize using world model summary (not raw artifacts)
    answer = self._llm.generate(
        SUMMARIZE_PROMPT.format(
            question=question,
            world_summary=world_model.get_state_summary(),
            results=format_step_summaries(history, registry)
        )
    )
    
    return OrchestratorResult(
        question=question, answer=answer, plan=plan, history=history,
        blackboard=blackboard  # NEW: expose for debugging/evaluation
    )
```

### 2.5 Phase 2 Deliverables Checklist

| Deliverable | File(s) | Test |
|---|---|---|
| Blackboard schema | `src/agent/blackboard.py` | Pydantic validation tests |
| State machine | `src/agent/state_machine.py` | Unit tests: all transitions + guards |
| World model interface | `src/agent/world_model.py` | Unit tests: update_beliefs, get_gaps |
| Runner V2 | `src/agent/plan_execute/runner.py` | 152 scenarios still pass |
| Phase enforcement | State machine + runner | Test: WO agent blocked in INVESTIGATING phase |

---

## Phase 3 — Multi-Agent Split and Parallel Execution (Week 5–8)

**Goal**: Split the single executor into Supervisor + scoped Specialist executors. Enable parallel execution of independent tasks. Introduce MCP session reuse.

### 3.1 Supervisor Agent

**What to build**: A new orchestration layer that decomposes tasks and dispatches to specialists.

**File**: `src/agent/supervisor.py` (new)

```python
# === SUPERVISOR RESPONSIBILITIES ===
# 1. Read blackboard (intent, assets, world state, phase)
# 2. Generate task DAG (JSON Schema) — only for allowed servers in current phase
# 3. Dispatch tasks to specialist executor(s)
# 4. After each task: update blackboard, run world model, check state machine
# 5. If state transition → generate next DAG for new phase
# 6. If validation fails → re-plan remaining tasks

# === INPUT ===
# blackboard: Blackboard
# registry: ArtifactRegistry
# server_descriptions: dict[str, str]

# === OUTPUT ===
# Updated blackboard (mutated in place)
# All artifacts registered
# Final OrchestratorResult

class Supervisor:
    def __init__(self, llm: LLMBackend, specialists: dict[str, SpecialistExecutor]):
        self._llm = llm
        self._specialists = specialists  # {server_name: SpecialistExecutor}
    
    async def run_turn(self, blackboard: Blackboard, registry: ArtifactRegistry) -> list[StepResultV2]:
        """Execute one turn of the supervisor loop.
        
        A turn = one DAG generation + execution + validation cycle.
        Multi-turn dialogs call this method repeatedly.
        """
        # 1. Generate DAG for current phase
        allowed = get_allowed_servers(blackboard.workflow_phase)
        dag = self._generate_dag(blackboard, allowed)
        
        # 2. Execute (with parallelism for independent tasks)
        results = await self._execute_dag(dag, blackboard, registry)
        
        # 3. Update world model
        for result in results:
            if result.artifact_id:
                artifact = registry.get(result.artifact_id)
                for asset in blackboard.identified_assets:
                    world_model.update_beliefs(asset["asset_id"], artifact)
        
        # 4. Check state machine transitions
        trigger = self._determine_trigger(blackboard, results)
        new_phase, reason = try_transition(blackboard, trigger)
        if new_phase != blackboard.workflow_phase:
            blackboard.phase_history.append({...})
            blackboard.workflow_phase = new_phase
        
        return results
```

### 3.2 Specialist Executor (Scoped)

**What to build**: A scoped executor that can only call tools from one MCP server, with local retry.

**File**: `src/agent/specialist.py` (new)

```python
# === KEY DIFFERENCE FROM CURRENT EXECUTOR ===
# 1. Scoped to ONE MCP server (enforced, not just by convention)
# 2. Has local ReAct retry loop (up to max_retries)
# 3. Produces Artifact on success, Exception artifact on failure
# 4. Does NOT do global re-planning — escalates to Supervisor

# === INPUT ===
# task: PlanStepV2           — single task from Supervisor's DAG
# question: str              — original user question (for context)
# blackboard: Blackboard     — read-only access to shared state
# registry: ArtifactRegistry — write access to register new artifacts

# === OUTPUT ===
# StepResultV2 with artifact_id set

class SpecialistExecutor:
    def __init__(self, server_name: str, server_path: str, llm: LLMBackend):
        self._server_name = server_name
        self._server_path = server_path
        self._llm = llm
        self._session = None  # MCP session (reused, see 3.3)
    
    async def execute_task(self, task: PlanStepV2, question: str,
                           blackboard: Blackboard, registry: ArtifactRegistry) -> StepResultV2:
        """Execute a single task with local ReAct retry loop."""
        
        for attempt in range(task.max_retries + 1):
            # 1. Generate tool args (LLM call with scoped system prompt)
            args = self._generate_args(task, question, blackboard, attempt)
            
            # 2. Call MCP tool
            try:
                result_text = await self._call_tool(task.tool, args)
            except Exception as e:
                if attempt < task.max_retries:
                    continue  # Retry with error context
                return StepResultV2(..., error=str(e))
            
            # 3. Validate
            artifact = self._wrap_artifact(task, result_text, registry)
            validation = validate_step(task, result, artifact)
            
            if validation.passed:
                return StepResultV2(..., artifact_id=artifact.id)
            
            if attempt < task.max_retries and validation.action == "retry":
                continue  # Try again with modified args
            
            # Max retries exhausted — return failure for Supervisor to handle
            return StepResultV2(..., error=validation.reason)
```

### 3.3 MCP Session Reuse

**What to build**: Replace per-call `stdio_client` sessions with persistent sessions.

**File**: `src/agent/mcp_pool.py` (new)

```python
# === CURRENT (executor.py) ===
# Every _call_tool() opens a new stdio session → cold start overhead

# === NEW ===
# MCPSessionPool maintains one persistent session per server
# Initialized once at startup, reused across all tool calls

class MCPSessionPool:
    """Maintains persistent MCP sessions for all registered servers."""
    
    async def initialize(self, server_paths: dict[str, str]) -> None:
        """Connect to all MCP servers and cache tool schemas."""
        # For each server:
        #   1. Open stdio session (keep alive)
        #   2. Call session.list_tools() once
        #   3. Cache tool schemas in memory
        ...
    
    async def call_tool(self, server_name: str, tool_name: str, args: dict) -> str:
        """Call a tool on an already-connected session."""
        ...
    
    async def shutdown(self) -> None:
        """Close all sessions gracefully."""
        ...
```

### 3.4 Parallel Execution

**What to build**: Execute independent DAG tasks concurrently using `asyncio.gather`.

```python
# In Supervisor._execute_dag():

async def _execute_dag(self, dag: PlanV2, blackboard, registry) -> list[StepResultV2]:
    results: dict[int, StepResultV2] = {}
    pending = set(s.step_number for s in dag.steps)
    
    while pending:
        # Find ready tasks (all dependencies met)
        ready = [
            s for s in dag.steps 
            if s.step_number in pending
            and all(d in results and results[d].success for d in s.dependencies)
        ]
        
        if not ready:
            break  # Deadlock or all remaining tasks have failed deps
        
        # Execute ready tasks in parallel
        coros = [
            self._specialists[s.server].execute_task(s, ...)
            for s in ready
        ]
        batch_results = await asyncio.gather(*coros, return_exceptions=True)
        
        for step, result in zip(ready, batch_results):
            results[step.step_number] = result
            pending.discard(step.step_number)
    
    return list(results.values())
```

### 3.5 Phase 3 Deliverables Checklist

| Deliverable | File(s) | Test |
|---|---|---|
| Supervisor agent | `src/agent/supervisor.py` | Multi-step scenario runs correctly |
| Specialist executor | `src/agent/specialist.py` | Scoped tool access enforced |
| MCP session pool | `src/agent/mcp_pool.py` | Session reuse (no cold starts after init) |
| Parallel execution | `src/agent/supervisor.py` | Independent tasks run concurrently |
| Phase enforcement | Supervisor + state machine | WO blocked until ACTIONING phase |

---

## Phase 4 — Verification, Local ReAct, and Multi-Turn (Week 8–12)

**Goal**: Add the 3-layer PEV verification, real local ReAct loops in specialists, and multi-turn dialog support.

### 4.1 Three-Layer Verification (PEV)

**File**: `src/agent/verification.py` (extend from `validator.py`)

```python
# === Layer 1: Tool Validator (before MCP call) ===
# INPUT:  tool_name, tool_args, blackboard
# OUTPUT: ValidationResult
# RULES:  - tool_args match MCP schema (Pydantic validation)
#          - asset IDs exist in blackboard.identified_assets
#          - timestamps are ISO 8601
#          - server is in allowed set for current phase

# === Layer 2: Domain Verifier (after MCP call, before blackboard write) ===
# INPUT:  artifact (with raw_data), blackboard
# OUTPUT: ValidationResult
# RULES:  - temperature values in plausible range (e.g., -50°C to 200°C)
#          - energy values are non-negative
#          - predicted values don't violate physical constraints
#          - TSFM output target column matches request

# === Layer 3: Response Critic (before final user output) ===
# INPUT:  draft_response (str), blackboard, world_model_summary
# OUTPUT: ValidationResult
# RULES:  (LLM-based) Does the response address original_intent?
#          Is confidence stated? Are evidence artifacts referenced?
#          Does it avoid "I'm an AI and cannot..." evasion patterns?
```

### 4.2 Multi-Turn Dialog Support

**File**: `src/agent/dialog.py` (new)

```python
# === MULTI-TURN SESSION ===
# Maintains blackboard across multiple user turns.
# Each turn triggers Supervisor.run_turn().

class DialogSession:
    """Manages a multi-turn conversation with persistent state."""
    
    def __init__(self, llm: LLMBackend, server_paths: dict):
        self._blackboard = Blackboard()
        self._registry = ArtifactRegistry()
        self._world_model = WorldModelInterface(self._blackboard)
        self._supervisor = Supervisor(llm, ...)
        self._turn_count = 0
    
    async def process_turn(self, user_message: str) -> str:
        """Process one user turn in the dialog.
        
        INPUT:  user_message (str) — user's natural language message
        OUTPUT: system_response (str) — agent's response
        
        FLOW:
        1. If first turn → full intent routing + plan + execute
        2. If follow-up → update blackboard with new intent, 
           keep existing artifacts and world state,
           Supervisor generates incremental DAG for new question
        """
        self._turn_count += 1
        
        if self._turn_count == 1:
            # Full initialization
            self._blackboard.original_intent = user_message
            intent = classify_intent(self._llm, user_message)
            self._blackboard.intent_type = intent.intent_type
            self._blackboard.identified_assets = intent.assets
            self._blackboard.workflow_phase, _ = try_transition(
                self._blackboard, "intent_resolved"
            )
        else:
            # Follow-up: update intent but keep accumulated state
            self._blackboard.original_intent += f" | Turn {self._turn_count}: {user_message}"
            # Supervisor will use existing world_state + new question
        
        # Run supervisor turn
        results = await self._supervisor.run_turn(
            self._blackboard, self._registry
        )
        
        # Generate response
        response = self._generate_response(results)
        return response
```

### 4.3 Phase 4 Deliverables Checklist

| Deliverable | File(s) | Test |
|---|---|---|
| 3-layer PEV | `src/agent/verification.py` | Unit tests per layer |
| Local ReAct in specialist | `src/agent/specialist.py` | Test: fuzzy sensor name → resolved after 2 retries |
| Multi-turn dialog | `src/agent/dialog.py` | Run Dialog 1 (5 turns) end-to-end |
| Response critic | `src/agent/verification.py` | Test: evasive response rejected |
| World model updates | `src/agent/world_model.py` | Test: beliefs update across turns |

---

## Phase 5 — Knowledge Layer and Evaluation (Week 12+)

**Goal**: Add domain knowledge (sensor ontology, failure taxonomy) and run evaluation against 15 multi-turn scenarios.

### 5.1 Knowledge Layer

```python
# === Sensor Ontology RAG ===
# FILE: src/agent/knowledge/sensor_ontology.py
# PURPOSE: Map user terms ("能耗", "power consumption") to MCP parameter names ("Power Input")
# FORMAT: YAML/JSON lookup table (no vector DB needed for Phase 5)
# CALLED BY: IntentRouter and Specialist agents before generating tool args

# === Failure Knowledge Base ===
# FILE: src/agent/knowledge/failure_taxonomy.py
# PURPOSE: Map sensor patterns to candidate failure modes
# SOURCE: Derived from fmsr-mcp-server's failure_modes.yaml
# CALLED BY: FMSR specialist for hypothesis generation
```

### 5.2 Evaluation Framework

```python
# === Run all 15 multi-turn scenarios ===
# FILE: src/evaluation/multi_turn_eval.py

# METRICS:
# 1. Task Success Rate       — did the agent complete the user's intent?
# 2. Planning Accuracy        — were the right tools called in the right order?
# 3. Tool Usage Correctness   — were tool parameters correct?
# 4. Recovery Ability         — did the agent recover from simulated failures?
# 5. Latency                  — end-to-end execution time
# 6. Token Cost               — total LLM token consumption
# 7. Replan Count             — how many times did the supervisor re-plan?

# COMPARISON BASELINES:
# A. Original PlanExecuteRunner (current codebase)
# B. Phase 1 runner (structured plan + retry)
# C. Phase 3 runner (supervisor + parallel)
# D. Phase 4 runner (full system)
```

---

## Final File Structure

```
src/agent/
├── plan_execute/
│   ├── runner.py            # PlanExecuteRunner (backward compat, wraps Supervisor)
│   ├── planner.py           # JSON Schema plan generation
│   ├── executor.py          # Legacy executor (kept for backward compat)
│   └── models.py            # PlanStepV2, PlanV2, StepResultV2
├── models.py                # OrchestratorResult
├── runner.py                # Abstract AgentRunner base
├── cli.py                   # CLI entry point
├── blackboard.py            # Blackboard, WorkflowPhase, AssetBelief      [Phase 2]
├── state_machine.py         # try_transition, get_allowed_servers          [Phase 2]
├── world_model.py           # WorldModelInterface                          [Phase 2]
├── artifacts.py             # Artifact, ArtifactRegistry                   [Phase 1]
├── validator.py             # Step validator (rule-based)                   [Phase 1]
├── verification.py          # 3-layer PEV verification                     [Phase 4]
├── supervisor.py            # Supervisor agent                              [Phase 3]
├── specialist.py            # SpecialistExecutor (scoped + local ReAct)    [Phase 3]
├── mcp_pool.py              # MCPSessionPool (persistent sessions)         [Phase 3]
├── dialog.py                # DialogSession (multi-turn)                    [Phase 4]
├── intent_router.py         # Intent classification + entity extraction     [Phase 2]
└── knowledge/
    ├── sensor_ontology.py   # Sensor name mapping                           [Phase 5]
    └── failure_taxonomy.py  # Failure mode knowledge base                   [Phase 5]
```

---

## Key Invariants Across All Phases

1. **MCP servers are never modified.** All changes are in `src/agent/`.
2. **CLI `uv run plan-execute` always works.** Each phase wraps new logic behind the existing interface.
3. **152 single-turn scenarios never regress.** Run the benchmark after every phase.
4. **Blackboard is the single source of truth.** No agent-to-agent direct communication.
5. **Artifacts stay out of LLM context.** Only summaries (≤200 chars) enter prompts; raw data stays in the registry.
6. **State machine transitions are pure functions.** No LLM calls in transition logic.
7. **World model is an interface.** Phase 2 uses rules; Phase 4+ can swap in LLM-based or KG-based implementations without changing callers.
