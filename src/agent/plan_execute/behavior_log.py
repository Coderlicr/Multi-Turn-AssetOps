"""JSONL behavior logger for the plan-execute system."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Plan, PlanStep

_log = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = Path(__file__).parent.parent.parent.parent / "logs" / "plan_execute"


class PlanExecuteBehaviorLog:
    """Write plan-execute behavior events in a Supervisor-Specialist-like shape."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self._log_dir = log_dir or _DEFAULT_LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        case_id: str,
        agent_role: str,
        task_type: str,
        status: str,
        turn_id: str | None = None,
        input_artifact_ids: list[str] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        output_artifact_ids: list[str] | None = None,
        **extra: Any,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "agent_role": agent_role,
            "task_type": task_type,
            "input_artifact_ids": input_artifact_ids or [],
            "tool_calls": tool_calls or [],
            "output_artifact_ids": output_artifact_ids or [],
            "status": status,
        }
        if turn_id is not None:
            record["turn_id"] = turn_id
        record.update({key: _jsonable(value) for key, value in extra.items()})

        log_path = self._log_dir / f"{case_id}.jsonl"
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            _log.warning("PlanExecuteBehaviorLog: failed to write log for %s: %s", case_id, exc)


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    return {
        "raw": plan.raw,
        "steps": [plan_step_to_dict(step) for step in plan.steps],
    }


def plan_step_to_dict(step: PlanStep) -> dict[str, Any]:
    return {
        "step_number": step.step_number,
        "task": step.task,
        "server": step.server,
        "tool": step.tool,
        "tool_args": step.tool_args,
        "dependencies": step.dependencies,
        "expected_output": step.expected_output,
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
