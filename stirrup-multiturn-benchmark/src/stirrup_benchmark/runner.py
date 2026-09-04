"""Persistent-session Stirrup runner for true multi-user-turn conversations."""

from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

from .finish_tool import BENCHMARK_FINISH_TOOL
from .models import (
    AgentResult,
    ConversationResult,
    ConversationTrajectory,
    UserTurnRecord,
)
from .trajectory import (
    active_conversation_context,
    assistant_message_ids,
    build_trajectory,
    final_answer,
    messages_for_new_assistants,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_WINDOW_TOKENS = 100_000
CONTEXT_SUMMARIZATION_CUTOFF = 0.75
ROUTERS = {
    "litellm_proxy/": ("LITELLM_BASE_URL", "LITELLM_API_KEY"),
    "tokenrouter/": ("TOKENROUTER_BASE_URL", "TOKENROUTER_API_KEY"),
}
SYSTEM_PROMPT = """\
You are an industrial maintenance analysis assistant. Use the MaintIE MCP tools
as the authoritative source for the work-order corpus. Preserve entities,
constraints, tool results, and corrections across user turns. Answer each
current user request concisely; never anticipate or answer future turns.
"""


class StirrupMultiTurnRunner:
    def __init__(
        self,
        *,
        model: str,
        max_turns: int = 12,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.max_turns = max_turns
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort

    def _build_client(self):
        client_kwargs = (
            {"temperature": self.temperature} if self.temperature is not None else None
        )
        for prefix, (base_env, key_env) in ROUTERS.items():
            if self.model.startswith(prefix):
                base_url = os.environ.get(base_env)
                api_key = os.environ.get(key_env)
                if not base_url or not api_key:
                    raise ValueError(
                        f"{base_env} and {key_env} are required for {prefix} models"
                    )
                from stirrup.clients.chat_completions_client import (
                    ChatCompletionsClient,
                )

                return ChatCompletionsClient(
                    model=self.model[len(prefix) :],
                    context_window_tokens=CONTEXT_WINDOW_TOKENS,
                    base_url=base_url.rstrip("/"),
                    api_key=api_key,
                    reasoning_effort=self.reasoning_effort,
                    kwargs=client_kwargs,
                )
        from stirrup.clients.litellm_client import LiteLLMClient

        return LiteLLMClient(
            model=self.model,
            context_window_tokens=CONTEXT_WINDOW_TOKENS,
            reasoning_effort=self.reasoning_effort,
            kwargs=client_kwargs,
        )

    def _build_mcp_provider(self):
        from stirrup.tools.mcp import MCPConfig, MCPToolProvider

        config = MCPConfig.model_validate(
            {
                "mcpServers": {
                    "maintie": {
                        "command": sys.executable,
                        "args": ["-m", "stirrup_benchmark.maintie.server"],
                        "cwd": str(PROJECT_ROOT),
                    }
                }
            }
        )
        return MCPToolProvider(config=config)

    def _build_agent(self):
        from stirrup import Agent

        return Agent(
            client=self._build_client(),
            name="stirrup-multiturn-benchmark",
            system_prompt=SYSTEM_PROMPT,
            tools=[self._build_mcp_provider()],
            finish_tool=BENCHMARK_FINISH_TOOL,
            max_turns=self.max_turns,
            context_summarization_cutoff=CONTEXT_SUMMARIZATION_CUTOFF,
        )

    async def run_single(self, user_message: str) -> AgentResult:
        agent = self._build_agent()
        started_at = dt.datetime.now(dt.UTC).isoformat()
        async with agent.session() as session:
            finish_params, history, _metadata = await session.run(user_message)
        trajectory = build_trajectory(history)
        trajectory.started_at = started_at
        return AgentResult(
            answer=final_answer(history, finish_params),
            trajectory=trajectory,
        )

    async def run_conversation(self, user_messages: list[str]) -> ConversationResult:
        if len(user_messages) < 2:
            raise ValueError("A multi-turn conversation requires at least two messages")
        if any(
            not isinstance(message, str) or not message.strip()
            for message in user_messages
        ):
            raise ValueError("Every user message must be a non-empty string")

        from stirrup.core.models import AssistantMessage, UserMessage

        started_at = dt.datetime.now(dt.UTC).isoformat()
        agent = self._build_agent()
        conversation_context: list = []
        seen_assistant_ids: set[str] = set()
        user_turns: list[UserTurnRecord] = []

        async with agent.session() as session:
            for index, message in enumerate(user_messages):
                turn_started = time.perf_counter()
                turn_started_at = dt.datetime.now(dt.UTC).isoformat()
                prior_agent_steps = sum(
                    isinstance(item, AssistantMessage) for item in conversation_context
                )
                # Stirrup 0.2 counts supplied historical AssistantMessages toward
                # max_turns, so retain a fresh per-user-turn step budget.
                session._max_turns = prior_agent_steps + self.max_turns
                finish_params, history, _metadata = await session.run(
                    [*conversation_context, UserMessage(content=message)]
                )
                answer = final_answer(history, finish_params)
                current_messages = messages_for_new_assistants(
                    history, seen_assistant_ids
                )
                step_trajectory = build_trajectory([current_messages])
                step_trajectory.started_at = turn_started_at
                user_turns.append(
                    UserTurnRecord(
                        index=index,
                        user_message=message,
                        answer=answer,
                        trajectory=step_trajectory,
                        started_at=turn_started_at,
                        duration_ms=(time.perf_counter() - turn_started) * 1000,
                    )
                )
                seen_assistant_ids.update(assistant_message_ids(history))
                conversation_context = active_conversation_context(history)

        trajectory = ConversationTrajectory(
            user_turns=user_turns,
            started_at=started_at,
        )
        return ConversationResult(
            user_messages=list(user_messages),
            answers=[turn.answer for turn in user_turns],
            trajectory=trajectory,
        )
