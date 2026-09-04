from stirrup.core.models import (
    AssistantMessage,
    SystemMessage,
    TokenUsage,
    ToolCall as StirrupToolCall,
    ToolMessage,
    UserMessage,
)

from stirrup_benchmark.trajectory import (
    active_conversation_context,
    assistant_message_ids,
    build_trajectory,
    messages_for_new_assistants,
)


def test_history_helpers_separate_new_agent_steps_and_keep_live_context():
    first_call = StirrupToolCall(
        name="maintie__count", arguments="{}", tool_call_id="tool-1"
    )
    first = AssistantMessage(blocks=[first_call], token_usage=TokenUsage())
    tool = ToolMessage(
        content='{"count":347}',
        tool_call_id="tool-1",
        name="maintie__count",
        success=True,
    )
    second = AssistantMessage(blocks=[], token_usage=TokenUsage())
    history = [
        [
            SystemMessage(content="system"),
            UserMessage(content="first"),
            first,
            tool,
            second,
        ]
    ]

    assert messages_for_new_assistants(history, {first.id}) == [second]
    assert assistant_message_ids(history) == {first.id, second.id}
    context = active_conversation_context(history)
    assert context[0].role == "user"
    assert all(message.role != "system" for message in context)

    trajectory = build_trajectory(history)
    assert trajectory.all_tool_calls[0].name == "maintie__count"
    assert trajectory.all_tool_calls[0].output == '{"count":347}'
