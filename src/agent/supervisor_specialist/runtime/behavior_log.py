"""JSONL behavior logger for the Supervisor-Specialist system."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agent.supervisor_specialist.schemas import ArtifactEnvelope, TaskEnvelope, ToolCallLog

_log = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = Path(__file__).parent.parent.parent.parent.parent / "logs" / "supervisor_specialist"


class BehaviorLog:
    def __init__(self, log_dir: Path | None = None, reuse_mode: str | None = None) -> None:
        self._log_dir = log_dir or _DEFAULT_LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)
        # Stamped on every record so ablation runs are self-identifying.
        self._reuse_mode = reuse_mode

    def write(
        self,
        *,
        case_id: str,
        agent_role: str,
        task_type: str,
        input_artifact_ids: list[str],
        tool_calls: list[ToolCallLog],
        output_artifact_ids: list[str],
        status: str,
        turn_id: str | None = None,
        task: TaskEnvelope | None = None,
        output_artifacts: list[ArtifactEnvelope] | None = None,
        user_message: str | None = None,
        final_response: str | None = None,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "agent_role": agent_role,
            "task_type": task_type,
            "input_artifact_ids": input_artifact_ids,
            "tool_calls": [tc.model_dump() for tc in tool_calls],
            "output_artifact_ids": output_artifact_ids,
            "status": status,
        }
        if self._reuse_mode is not None:
            record["reuse_mode"] = self._reuse_mode
        if turn_id is not None:
            record["turn_id"] = turn_id
        if task is not None:
            record["task"] = task.model_dump()
        if output_artifacts is not None:
            record["output_artifacts"] = [a.model_dump() for a in output_artifacts]
        if user_message is not None:
            record["user_message"] = user_message
        if final_response is not None:
            record["final_response"] = final_response
        log_path = self._log_dir / f"{case_id}.jsonl"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            _log.warning("BehaviorLog: failed to write log for %s: %s", case_id, exc)
