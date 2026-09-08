"""Versioned schema for the Stirrup multi-turn benchmark."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

TURN_HEADER = re.compile(r"^User turn (\d+):\s*$", re.MULTILINE)


def parse_question(text: str) -> list[str]:
    """Read numbered user messages without exposing future turns to the agent."""
    headers = list(TURN_HEADER.finditer(text))
    if not headers:
        raise ValueError("question.txt must use 'User turn 1:' headers")
    if text[: headers[0].start()].strip():
        raise ValueError("Unexpected text before the first user turn")
    if [int(h.group(1)) for h in headers] != list(range(1, len(headers) + 1)):
        raise ValueError("User turn numbers must be sequential from 1")
    messages = [
        text[
            h.end() : headers[i + 1].start() if i + 1 < len(headers) else len(text)
        ].strip()
        for i, h in enumerate(headers)
    ]
    if not all(messages):
        raise ValueError("User turns must not be empty")
    return messages


class DependencyType(StrEnum):
    REFERENCE_RESOLUTION = "reference_resolution"
    INFORMATION_ACCUMULATION = "information_accumulation"
    CONSTRAINT_UPDATE = "constraint_update"
    CROSS_TURN_TOOL_USE = "cross_turn_tool_use"
    CORRECTION_CLARIFICATION = "correction_clarification"


class MultiTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnSpec(MultiTurn):
    """One real user turn; not one internal agent reasoning/tool step."""

    turn_id: int = Field(ge=1)
    turn_type: str = "task"
    user_message: str = Field(min_length=1)
    dependency_on_previous_turns: str
    dependency_types: list[DependencyType] = Field(default_factory=list)
    expected_information: str
    expected_tool_behavior: list[list[str]] = Field(default_factory=list)
    accepted_tool_plans: list[list[list[str]]] = Field(default_factory=list)
    ground_truth: Any = None


class MultiTurnScenario(MultiTurn):
    """One benchmark conversation with scenario- and turn-level truth."""

    schema_version: str = "1.0"
    scenario_id: str = Field(min_length=1)
    paired_scenario_id: str | None = None
    source: str = Field(min_length=1)
    split: str
    description: str = Field(min_length=1)
    overall_user_goal: str = Field(min_length=1)
    overall_expected_outcome: str = Field(min_length=1)
    reference_date: str | None = None
    context_dependency: list[DependencyType] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    executable: bool
    valid_multi_turn: bool
    ground_truth_available: bool
    duplicate_of: str | None = None
    notes: str = ""
    turns: list[TurnSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_turns(self) -> MultiTurnScenario:
        if self.valid_multi_turn and len(self.turns) < 2:
            raise ValueError("valid_multi_turn requires at least two user turns")
        expected = list(range(1, len(self.turns) + 1))
        actual = [turn.turn_id for turn in self.turns]
        if actual != expected:
            raise ValueError(f"turn_id values must be sequential from 1, got {actual}")
        if (
            self.source != "scenario_directory"
            and self.valid_multi_turn
            and not any(turn.dependency_types for turn in self.turns[1:])
        ):
            raise ValueError(
                "valid_multi_turn requires an explicit dependency after turn 1"
            )
        return self


def _load_directory(path: Path) -> list[dict[str, Any]]:
    """Load the three-file contract; no per-turn labels are invented."""
    raw: list[dict[str, Any]] = []
    for scenario_dir in sorted(path.iterdir()):
        if not scenario_dir.is_dir():
            continue
        question_path = scenario_dir / "question.txt"
        if not question_path.exists():
            continue
        question = question_path.read_text(encoding="utf-8")
        # Existing upstream single-question directories use another runner.
        if not TURN_HEADER.search(question):
            continue
        messages = parse_question(question)
        folder_id = scenario_dir.name.removeprefix("scenario_")

        manifest_path = scenario_dir / "manifest.json"
        question_path = scenario_dir / "question.txt"
        groundtruth_path = scenario_dir / "groundtruth.txt"
        for required_path in (manifest_path, question_path, groundtruth_path):
            if not required_path.exists():
                raise FileNotFoundError(
                    f"Scenario {folder_id} is missing required file: {required_path}"
                )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise TypeError(f"{manifest_path} must contain a JSON object")
        final_truth = json.loads(groundtruth_path.read_text(encoding="utf-8"))
        # Runtime server routing is derived from the declared collections.
        tools = []
        for server, collections in {
            "iot": {"iot", "asset"},
            "tsfm": {"model_catalog", "feature_catalog"},
            "fmsr": {"failure_mode"},
        }.items():
            if collections.intersection(manifest):
                tools.append(server)
        if folder_id.startswith("WTB") and not manifest:
            tools = ["maintie"]
        payload = {
            "scenario_id": folder_id,
            "source": "scenario_directory",
            "split": "pilot",
            "description": folder_id,
            "overall_user_goal": messages[0],
            "overall_expected_outcome": "Final answer matches groundtruth.txt",
            "required_tools": tools,
            "executable": final_truth is not None,
            "valid_multi_turn": len(messages) > 1,
            "ground_truth_available": final_truth is not None,
            "notes": "Final-answer evaluation only; per-turn truth/path labels are unavailable.",
            "turns": [
                {
                    "turn_id": i + 1,
                    "user_message": message,
                    "dependency_on_previous_turns": "Not annotated in the three-file format",
                    "expected_information": "See question.txt",
                    "ground_truth": final_truth if i == len(messages) - 1 else None,
                }
                for i, message in enumerate(messages)
            ],
        }
        raw.append(payload)
    return raw


def load_scenarios(path: Path) -> list[MultiTurnScenario]:
    """Load a scenario directory, JSON, or JSONL and reject duplicate IDs."""
    if path.is_dir():
        raw = _load_directory(path)
        scenarios = [MultiTurnScenario.model_validate(item) for item in raw]
        ids = [scenario.scenario_id for scenario in scenarios]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate scenario IDs in {path}")
        return scenarios

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    if path.suffix == ".jsonl":
        raw = [json.loads(line) for line in content.splitlines() if line.strip()]
    else:
        payload = json.loads(content)
        raw = payload if isinstance(payload, list) else [payload]
    scenarios = [MultiTurnScenario.model_validate(item) for item in raw]
    ids = [scenario.scenario_id for scenario in scenarios]
    if len(set(ids)) != len(ids):
        raise ValueError(f"Duplicate scenario IDs in {path}")
    return scenarios
