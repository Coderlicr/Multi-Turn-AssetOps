"""Shared utilities for the Supervisor-Specialist system."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

_PATH_RE = re.compile(r"(/[^\s'\"),]+(?:\.csv|\.json|\.pkl|\.txt|/))")


async def call_llm(llm, prompt: str, temperature: float = 0.0) -> str:
    """Async wrapper around the synchronous LiteLLMBackend.generate."""
    return await asyncio.to_thread(llm.generate, prompt, temperature)


def parse_json_from_llm(raw: str) -> dict | None:
    """Extract a JSON object from an LLM response, handling markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).lstrip("json").strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            result = json.loads(text[start:end])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    _log.debug("parse_json_from_llm: no JSON object found in: %r…", raw[:120])
    return None


def format_tool_schemas_for_prompt(tool_schemas: list[dict]) -> str:
    """Format a list of tool schema dicts into a human-readable string for LLM prompts."""
    lines = []
    for t in tool_schemas:
        name = t.get("name", "")
        description = t.get("description", "")
        schema = t.get("input_schema", {})
        props = schema.get("properties", {})
        required_set = set(schema.get("required", []))
        params = ", ".join(
            f"{k}: {v.get('type', 'any')}{'?' if k not in required_set else ''}"
            for k, v in props.items()
        )
        lines.append(f"- {name}({params}): {description}")
    return "\n".join(lines) if lines else "(no tools available)"


def format_artifacts_summary(artifacts: list) -> str:
    """Format a list of ArtifactEnvelope objects into a summary string."""
    if not artifacts:
        return "(none)"
    lines = []
    for a in artifacts:
        # Extract all file paths from payload so they are always visible to downstream specialists
        payload = a.payload or {}
        file_paths: list[str] = []
        for v in payload.values():
            if isinstance(v, str) and ("/" in v or v.endswith((".csv", ".json"))):
                file_paths.append(v)
            elif isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, str) and ("/" in vv or vv.endswith((".csv", ".json"))):
                        file_paths.append(vv)

        payload_str = json.dumps(payload, ensure_ascii=False)
        payload_preview = payload_str[:2000]
        if len(payload_str) > 2000:
            payload_preview += "... [truncated]"

        entry = (
            f"[{a.artifact_id}] type={a.artifact_type} producer={a.producer} "
            f"assets={a.asset_ids}\n  source_tools: {getattr(a, 'source_tools', [])}"
        )
        summary = getattr(a, "summary", "") or ""
        if summary:
            entry += f"\n  summary: {summary}"
        entry += f"\n  payload: {payload_preview}"
        if file_paths:
            entry += f"\n  file_paths: {file_paths}"
        lines.append(entry)
    return "\n".join(lines)


def extract_file_paths(value: Any) -> list[str]:
    """Return file-like paths from nested JSON-ish values or plain text."""
    paths: list[str] = []

    def _walk(item: Any) -> None:
        if isinstance(item, str):
            paths.extend(_PATH_RE.findall(item))
            if item.startswith("/") and " " not in item and item not in paths:
                paths.append(item)
        elif isinstance(item, dict):
            for v in item.values():
                _walk(v)
        elif isinstance(item, list):
            for v in item:
                _walk(v)

    _walk(value)
    # Preserve order while de-duplicating.
    return list(dict.fromkeys(paths))


def format_conversation_memory(memory: object | None) -> str:
    """Format ConversationMemory compactly for LLM prompts."""
    if memory is None:
        return "(none)"

    active_site = getattr(memory, "active_site", "MAIN")
    active_asset_ids = getattr(memory, "active_asset_ids", [])
    active_time_window = getattr(memory, "active_time_window", None)
    focus_metrics = getattr(memory, "focus_metrics", [])
    active_artifact_ids = getattr(memory, "active_artifact_ids", [])
    rolling_summary = getattr(memory, "rolling_summary", "")
    recent_turns = getattr(memory, "recent_turns", [])

    lines = [
        f"Active site: {active_site}",
        f"Active assets: {active_asset_ids or '(none)'}",
        f"Active time window: {active_time_window.model_dump() if active_time_window else '(none)'}",
        f"Focus metrics: {focus_metrics or '(none)'}",
        f"Reusable artifact IDs: {active_artifact_ids or '(none)'}",
    ]
    if rolling_summary:
        lines.append(f"Rolling summary: {rolling_summary[:1200]}")

    if recent_turns:
        lines.append("Recent turns:")
        for turn in recent_turns[-5:]:
            user_msg = getattr(turn, "user_message", "")
            answer = getattr(turn, "assistant_answer", "")
            artifact_ids = getattr(turn, "artifact_ids", [])
            root_cause = getattr(turn, "root_cause", None)
            actions = getattr(turn, "recommended_actions", [])
            tool_calls = getattr(turn, "tool_calls", [])
            tool_names = [
                f"{tc.tool_name}:{tc.status}"
                for tc in tool_calls[-6:]
                if hasattr(tc, "tool_name")
            ]
            lines.append(
                f"- Turn {getattr(turn, 'turn_index', '?')}: "
                f"user={user_msg[:240]!r}; answer={answer[:360]!r}; "
                f"artifacts={artifact_ids}; tools={tool_names}; "
                f"root_cause={root_cause or '(none)'}; actions={actions or '(none)'}"
            )

    return "\n".join(lines)


def format_tool_results_for_prompt(tool_results: list) -> str:
    """Format ToolCallResult list for the artifact-generation prompt.

    Uses a higher truncation limit than the old plan prompt so that file paths
    and other key values (e.g. csv_path from iot.history_csv) are not cut off.
    """
    if not tool_results:
        return "(no tool calls made)"
    lines = []
    for r in tool_results:
        batch_suffix = ""
        parallel_group_id = getattr(r, "parallel_group_id", None)
        if parallel_group_id is not None:
            batch_suffix = (
                f" [parallel_group={parallel_group_id} "
                f"{getattr(r, 'parallel_index', None)}/{getattr(r, 'parallel_size', None)}]"
            )
        if r.status == "ok":
            result_str = str(r.result or "")
            result_preview = result_str[:2000]
            if len(result_str) > 2000:
                result_preview += "... [truncated]"
            lines.append(f"[{r.order}]{batch_suffix} {r.tool_name} -> OK\n{result_preview}")
        else:
            lines.append(f"[{r.order}]{batch_suffix} {r.tool_name} -> FAILED: {r.error}")
    return "\n\n".join(lines)
