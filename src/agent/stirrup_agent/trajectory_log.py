"""JSONL trajectory persistence for the Stirrup agent runner."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Trajectory

_log = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = (
    Path(__file__).parent.parent.parent.parent / "logs" / "stirrup_agent"
)


def _make_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"run_{timestamp}_{uuid.uuid4().hex[:6]}"


class TrajectoryLog:
    """Append lifecycle events and the completed trajectory to one JSONL file."""

    def __init__(
        self,
        log_dir: Path | None = None,
        *,
        enabled: bool = True,
        run_id: str | None = None,
    ) -> None:
        self._enabled = enabled
        self.run_id = run_id or _make_run_id()
        self._log_dir = log_dir or _DEFAULT_LOG_DIR
        self.path = self._log_dir / f"{self.run_id}.jsonl"
        if self._enabled:
            self._log_dir.mkdir(parents=True, exist_ok=True)

    def write_started(
        self,
        *,
        model: str,
        question: str,
        reference_date: str,
    ) -> None:
        self._write(
            {
                "event": "run_started",
                "status": "running",
                "model": model,
                "question": question,
                "reference_date": reference_date,
            }
        )

    def write_completed(
        self,
        *,
        model: str,
        question: str,
        answer: str,
        trajectory: Trajectory,
    ) -> None:
        payload = dataclasses.asdict(trajectory)
        payload["total_input_tokens"] = trajectory.total_input_tokens
        payload["total_output_tokens"] = trajectory.total_output_tokens
        self._write(
            {
                "event": "run_completed",
                "status": "ok",
                "model": model,
                "question": question,
                "answer": answer,
                "trajectory": payload,
            }
        )

    def write_failed(
        self,
        *,
        model: str,
        question: str,
        error: BaseException,
    ) -> None:
        status = (
            "interrupted"
            if isinstance(error, (KeyboardInterrupt, SystemExit, asyncio.CancelledError))
            else "error"
        )
        self._write(
            {
                "event": "run_failed",
                "status": status,
                "model": model,
                "question": question,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )

    def _write(self, record: dict[str, Any]) -> None:
        if not self._enabled:
            return
        envelope = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "agent": "stirrup-agent",
            **record,
        }
        try:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(envelope, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            _log.warning("TrajectoryLog: failed to write %s: %s", self.path, exc)
