"""Artifact registry for tracking intermediate results.

Phase 1: in-memory store with simple truncation summaries (no LLM).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Heuristic type inference ────────────────────────────────────────────────


_TOOL_TYPE_MAP: dict[str, str] = {
    "sites": "sensor_list",
    "assets": "sensor_list",
    "sensors": "sensor_list",
    "observations": "timeseries_df",
    "history": "timeseries_df",
    "forecast": "timeseries_df",
    "failure_modes": "failure_modes",
    "work_order": "work_order",
    "create_work_order": "work_order",
    "anomaly": "anomaly_report",
    "anomalies": "anomaly_report",
}


def infer_type(tool_name: str) -> str:
    """Infer artifact type from tool name using simple heuristics."""
    lower = tool_name.lower()
    for key, art_type in _TOOL_TYPE_MAP.items():
        if key in lower:
            return art_type
    return "raw_json"


def truncate_for_llm(text: str, max_chars: int = 200) -> str:
    """Truncate text for LLM context — simple truncation, no LLM call."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


# ── Models ──────────────────────────────────────────────────────────────────


class Artifact(BaseModel):
    """Metadata wrapper for any intermediate result."""

    id: str = Field(default_factory=lambda: f"ART-{uuid.uuid4().hex[:8]}")
    artifact_type: str  # "sensor_list", "timeseries_df", "anomaly_report", etc.
    created_by_step: int
    created_by_server: str
    summary: str  # <=200 chars, safe for LLM context
    raw_data: Any  # Full data (kept OUT of LLM prompts)
    depends_on: list[str] = Field(default_factory=list)  # upstream artifact IDs


class ArtifactRegistry:
    """In-memory artifact store with lineage tracking."""

    def __init__(self) -> None:
        self._store: dict[str, Artifact] = {}

    def register(self, artifact: Artifact) -> str:
        """Register an artifact and return its ID."""
        self._store[artifact.id] = artifact
        return artifact.id

    def get(self, artifact_id: str) -> Optional[Artifact]:
        """Return the full artifact, or None if not found."""
        return self._store.get(artifact_id)

    def get_summary(self, artifact_id: str) -> str:
        """Return summary only -- this is what goes into LLM context."""
        art = self._store.get(artifact_id)
        return art.summary if art else ""

    def get_raw(self, artifact_id: str) -> Any:
        """Return raw data -- for code execution, NOT for LLM prompts."""
        art = self._store.get(artifact_id)
        return art.raw_data if art else None

    def get_by_step(self, step_number: int) -> Optional[Artifact]:
        """Return the artifact produced by a given step, or None."""
        for art in self._store.values():
            if art.created_by_step == step_number:
                return art
        return None

    def lineage(self, artifact_id: str) -> list[str]:
        """Trace back through depends_on to build full evidence chain."""
        visited: set[str] = set()
        chain: list[str] = []

        def _walk(aid: str) -> None:
            if aid in visited:
                return
            visited.add(aid)
            art = self._store.get(aid)
            if art is None:
                return
            for dep_id in art.depends_on:
                _walk(dep_id)
            chain.append(aid)

        _walk(artifact_id)
        return chain

    def all_ids(self) -> list[str]:
        """Return all registered artifact IDs."""
        return list(self._store.keys())

    def __len__(self) -> int:
        return len(self._store)
