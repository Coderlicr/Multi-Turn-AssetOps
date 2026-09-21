"""Schema and loader for the multi-turn evaluation dataset.

Replaces docs/Multi_Turn_Dialog_Scenarios.md, whose prose reference answers
could not be machine-checked and contained unverified claims — e.g. it pinned
Dialog 1 to "Chiller 6" although the user names no asset and site MAIN has four,
and asserted an efficiency figure that only holds once sensor dropouts are
excluded (65.4% of that column reads 0).

Each turn separates three kinds of expectation:

* ``facts``        — assertions checkable against the live tools/DB by
                     ``validate.py``. These are the dataset's factual ground.
* ``expectations`` — what a correct answer must address; scored by the LLM judge.
* ``pitfalls``     — claims that indicate hallucination or a skipped step.

Keeping them apart matters: reference answers derived from a system's own run
are circular unless the factual part is re-verified against the data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

DATASET_DIR = Path(__file__).parent
DIALOGS_DIR = DATASET_DIR / "dialogs"


class FactCheck(BaseModel):
    """How to re-verify a fact against the live system."""

    tool: str = Field(description="MCP tool name, e.g. iot.assets")
    args: dict[str, Any] = Field(default_factory=dict)
    #: Substrings that must all appear in the tool's JSON response.
    expect_contains: list[str] = Field(default_factory=list)
    #: Name of a function in checks.py, used when the claim is numeric and the
    #: tool returns a csv_path. Substring matching cannot verify those.
    fn: str | None = None
    #: Optional free-form note when the check needs manual interpretation.
    manual: str | None = None


class Fact(BaseModel):
    id: str
    claim: str
    check: FactCheck | None = None
    #: Set once validate.py has confirmed it, with the date of the run.
    verified_on: str | None = None


class Turn(BaseModel):
    index: int
    user: str
    #: Domains the turn's conclusions must rest on. Satisfied EITHER by calling a
    #: tool this turn OR by reusing an artifact an earlier turn produced — a turn
    #: that answers purely from retained evidence is correct, not a skipped step.
    #: Scoring on "did it call a tool" would penalise exactly the behaviour this
    #: system exists to produce, and would flatter the no-reuse ablation.
    evidence_domains: list[str] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    expectations: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    notes: str | None = None


class Dialog(BaseModel):
    id: int
    title: str
    category: str
    reference_date: str
    site: str = "MAIN"
    #: Assets the user names explicitly. Empty means the user was vague and a
    #: correct answer must resolve or surface the ambiguity rather than guess.
    assets_named_by_user: list[str] = Field(default_factory=list)
    #: Data-quality constraints any numeric claim has to respect.
    data_caveats: list[str] = Field(default_factory=list)
    turns: list[Turn]

    @property
    def turn_count(self) -> int:
        return len(self.turns)


def load_dialog(path: Path) -> Dialog:
    return Dialog.model_validate(yaml.safe_load(path.read_text()))


def load_all() -> list[Dialog]:
    return [load_dialog(p) for p in sorted(DIALOGS_DIR.glob("dialog_*.yaml"))]


def as_runner_scenarios() -> list[dict]:
    """Shape consumed by the eval runners (id/title/category/reference_date/turns)."""
    return [
        {
            "id": d.id,
            "title": d.title,
            "category": d.category,
            "reference_date": d.reference_date,
            "turns": [t.user for t in d.turns],
        }
        for d in load_all()
    ]
