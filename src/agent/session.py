"""Minimal session state for multi-turn plan-execute workflows."""

from __future__ import annotations

from dataclasses import dataclass, field

from .plan_execute.models import StepResult


@dataclass
class TurnRecord:
    """A compact record of one completed dialog turn."""

    question: str
    answer: str


@dataclass
class SessionState:
    """Conversation state limited to recent turns."""

    recent_turns: list[TurnRecord] = field(default_factory=list)
    max_recent_turns: int = 10

    def build_question(self, question: str) -> str:
        """Append recent turn history to the current user question."""
        context = self.render_context()
        if not context:
            return question
        return f"{context}\n\nCurrent user question:\n{question}"

    def render_context(self) -> str:
        """Render remembered turns as plain text for LLM prompts."""
        if not self.recent_turns:
            return ""

        turn_lines = ["Recent conversation:"]
        for turn in self.recent_turns:
            turn_lines.append(f"User: {turn.question}")
            turn_lines.append(f"Assistant: {turn.answer}")
        return "\n".join(turn_lines)

    def record_turn(
        self,
        question: str,
        answer: str,
        history: list[StepResult],
    ) -> None:
        """Append the latest turn and discard older turns beyond the limit."""
        del history
        self.recent_turns.append(TurnRecord(question=question, answer=answer))
        if len(self.recent_turns) > self.max_recent_turns:
            self.recent_turns = self.recent_turns[-self.max_recent_turns :]
