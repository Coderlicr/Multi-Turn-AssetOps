"""Versioned schema for the Stirrup multi-turn benchmark."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONVERSATION_FILENAME = "conversation.json"


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
        if self.valid_multi_turn and not any(
            turn.dependency_types for turn in self.turns[1:]
        ):
            raise ValueError(
                "valid_multi_turn requires an explicit dependency after turn 1"
            )
        return self


def _load_directory(path: Path) -> list[dict[str, Any]]:
    """Load self-contained ``scenario_<id>`` conversation directories.

    The regular AssetOpsBench contract remains authoritative for environment,
    prompt, and final truth: ``manifest.json``, ``question.txt``, and
    ``groundtruth.txt``.  ``conversation.json`` is the minimal multi-turn
    extension that preserves the ordered user messages and turn metadata.
    """
    raw: list[dict[str, Any]] = []
    for scenario_dir in sorted(path.iterdir()):
        if not scenario_dir.is_dir():
            continue
        conversation_path = scenario_dir / CONVERSATION_FILENAME
        if not conversation_path.exists():
            continue

        payload = json.loads(conversation_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError(f"{conversation_path} must contain one JSON object")

        folder_id = scenario_dir.name.removeprefix("scenario_")
        if str(payload.get("scenario_id", "")) != folder_id:
            raise ValueError(
                f"{conversation_path} scenario_id must match folder id {folder_id!r}"
            )

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
        if not question_path.read_text(encoding="utf-8").strip():
            raise ValueError(f"{question_path} must not be empty")

        final_truth = json.loads(groundtruth_path.read_text(encoding="utf-8"))
        turns = payload.get("turns")
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"{conversation_path} must contain at least one turn")
        if turns[-1].get("ground_truth") != final_truth:
            raise ValueError(
                f"Final turn ground_truth in {conversation_path} must exactly match "
                f"{groundtruth_path}"
            )
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
