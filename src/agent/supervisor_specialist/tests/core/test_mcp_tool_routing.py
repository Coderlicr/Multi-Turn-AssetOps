"""Tests for MCPToolClient tool routing logic."""

import pytest
from unittest.mock import AsyncMock, patch

from agent.supervisor_specialist.runtime.mcp_tools import MCPToolClient
from agent.supervisor_specialist.schemas import MCPToolResult


@pytest.fixture
def client():
    return MCPToolClient(
        server_paths={
            "iot": "iot-mcp-server",
            "utilities": "utilities-mcp-server",
            "fmsr": "fmsr-mcp-server",
            "tsfm": "tsfm-mcp-server",
            "wo": "wo-mcp-server",
        }
    )


def test_parse_tool_name(client):
    assert client._parse_tool_name("iot.history_csv") == ("iot", "history_csv")
    assert client._parse_tool_name("tsfm.run_integrated_tsad") == ("tsfm", "run_integrated_tsad")
    assert client._parse_tool_name("fmsr.get_failure_modes") == ("fmsr", "get_failure_modes")
    assert client._parse_tool_name("wo.predict_next_work_order") == ("wo", "predict_next_work_order")
    assert client._parse_tool_name("utilities.csv_stats") == ("utilities", "csv_stats")


@pytest.mark.anyio
async def test_call_routes_to_correct_server(client):
    with patch(
        "agent.supervisor_specialist.runtime.mcp_tools._call_tool_on_server",
        new_callable=AsyncMock,
        return_value='{"assets": ["Chiller 6"]}',
    ) as mock_call:
        result = await client.call("iot.assets", {"site_name": "MAIN"})
        assert result.status == "ok"
        call_args = mock_call.call_args
        assert call_args[0][1] == "assets"  # bare tool name passed to server


@pytest.mark.anyio
async def test_call_fails_for_unregistered_server(client):
    result = await client.call("vibration.get_spectrum", {})
    assert result.status == "failed"
    assert "vibration" in result.error


@pytest.mark.anyio
async def test_call_returns_failed_on_error(client):
    with patch(
        "agent.supervisor_specialist.runtime.mcp_tools._call_tool_on_server",
        new_callable=AsyncMock,
        side_effect=Exception("connection refused"),
    ):
        result = await client.call("iot.assets", {})
        assert result.status == "failed"
        assert "connection refused" in result.error


@pytest.mark.anyio
async def test_get_allowed_tool_schemas_filters_correctly(client):
    mock_tools = [
        {"name": "assets", "description": "Get assets", "input_schema": {"properties": {}}},
        {"name": "sensors", "description": "Get sensors", "input_schema": {"properties": {}}},
        {"name": "history", "description": "Get history", "input_schema": {"properties": {}}},
    ]
    with patch.object(client, "list_tools", new_callable=AsyncMock, return_value=mock_tools):
        schemas = await client.get_allowed_tool_schemas({"iot.assets", "iot.sensors"})
        names = {s["name"] for s in schemas}
        assert "iot.assets" in names
        assert "iot.sensors" in names
        assert "iot.history" not in names


@pytest.mark.anyio
async def test_call_detects_json_error_response(client):
    with patch(
        "agent.supervisor_specialist.runtime.mcp_tools._call_tool_on_server",
        new_callable=AsyncMock,
        return_value='{"error": "asset not found"}',
    ):
        result = await client.call("iot.assets", {"site_name": "MISSING"})
        assert result.status == "failed"
        assert "asset not found" in result.error
