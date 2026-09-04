"""Serializable execution models with separate user-turn and agent-step levels."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    id: str = ""
    output: object = None
    duration_ms: float | None = None


@dataclass
class AgentStep:
    index: int
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float | None = None


@dataclass
class AgentTrajectory:
    turns: list[AgentStep] = field(default_factory=list)
    started_at: str | None = None

    @property
    def total_input_tokens(self) -> int:
        return sum(turn.input_tokens for turn in self.turns)

    @property
    def total_output_tokens(self) -> int:
        return sum(turn.output_tokens for turn in self.turns)

    @property
    def all_tool_calls(self) -> list[ToolCall]:
        return [call for turn in self.turns for call in turn.tool_calls]


@dataclass
class UserTurnRecord:
    index: int
    user_message: str
    answer: str
    trajectory: AgentTrajectory
    started_at: str | None = None
    duration_ms: float | None = None


@dataclass
class ConversationTrajectory:
    user_turns: list[UserTurnRecord] = field(default_factory=list)
    started_at: str | None = None

    @property
    def total_input_tokens(self) -> int:
        return sum(turn.trajectory.total_input_tokens for turn in self.user_turns)

    @property
    def total_output_tokens(self) -> int:
        return sum(turn.trajectory.total_output_tokens for turn in self.user_turns)

    @property
    def all_tool_calls(self) -> list[ToolCall]:
        return [
            call for turn in self.user_turns for call in turn.trajectory.all_tool_calls
        ]

    @property
    def agent_step_count(self) -> int:
        return sum(len(turn.trajectory.turns) for turn in self.user_turns)


@dataclass
class AgentResult:
    answer: str
    trajectory: AgentTrajectory


@dataclass
class ConversationResult:
    user_messages: list[str]
    answers: list[str]
    trajectory: ConversationTrajectory
