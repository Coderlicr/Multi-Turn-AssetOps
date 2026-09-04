"""Real-tool OPR policy for the WTB-50 benchmark.

The advisor-provided gold file uses compact reasoning sketches such as
``filter>group>rank``, ``index``, and ``merge``.  Those are useful descriptions
of the intended computation, but they are not MCP tool calls.  This module keeps
those sketches for auditability and supplies the actual external-tool plans used
by Optimal Path Rate (OPR).

Only the seven tools exposed by the MaintIE MCP server may appear here.  Local
operations over an already returned result (sorting, indexing, merging,
comparison, humanisation, or composition) deliberately use an empty plan.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

ToolPlan = list[list[str]]

ALLOWED_TOOLS = frozenset(
    {"search", "extract", "count", "group_count", "rank", "get_text", "compare"}
)

# One preferred real MCP path per turn.  Outer list = turns; each turn is a
# sequence of parallel groups.  For example [["count", "count"]] means two
# independent count calls in one parallel group, while [["search"], ["extract"]]
# means search first and then extract.
PREFERRED_REAL_TOOL_PLANS: dict[str, list[ToolPlan]] = {
    "WTB01": [[["count", "count"]], [["rank"]], [], [["rank"]]],
    "WTB02": [[["search"]], [], [["count", "count"]], [["rank"]]],
    "WTB03": [[["compare"]], [], [], [["compare"]]],
    "WTB04": [[["rank"]], [], [["rank"]]],
    "WTB05": [[["compare"]], [["group_count"]], [], []],
    "WTB06": [[["rank"]], [], [["compare"]], []],
    "WTB07": [[["search"]], [], [["extract"]]],
    "WTB08": [[["rank"]], [], [["rank"]]],
    "WTB09": [[], [], [["rank"]]],
    "WTB10": [[["count"]], [["count"]], [["count"]]],
    "WTB11": [[], [], [["rank"]], [["rank"]]],
    "WTB12": [[["rank"]], [["count", "rank"]], []],
    "WTB13": [[["compare"]], [["rank"]]],
    "WTB14": [[["rank"]], [], [["count"]], [["count"]]],
    "WTB15": [[["search"]], [["search"]], [["search"]]],
    "WTB16": [[["count"]], [["count"]], [["count"]]],
    "WTB17": [[["compare"]], [], [["compare"]], []],
    "WTB18": [[["search"]], [["compare"]]],
    "WTB19": [[["group_count"]], [], []],
    "WTB20": [[], [["rank"]], [], []],
    "WTB21": [[["rank"]], [["rank"]], []],
    "WTB22": [[["compare"]], []],
    "WTB23": [[["rank"]], [], [["count"]]],
    "WTB24": [[["count"]], [["count"]], []],
    "WTB25": [[], [["rank"]], [["rank"]]],
    "WTB26": [[["search"]], [["search"]], []],
    "WTB27": [[["search"]], [], [["search"]], [["group_count"]]],
    "WTB28": [[["compare"]], []],
    "WTB29": [[["rank"]], [], [["search"], ["extract"]]],
    "WTB30": [[["compare"]], [["compare"]]],
    "WTB31": [[["search"]], [["search"]], [["search"]]],
    "WTB32": [[["compare"]], []],
    "WTB33": [[], [["rank"]], [["rank"]]],
    "WTB34": [[["rank"]], [], [["group_count"]]],
    "WTB35": [[["rank", "rank"]], [], [["group_count"]]],
    "WTB36": [[["search"]], [], [["rank"]]],
    "WTB37": [[["compare"]], [["compare"]], []],
    "WTB38": [[], [], [["count"]]],
    "WTB39": [[["compare"]], [["compare"]], []],
    "WTB40": [[["rank"]], [["rank"]], [["count"]]],
    "WTB41": [[["group_count", "group_count"]], []],
    "WTB42": [[], [], []],
    "WTB43": [[["rank"]], [["rank"]], [["rank"]]],
    "WTB44": [[["count"]], [["count"]], []],
    "WTB45": [[["rank"]], [["rank"]]],
    "WTB46": [[["compare"]], []],
    "WTB47": [[["rank"]], [], [["count"]], [["rank"]]],
    "WTB48": [[], [], [["rank"]]],
    "WTB49": [[["compare"]], [], []],
    "WTB50": [[], [], [["rank"], ["compare"]]],
}

# Alternative paths that are equally valid with the current general-purpose
# MaintIE tools.  Keys use a zero-based turn index.
ACCEPTED_ALTERNATIVES: dict[tuple[str, int], list[ToolPlan]] = {
    ("WTB01", 0): [[["group_count"]], [["compare"]]],
    ("WTB02", 2): [[["group_count"]], [["compare"]]],
    ("WTB03", 0): [[["search"], ["extract"]]],
    ("WTB05", 0): [[["search"], ["count"]]],
    ("WTB12", 1): [[["compare"]]],
    ("WTB13", 0): [[["count", "count"]]],
    ("WTB17", 0): [[["count", "count"]]],
    ("WTB17", 2): [[["count", "count"]]],
    ("WTB22", 0): [[["count", "count", "count", "rank"]]],
    ("WTB28", 0): [[["group_count", "group_count"]]],
    ("WTB30", 0): [[["count", "count"]]],
    ("WTB30", 1): [[["count", "count"]]],
    ("WTB32", 0): [[["count", "count"]]],
    ("WTB37", 0): [[["count", "count"]]],
    ("WTB39", 0): [[["count", "count", "count", "count"]]],
    ("WTB41", 0): [[["compare"]]],
    ("WTB46", 0): [[["group_count", "group_count", "group_count"]]],
    ("WTB49", 0): [[["rank", "count"]]],
}


def _validate_plan(plan: ToolPlan) -> None:
    for group in plan:
        for tool in group:
            if tool not in ALLOWED_TOOLS:
                raise ValueError(f"Non-MaintIE tool in OPR policy: {tool!r}")


def validate_policy(gold: dict[str, list[dict[str, Any]]]) -> None:
    """Raise if the policy is incomplete or contains a non-real tool."""
    if set(PREFERRED_REAL_TOOL_PLANS) != set(gold):
        missing = sorted(set(gold) - set(PREFERRED_REAL_TOOL_PLANS))
        extra = sorted(set(PREFERRED_REAL_TOOL_PLANS) - set(gold))
        raise ValueError(f"WTB tool policy mismatch; missing={missing}, extra={extra}")

    for scenario_id, turns in gold.items():
        preferred = PREFERRED_REAL_TOOL_PLANS[scenario_id]
        if len(preferred) != len(turns):
            raise ValueError(
                f"{scenario_id}: policy has {len(preferred)} turns, gold has {len(turns)}"
            )
        for plan in preferred:
            _validate_plan(plan)
    for (scenario_id, turn_index), plans in ACCEPTED_ALTERNATIVES.items():
        if scenario_id not in gold or not 0 <= turn_index < len(gold[scenario_id]):
            raise ValueError(
                f"Alternative OPR path targets unknown turn: {scenario_id}[{turn_index}]"
            )
        for plan in plans:
            _validate_plan(plan)


def apply_real_tool_policy(
    gold: dict[str, list[dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    """Return gold with reasoning sketches separated from real OPR paths."""
    validate_policy(gold)
    revised = deepcopy(gold)
    for scenario_id, turns in revised.items():
        for turn_index, turn in enumerate(turns):
            preferred = deepcopy(PREFERRED_REAL_TOOL_PLANS[scenario_id][turn_index])
            legacy = turn.get("reasoning_plan", turn.get("tools", []))
            alternatives = deepcopy(
                ACCEPTED_ALTERNATIVES.get((scenario_id, turn_index), [])
            )
            turn["reasoning_plan"] = legacy
            turn["tools"] = preferred
            turn["accepted_tool_plans"] = [preferred, *alternatives]
    return revised
