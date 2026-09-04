import json

import pytest
from stirrup.core.models import (
    AssistantMessage,
    SystemMessage,
    TokenUsage,
    ToolCall,
    ToolMessage,
    UserMessage,
)

from stirrup_benchmark.finish_tool import BenchmarkFinishParams
from stirrup_benchmark.runner import StirrupMultiTurnRunner


def test_runner_builds_stirrup_mcp_provider():
    runner = StirrupMultiTurnRunner(model="unused")

    provider = runner._build_mcp_provider()

    assert provider is not None


@pytest.mark.anyio
async def test_conversation_uses_one_session_and_carries_prior_context(monkeypatch):
    calls: list[list] = []
    lifecycle = {"enter": 0, "exit": 0}

    class FakeSession:
        _max_turns = 4

        async def __aenter__(self):
            lifecycle["enter"] += 1
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            lifecycle["exit"] += 1

        async def run(self, messages):
            calls.append(messages)
            prompt = messages[-1].content
            answer = f"answer:{prompt}"
            finish_call = ToolCall(
                name="finish",
                arguments=json.dumps({"answer": answer}),
                tool_call_id=f"finish-{len(calls)}",
            )
            assistant = AssistantMessage(
                blocks=[finish_call],
                token_usage=TokenUsage(input=10, answer=2),
            )
            tool = ToolMessage(
                content=answer,
                tool_call_id=finish_call.tool_call_id,
                name="finish",
                success=True,
            )
            return (
                BenchmarkFinishParams(answer=answer),
                [[SystemMessage(content="system"), *messages, assistant, tool]],
                {},
            )

    class FakeAgent:
        def __init__(self):
            self._session = FakeSession()

        def session(self):
            return self._session

    runner = StirrupMultiTurnRunner(model="unused", max_turns=4)
    monkeypatch.setattr(runner, "_build_agent", FakeAgent)

    result = await runner.run_conversation(["first", "use that"])

    assert lifecycle == {"enter": 1, "exit": 1}
    assert result.answers == ["answer:first", "answer:use that"]
    assert len(result.trajectory.user_turns) == 2
    assert all(len(turn.trajectory.turns) == 1 for turn in result.trajectory.user_turns)
    assert calls[0][-1].content == "first"
    assert any(
        isinstance(message, UserMessage) and message.content == "first"
        for message in calls[1]
    )
    assert calls[1][-1].content == "use that"
