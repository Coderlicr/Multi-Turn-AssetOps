"""Keep Stirrup's synthetic continuation messages scoped to task completion."""

from __future__ import annotations

import re
from typing import Any

from stirrup.core.models import (
    AssistantMessage,
    ChatMessage,
    Tool,
    TurnWarningMessage,
    UserMessage,
)

_STIRRUP_CONTINUE_MESSAGE = "Please continue the task"

INCOMPLETE_RESPONSE_PROMPT = """\
Your previous response did not complete the task through a finish tool.
Re-evaluate only the original user request. If that request is already fully
satisfied, call `finish` now as the only tool call and put the complete
user-facing response in `finish.answer`. Otherwise, perform only the additional
work strictly required to satisfy the original request. Do not broaden the
scope or demonstrate optional capabilities.
"""

_TURN_COUNT_RE = re.compile(r"You have (\d+) turns? remaining")


def _turn_warning_prompt(content: str) -> str:
    """Return a completion-oriented replacement for Stirrup's turn warning."""
    match = _TURN_COUNT_RE.search(content)
    remaining = match.group(1) if match else "a limited number of"
    return (
        f"You have {remaining} turns remaining. Re-evaluate only the original "
        "user request. If it is already complete, call `finish` now as the only "
        "tool call and put the complete user-facing response in `finish.answer`. "
        "Otherwise, perform only the work strictly required to complete it and "
        "reserve a final turn for `finish`. Do not broaden the scope."
    )


def rewrite_completion_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Rewrite framework-generated nudges before they are sent to the model.

    Stirrup 0.2.0 hard-codes ``Please continue the task`` after a tool-free
    assistant response. Models can interpret that synthetic user message as a
    request to expand an already-complete task. The dependency currently has no
    public hook for replacing it, so this adapter changes only the model-facing
    copy of those framework messages and leaves genuine user prompts untouched.
    """
    rewritten: list[ChatMessage] = []
    for index, message in enumerate(messages):
        replacement: str | None = None

        if isinstance(message, TurnWarningMessage) and isinstance(message.content, str):
            replacement = _turn_warning_prompt(message.content)
        elif (
            type(message) is UserMessage
            and message.content == _STIRRUP_CONTINUE_MESSAGE
            and index > 0
            and isinstance(messages[index - 1], AssistantMessage)
        ):
            replacement = INCOMPLETE_RESPONSE_PROMPT

        rewritten.append(
            message.model_copy(update={"content": replacement})
            if replacement is not None
            else message
        )

    return rewritten


class CompletionProtocolClient:
    """LLM-client adapter that corrects Stirrup's synthetic completion nudges."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def delegate(self) -> Any:
        return self._client

    @property
    def model_slug(self) -> str:
        return self._client.model_slug

    @property
    def context_window_tokens(self) -> int:
        return self._client.context_window_tokens

    async def generate(
        self,
        messages: list[ChatMessage],
        tools: dict[str, Tool],
    ) -> AssistantMessage:
        return await self._client.generate(
            rewrite_completion_messages(messages),
            tools,
        )
