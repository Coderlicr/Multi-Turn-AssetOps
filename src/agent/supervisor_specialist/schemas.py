"""Pydantic models and TypedDict state for the Supervisor-Specialist system."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


RunMode = Literal["auto", "maintie", "assetops"]
SelectionScope = Literal["corpus", "active"]


class TimeWindow(BaseModel):
    start: str | None = None
    end: str | None = None
    mode: str | None = None
    lookback_days: int | None = None


class TaskEnvelope(BaseModel):
    case_id: str
    task_type: str
    goal: str
    site: str
    asset_ids: list[str]
    time_window: TimeWindow
    focus_metrics: list[str]
    input_artifacts: list[str]
    constraints: dict[str, Any] = Field(default_factory=dict)


class ArtifactEnvelope(BaseModel):
    artifact_id: str
    case_id: str
    producer: str
    artifact_type: Literal[
        "inventory",
        "dataset_ref",
        "analysis_result",
        "reasoning_result",
        "planning_result",
        "draft_action",
    ]
    asset_ids: list[str]
    time_window: TimeWindow
    source_tools: list[str]
    source_artifacts: list[str]
    payload: dict[str, Any]
    open_questions: list[str] = Field(default_factory=list)
    summary: str = ""


class CaseState(BaseModel):
    case_id: str
    user_goal: str
    site: str
    asset_ids: list[str]
    time_window: TimeWindow
    focus_metrics: list[str]
    status: Literal[
        "collecting_data",
        "analyzing",
        "reasoning",
        "planning",
        "waiting_for_user",
        "completed",
    ]
    artifact_ids: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    next_step: str | None = None


class ToolCallSummary(BaseModel):
    """Compact tool-call memory safe to include in future prompts."""

    order: int
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "failed"]
    result_preview: str | None = None
    error: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    parallel_group_id: str | None = None
    parallel_index: int | None = None
    parallel_size: int | None = None
    selection_scope: SelectionScope = "corpus"
    within_ids_count: int | None = None


class MaintIESelection(BaseModel):
    """Typed reusable MaintIE work-order set kept out of LLM prompts."""

    wo_ids: list[int]
    source_turn_index: int
    source_filter: dict[str, Any] = Field(default_factory=dict)
    parent_size: int | None = None


class ExecutionBudget(BaseModel):
    """Hard per-turn limits shared by the supervisor and specialists."""

    max_specialist_dispatches: int = Field(default=2, ge=1)
    max_tool_calls: int = Field(default=6, ge=1)
    specialist_dispatches_used: int = Field(default=0, ge=0)
    tool_calls_used: int = Field(default=0, ge=0)

    @property
    def remaining_dispatches(self) -> int:
        return max(self.max_specialist_dispatches - self.specialist_dispatches_used, 0)

    @property
    def remaining_tool_calls(self) -> int:
        return max(self.max_tool_calls - self.tool_calls_used, 0)

    def record_dispatch(self) -> bool:
        if self.remaining_dispatches <= 0:
            return False
        self.specialist_dispatches_used += 1
        return True

    def record_tool_calls(self, count: int) -> None:
        self.tool_calls_used = min(self.tool_calls_used + max(count, 0), self.max_tool_calls)


class DialogTurnRecord(BaseModel):
    """A compact record of one completed supervisor-specialist turn."""

    turn_index: int
    user_message: str
    assistant_answer: str
    artifact_ids: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    root_cause: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    structured_result: dict[str, Any] | None = None


class ConversationMemory(BaseModel):
    """Structured multi-turn memory for the current CLI session."""

    active_site: str = "MAIN"
    active_asset_ids: list[str] = Field(default_factory=list)
    active_time_window: TimeWindow = Field(default_factory=TimeWindow)
    focus_metrics: list[str] = Field(default_factory=list)
    rolling_summary: str = ""
    recent_turns: list[DialogTurnRecord] = Field(default_factory=list)
    active_artifact_ids: list[str] = Field(default_factory=list)
    active_maintie_selection: MaintIESelection | None = None
    max_recent_turns: int = 10


class GraphState(TypedDict, total=False):
    case_state: CaseState
    current_user_message: str
    conversation_memory: ConversationMemory
    current_task: TaskEnvelope | None
    last_artifacts: list[ArtifactEnvelope]
    final_response: str | None
    next_node: str
    step_count: int
    max_steps: int
    error_message: str | None
    turn_index: int
    turn_artifact_ids: list[str]
    turn_tool_calls: list[ToolCallSummary]
    execution_budget: ExecutionBudget
    structured_result: dict[str, Any] | None


# ── Specialist communication models ──────────────────────────────────────────


class ToolCallRequest(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    selection_scope: SelectionScope = "corpus"


class SpecialistStepDecision(BaseModel):
    """One ReAct step decision from a specialist LLM."""

    done: bool = False
    tool_name: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    selection_scope: SelectionScope = "corpus"
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    rationale: str | None = None


class ToolPlan(BaseModel):
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)


class ToolCallResult(BaseModel):
    order: int
    tool_name: str
    args: dict[str, Any]
    status: Literal["ok", "failed"]
    result: Any | None = None
    error: str | None = None
    parallel_group_id: str | None = None
    parallel_index: int | None = None
    parallel_size: int | None = None
    selection_scope: SelectionScope = "corpus"
    within_ids_count: int | None = None


class ArtifactDraft(BaseModel):
    artifact_type: Literal[
        "inventory",
        "dataset_ref",
        "analysis_result",
        "reasoning_result",
        "planning_result",
        "draft_action",
    ]
    asset_ids: list[str]
    time_window: TimeWindow = Field(default_factory=TimeWindow)
    source_artifacts: list[str] = Field(default_factory=list)
    payload: dict[str, Any]
    open_questions: list[str] = Field(default_factory=list)
    summary: str = ""


class SpecialistFinal(BaseModel):
    artifacts: list[ArtifactDraft]


class SpecialistResult(BaseModel):
    artifacts: list[ArtifactEnvelope]
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)


class MaintIEResultDraft(BaseModel):
    """The only LLM-authored object in the deterministic MaintIE response path."""

    model_config = ConfigDict(extra="forbid")

    result: dict[str, Any] | None


class SupervisorTurnResult(BaseModel):
    """Structured, serializable result for one Supervisor-Specialist turn."""

    question: str
    answer: str
    result: dict[str, Any] | None = None
    tools: list[list[str]] = Field(default_factory=list)
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    status: Literal["ok", "partial", "error"] = "ok"
    error: str | None = None


# ── Supervisor output model ───────────────────────────────────────────────────


class SupervisorDecision(BaseModel):
    next_node: Literal[
        "data_collection_specialist",
        "time_series_analysis_specialist",
        "failure_reasoning_specialist",
        "maintenance_planning_specialist",
        "respond_to_user",
    ]
    next_task: TaskEnvelope | None = None
    case_status: str
    next_step: str | None = None


# ── MCP tool models ───────────────────────────────────────────────────────────


class MCPToolResult(BaseModel):
    status: Literal["ok", "failed"]
    result: Any | None = None
    error: str | None = None


# ── Log models ────────────────────────────────────────────────────────────────


class ToolCallLog(BaseModel):
    order: int
    tool_name: str
    args: dict[str, Any]
    status: str
    result: Any | None = None
    error: str | None = None
    parallel_group_id: str | None = None
    parallel_index: int | None = None
    parallel_size: int | None = None
    selection_scope: SelectionScope = "corpus"
    within_ids_count: int | None = None
