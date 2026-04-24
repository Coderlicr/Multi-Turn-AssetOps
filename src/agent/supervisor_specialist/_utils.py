"""Shared utilities for the Supervisor-Specialist system."""

from __future__ import annotations

import asyncio
import json
import logging

_log = logging.getLogger(__name__)


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
            f"assets={a.asset_ids}\n  payload: {payload_preview}"
        )
        if file_paths:
            entry += f"\n  file_paths: {file_paths}"
        lines.append(entry)
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
        if r.status == "ok":
            result_str = str(r.result or "")
            result_preview = result_str[:2000]
            if len(result_str) > 2000:
                result_preview += "... [truncated]"
            lines.append(f"[{r.order}] {r.tool_name} -> OK\n{result_preview}")
        else:
            lines.append(f"[{r.order}] {r.tool_name} -> FAILED: {r.error}")
    return "\n\n".join(lines)
