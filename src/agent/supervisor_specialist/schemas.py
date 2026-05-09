"""Pydantic models and TypedDict state for the Supervisor-Specialist system."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


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


class DialogTurnRecord(BaseModel):
    """A compact record of one completed supervisor-specialist turn."""

    turn_index: int
    user_message: str
    assistant_answer: str
    artifact_ids: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    root_cause: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)


class ConversationMemory(BaseModel):
    """Structured multi-turn memory for the current CLI session."""

    active_site: str = "MAIN"
    active_asset_ids: list[str] = Field(default_factory=list)
    active_time_window: TimeWindow = Field(default_factory=TimeWindow)
    focus_metrics: list[str] = Field(default_factory=list)
    rolling_summary: str = ""
    recent_turns: list[DialogTurnRecord] = Field(default_factory=list)
    active_artifact_ids: list[str] = Field(default_factory=list)
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


# ── Specialist communication models ──────────────────────────────────────────


class ToolCallRequest(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolPlan(BaseModel):
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)


class ToolCallResult(BaseModel):
    order: int
    tool_name: str
    args: dict[str, Any]
    status: Literal["ok", "failed"]
    result: Any | None = None
    error: str | None = None


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
