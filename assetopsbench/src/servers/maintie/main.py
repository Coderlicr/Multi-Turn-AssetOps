"""MaintIE MCP server over the official manually corrected gold release."""

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP(
    "maintie",
    instructions=(
        "Query 1,076 work-order texts annotated with the MaintIE ontology. "
        "Reuse wo_ids with within_ids across turns. Use patient_of_activity='Replace' "
        "when ranking replaced components. The corpus has no date, shift, cost, site, "
        "or reliable asset identity fields."
    ),
)

for _tool in (
    tools.search,
    tools.extract,
    tools.count,
    tools.group_count,
    tools.rank,
    tools.get_text,
    tools.compare,
):
    mcp.tool()(_tool)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
