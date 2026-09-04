"""MCP entry point for deterministic MaintIE queries."""

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP(
    "maintie",
    instructions=(
        "Query 1,076 work-order texts annotated with the MaintIE ontology. "
        "Reuse wo_ids with within_ids across turns. Use "
        "patient_of_activity='Replace' for replaced-component rankings."
    ),
)

for tool in (
    tools.search,
    tools.extract,
    tools.count,
    tools.group_count,
    tools.rank,
    tools.get_text,
    tools.compare,
):
    mcp.tool()(tool)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
