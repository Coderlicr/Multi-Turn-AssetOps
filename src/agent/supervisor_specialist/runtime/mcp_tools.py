"""MCP tool adapter for the Supervisor-Specialist system.

Reuses the same stdio MCP client pattern as the plan-execute executor.
Tool names use the format: <server_prefix>.<tool_name> (e.g. iot.history_csv).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from agent.supervisor_specialist.schemas import MCPToolResult, ToolCallRequest

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent

DEFAULT_SERVER_PATHS: dict[str, Path | str] = {
    "iot": "iot-mcp-server",
    "utilities": "utilities-mcp-server",
    "fmsr": "fmsr-mcp-server",
    "tsfm": "tsfm-mcp-server",
    "wo": "wo-mcp-server",
    # vibration excluded: no chiller asset data available
}

_TOOL_CALL_TIMEOUT = 300  # seconds


def _make_stdio_params(server: Path | str):
    from mcp import StdioServerParameters

    if isinstance(server, str):
        return StdioServerParameters(
            command="uv",
            args=["run", server],
            cwd=str(_REPO_ROOT),
        )
    try:
        rel = server.relative_to(_REPO_ROOT)
        module = str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
        return StdioServerParameters(
            command="python",
            args=["-m", module],
            cwd=str(_REPO_ROOT),
        )
    except ValueError:
        return StdioServerParameters(command="python", args=[str(server)])


async def _list_tools_from_server(server_path: Path | str) -> list[dict]:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _make_stdio_params(server_path)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            tools = []
            for t in result.tools:
                schema = t.inputSchema or {}
                tools.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": schema,
                    }
                )
            return tools


async def _call_tool_on_server(
    server_path: Path | str, tool_name: str, args: dict
) -> str:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async def _inner() -> str:
        params = _make_stdio_params(server_path)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return "\n".join(
                    getattr(item, "text", str(item)) for item in result.content
                )

    return await asyncio.wait_for(_inner(), timeout=_TOOL_CALL_TIMEOUT)


class MCPToolClient:
    """Unified MCP tool client routing by server prefix."""

    def __init__(self, server_paths: dict[str, Path | str] | None = None) -> None:
        self._server_paths = server_paths if server_paths is not None else DEFAULT_SERVER_PATHS

    def _parse_tool_name(self, full_tool_name: str) -> tuple[str, str]:
        """Split 'iot.history_csv' into ('iot', 'history_csv')."""
        if "." not in full_tool_name:
            return full_tool_name, full_tool_name
        prefix, _, name = full_tool_name.partition(".")
        return prefix, name

    async def call(self, tool_name: str, args: dict) -> MCPToolResult:
        prefix, bare_name = self._parse_tool_name(tool_name)
        server_path = self._server_paths.get(prefix)
        if server_path is None:
            return MCPToolResult(
                status="failed",
                error=f"No registered MCP server for prefix '{prefix}'. "
                      f"Registered: {list(self._server_paths)}",
            )
        try:
            result = await _call_tool_on_server(server_path, bare_name, args)
            # Treat JSON error payloads as failures
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "error" in parsed:
                    return MCPToolResult(status="failed", error=str(parsed["error"]))
            except (json.JSONDecodeError, ValueError):
                pass
            return MCPToolResult(status="ok", result=result)
        except asyncio.TimeoutError:
            return MCPToolResult(
                status="failed",
                error=f"Tool call '{tool_name}' timed out after {_TOOL_CALL_TIMEOUT}s",
            )
        except Exception as exc:  # noqa: BLE001
            return MCPToolResult(status="failed", error=str(exc) or repr(exc))

    async def list_tools(self, server_name: str) -> list[dict]:
        server_path = self._server_paths.get(server_name)
        if server_path is None:
            return []
        try:
            return await _list_tools_from_server(server_path)
        except Exception as exc:  # noqa: BLE001
            _log.warning("list_tools(%s) failed: %s", server_name, exc)
            return []

    async def get_allowed_tool_schemas(self, allowed_tools: set[str]) -> list[dict]:
        """Return full tool schemas filtered to allowed_tools set.

        Each returned dict has keys: name (prefixed), description, input_schema.
        """
        # Group by server prefix
        prefix_to_tools: dict[str, list[str]] = {}
        for full_name in allowed_tools:
            prefix, bare = self._parse_tool_name(full_name)
            prefix_to_tools.setdefault(prefix, []).append(bare)

        schemas: list[dict] = []
        for prefix, bare_names in prefix_to_tools.items():
            server_tools = await self.list_tools(prefix)
            for t in server_tools:
                if t["name"] in bare_names:
                    schemas.append(
                        {
                            "name": f"{prefix}.{t['name']}",
                            "description": t.get("description", ""),
                            "input_schema": t.get("input_schema", {}),
                        }
                    )
        return schemas

    async def call_many(self, calls: list[ToolCallRequest]) -> list[MCPToolResult]:
        results = []
        for call in calls:
            results.append(await self.call(call.tool_name, call.args))
        return results
