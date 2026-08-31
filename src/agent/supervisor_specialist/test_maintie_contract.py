from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.supervisor_specialist._utils import format_tool_schemas_for_prompt
from agent.supervisor_specialist.runtime.mcp_tools import (
    MCPToolClient,
    MCPToolExecutionError,
    _content_from_tool_result,
)
from servers.maintie.tools import QueryFilter


def test_full_nested_schema_is_rendered_for_specialist():
    schema = {
        "type": "object",
        "properties": {
            "filter": {"$ref": "#/$defs/QueryFilter"},
        },
        "$defs": {
            "QueryFilter": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "object_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "has_fault": {"type": ["boolean", "null"]},
                },
            }
        },
    }

    rendered = format_tool_schemas_for_prompt(
        [{"name": "maintie.search", "description": "search", "input_schema": schema}]
    )

    assert '"$defs"' in rendered
    assert '"$ref": "#/$defs/QueryFilter"' in rendered
    assert '"object_terms"' in rendered
    assert '"additionalProperties": false' in rendered


@pytest.mark.parametrize("unknown", ["site", "object_class", "time_window"])
def test_query_filter_rejects_unknown_fields(unknown):
    with pytest.raises(ValidationError):
        QueryFilter.model_validate({unknown: "ignored-before-fix"})


def test_mcp_is_error_is_not_treated_as_success():
    result = SimpleNamespace(
        isError=True,
        content=[SimpleNamespace(text="filter.site: Extra inputs are not permitted")],
    )

    with pytest.raises(MCPToolExecutionError, match="Extra inputs"):
        _content_from_tool_result(result)


def test_mcp_success_content_is_returned():
    result = SimpleNamespace(
        isError=False,
        content=[SimpleNamespace(text='{"count": 3}')],
    )

    assert _content_from_tool_result(result) == '{"count": 3}'


@pytest.mark.anyio
async def test_real_maintie_mcp_rejects_unknown_filter_field():
    client = MCPToolClient({"maintie": "maintie-mcp-server"})

    result = await client.call("maintie.search", {"filter": {"site": "MAIN"}})

    assert result.status == "failed"
    assert "Extra inputs are not permitted" in result.error


@pytest.mark.anyio
async def test_real_maintie_schema_keeps_nested_filter_contract():
    client = MCPToolClient({"maintie": "maintie-mcp-server"})

    schemas = await client.get_allowed_tool_schemas({"maintie.search"})
    rendered = format_tool_schemas_for_prompt(schemas)

    assert '"object_terms"' in rendered
    assert '"has_fault"' in rendered
    assert '"additionalProperties": false' in rendered
