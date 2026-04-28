"""In-memory artifact store for the Supervisor-Specialist system."""

from __future__ import annotations

from agent.supervisor_specialist.schemas import ArtifactEnvelope


class ArtifactStore:
    def __init__(self) -> None:
        self._items: dict[str, ArtifactEnvelope] = {}
        self._counters: dict[str, int] = {}

    def next_id(self, role_prefix: str) -> str:
        current = self._counters.get(role_prefix, 0) + 1
        self._counters[role_prefix] = current
        return f"artifact_{role_prefix}_{current:03d}"

    def save_many(self, artifacts: list[ArtifactEnvelope]) -> None:
        for artifact in artifacts:
            self._items[artifact.artifact_id] = artifact

    def get(self, artifact_id: str) -> ArtifactEnvelope:
        return self._items[artifact_id]

    def get_many(self, artifact_ids: list[str]) -> list[ArtifactEnvelope]:
        return [self.get(i) for i in artifact_ids if i in self._items]

    def has(self, artifact_id: str) -> bool:
        return artifact_id in self._items

    def all(self) -> list[ArtifactEnvelope]:
        return list(self._items.values())
