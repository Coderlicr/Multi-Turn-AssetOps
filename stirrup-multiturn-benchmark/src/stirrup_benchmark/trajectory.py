"""Convert Stirrup 0.2 message histories into standalone trajectories."""

from __future__ import annotations

import json
from typing import Any, Iterable

from .models import AgentStep, AgentTrajectory, ToolCall


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else str(getattr(block, "text", ""))
            for block in content
        )
    return str(content)


def _assistant_text(message: Any) -> str:
    blocks = getattr(message, "blocks", None)
    if isinstance(blocks, list):
        return "".join(
            block.text
            for block in blocks
            if getattr(block, "kind", None) == "text"
            and isinstance(getattr(block, "text", None), str)
        )
    return _content_text(getattr(message, "content", ""))


def _assistant_tool_calls(message: Any) -> list[Any]:
    blocks = getattr(message, "blocks", None)
    if isinstance(blocks, list):
        return [
            block for block in blocks if getattr(block, "kind", None) == "tool_call"
        ]
    return list(getattr(message, "tool_calls", []) or [])


def _parse_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {"_raw": parsed}
        except json.JSONDecodeError:
            return {"_raw": arguments}
    return {}


def _milliseconds(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    return (end - start) * 1000


def _flatten(history: Iterable[Any]) -> list[Any]:
    flat: list[Any] = []
    for group in history:
        flat.extend(group if isinstance(group, list) else [group])
    return flat


def assistant_message_ids(history: Iterable[Any]) -> set[str]:
    return {
        message_id
        for message in _flatten(history)
        if getattr(message, "role", None) == "assistant"
        and (message_id := (getattr(message, "id", "") or ""))
    }


def messages_for_new_assistants(
    history: Iterable[Any], seen_assistant_ids: set[str]
) -> list[Any]:
    selected: list[Any] = []
    new_tool_call_ids: set[str] = set()
    for message in _flatten(history):
        role = getattr(message, "role", None)
        if role == "assistant":
            message_id = getattr(message, "id", "") or ""
            if message_id and message_id in seen_assistant_ids:
                continue
            selected.append(message)
            new_tool_call_ids.update(
                getattr(call, "tool_call_id", "") or ""
                for call in _assistant_tool_calls(message)
            )
        elif (
            role == "tool"
            and (getattr(message, "tool_call_id", "") or "") in new_tool_call_ids
        ):
            selected.append(message)
    return selected


def active_conversation_context(history: Iterable[Any]) -> list[Any]:
    groups = list(history)
    if not groups:
        return []
    active = groups[-1] if isinstance(groups[-1], list) else [groups[-1]]
    return [message for message in active if getattr(message, "role", None) != "system"]


def build_trajectory(history: Iterable[Any]) -> AgentTrajectory:
    trajectory = AgentTrajectory()
    tool_calls_by_id: dict[str, ToolCall] = {}
    for message in _flatten(history):
        role = getattr(message, "role", None)
        if role == "assistant":
            tool_calls: list[ToolCall] = []
            for raw_call in _assistant_tool_calls(message):
                call = ToolCall(
                    name=getattr(raw_call, "name", "") or "",
                    input=_parse_arguments(getattr(raw_call, "arguments", "")),
                    id=getattr(raw_call, "tool_call_id", "") or "",
                )
                tool_calls.append(call)
                if call.id:
                    tool_calls_by_id[call.id] = call
            usage = getattr(message, "token_usage", None)
            trajectory.turns.append(
                AgentStep(
                    index=len(trajectory.turns),
                    text=_assistant_text(message),
                    tool_calls=tool_calls,
                    input_tokens=int(getattr(usage, "input", 0) or 0),
                    output_tokens=int(getattr(usage, "output", 0) or 0),
                    duration_ms=_milliseconds(
                        getattr(message, "request_start_time", None),
                        getattr(message, "request_end_time", None),
                    ),
                )
            )
        elif role == "tool":
            call = tool_calls_by_id.get(getattr(message, "tool_call_id", "") or "")
            if call is not None:
                call.output = _content_text(getattr(message, "content", ""))
                call.duration_ms = _milliseconds(
                    getattr(message, "tool_start_time", None),
                    getattr(message, "tool_end_time", None),
                )
    return trajectory


def final_answer(history: Iterable[Any], finish_params: Any) -> str:
    answer = getattr(finish_params, "answer", None)
    if isinstance(answer, str) and answer.strip():
        return answer.strip()
    messages = _flatten(history)
    for message in reversed(messages):
        if getattr(message, "role", None) != "assistant":
            continue
        if any(
            getattr(call, "name", None) == "finish"
            for call in _assistant_tool_calls(message)
        ):
            text = _assistant_text(message).strip()
            if text:
                return text
    reason = getattr(finish_params, "reason", None)
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    for message in reversed(messages):
        if getattr(message, "role", None) == "assistant":
            text = _assistant_text(message).strip()
            if text:
                return text
    return ""
