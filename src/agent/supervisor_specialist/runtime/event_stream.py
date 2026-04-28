"""CLI-visible event stream for the Supervisor-Specialist system."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


class EventStream:
    def __init__(self, *, use_stderr: bool = True, quiet: bool = False) -> None:
        self._out = sys.stderr if use_stderr else sys.stdout
        self._quiet = quiet

    def emit(
        self,
        *,
        case_id: str,
        agent_role: str,
        task_type: str,
        status: str,
        message: str,
    ) -> None:
        if self._quiet:
            return
        event = {
            "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "case_id": case_id,
            "agent_role": agent_role,
            "task_type": task_type,
            "status": status,
            "message": message,
        }
        ts = event["ts"]
        role = agent_role.replace("_", "-")
        status_marker = {
            "running": ">>",
            "completed": "OK",
            "failed": "!!",
        }.get(status, "--")
        print(
            f"[{ts}] [{status_marker}] [{role}] {message}",
            file=self._out,
            flush=True,
        )
