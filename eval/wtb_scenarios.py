"""Load the 50 advisor-provided WildToolBench-style dialogs.

The Markdown file is the dialogue source and wtb_ground_truth.json is the fixed
evaluation target.  Gold data is loaded only by the evaluator, never passed to
an agent process.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

if __package__:
    from .wtb_tool_policy import apply_real_tool_policy
else:  # Support ``python eval/wtb_scenarios.py`` and sibling script imports.
    from wtb_tool_policy import apply_real_tool_policy

REPO_ROOT = Path(__file__).resolve().parent.parent
WTB_ROOT = REPO_ROOT / "50 scenario"
SCENARIO_FILE = WTB_ROOT / "MaintIE_50_WildToolBench_Scenarios.md"
METADATA_FILE = WTB_ROOT / "MaintIE_50_WildToolBench_Scenarios.csv"
GOLD_FILE = WTB_ROOT / "wtb_ground_truth.json"

_HEADING_RE = re.compile(r"^## (WTB\d{2}) — (.+)$")
_TURN_RE = re.compile(r"^- \*\*\[(task|follow|clarify|chat)\]\*\* (.+)$")


def _load_metadata(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["id"]: row for row in csv.DictReader(handle)}


def load_wtb_gold(path: Path = GOLD_FILE) -> dict[str, list[dict]]:
    """Load fixed results and attach real MaintIE-tool OPR paths."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return apply_real_tool_policy(raw)


def load_wtb_scenarios(
    scenario_file: Path = SCENARIO_FILE,
    metadata_file: Path = METADATA_FILE,
    gold_file: Path = GOLD_FILE,
) -> list[dict]:
    """Return 50 aligned scenario records without exposing gold in turn text."""
    metadata = _load_metadata(metadata_file)
    gold = load_wtb_gold(gold_file)

    scenarios: list[dict] = []
    current: dict | None = None
    for line in scenario_file.read_text(encoding="utf-8").splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            if current is not None:
                scenarios.append(current)
            scenario_id, title = heading.groups()
            current = {
                "id": int(scenario_id.removeprefix("WTB")),
                "scenario_id": scenario_id,
                "title": title,
                "category": "wtb50",
                "reference_date": "2020-06-20",
                "turns": [],
                "turn_types": [],
            }
            continue

        turn = _TURN_RE.match(line)
        if turn and current is not None:
            turn_type, text = turn.groups()
            current["turn_types"].append(turn_type)
            current["turns"].append(text)

    if current is not None:
        scenarios.append(current)

    for scenario in scenarios:
        scenario_id = scenario["scenario_id"]
        if scenario_id not in metadata or scenario_id not in gold:
            raise ValueError(f"Missing metadata or gold for {scenario_id}")
        row = metadata[scenario_id]
        scenario.update(
            topology=row["topology"],
            intent_mechanism=row["intent_mechanism"],
            instruction_transition=row["instruction_transition"],
        )
        gold_turns = gold[scenario_id]
        if len(gold_turns) != len(scenario["turns"]):
            raise ValueError(f"Turn count mismatch for {scenario_id}")
        if [turn["type"] for turn in gold_turns] != scenario["turn_types"]:
            raise ValueError(f"Turn type mismatch for {scenario_id}")

    if len(scenarios) != 50:
        raise ValueError(f"Expected 50 WTB scenarios, found {len(scenarios)}")
    return scenarios


WTB_SCENARIOS = load_wtb_scenarios()
