"""Start the bundled MCP subprocess and verify its real tool surface and data."""

from __future__ import annotations

import asyncio
import json

from .runner import StirrupMultiTurnRunner

EXPECTED_TOOLS = {
    "maintie__search",
    "maintie__extract",
    "maintie__count",
    "maintie__group_count",
    "maintie__rank",
    "maintie__get_text",
    "maintie__compare",
}


async def check() -> dict:
    provider = StirrupMultiTurnRunner(model="unused")._build_mcp_provider()
    async with provider:
        tools = {tool.name for tool in provider.get_all_tools()}
        if tools != EXPECTED_TOOLS:
            raise RuntimeError(f"Unexpected MCP tools: {sorted(tools)}")
        count_result = await provider.call_tool("maintie", "count", {})
        if '"count": 1076' not in str(count_result):
            raise RuntimeError(f"Unexpected MaintIE count response: {count_result}")
    return {"mcp": "ok", "tools": sorted(tools), "records": 1076}


def main() -> None:
    print(json.dumps(asyncio.run(check()), ensure_ascii=False))


if __name__ == "__main__":
    main()
