"""Result and trajectory models local to the Stirrup runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """One tool invocation emitted by the model."""

    name: str
    input: dict
    id: str = ""
    output: object = None
    duration_ms: float | None = None


@dataclass
class TurnRecord:
    """One assistant turn and any tools called during it."""

    index: int
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float | None = None


@dataclass
class Trajectory:
    """Full Stirrup execution trace."""

    turns: list[TurnRecord] = field(default_factory=list)
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
class AgentResult:
    """Final answer plus the Stirrup execution trace."""

    question: str
    answer: str
    trajectory: Any
