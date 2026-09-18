"""In-memory artifact store for the Supervisor-Specialist system."""

from __future__ import annotations

from agent.supervisor_specialist.schemas import ArtifactEnvelope

#: Artifacts stay visible for the whole case (default, cross-turn evidence reuse).
SCOPE_CASE = "case"
#: Artifacts are only visible during the turn that produced them (reuse ablation).
SCOPE_TURN = "turn"

_VALID_SCOPES = (SCOPE_CASE, SCOPE_TURN)


class ArtifactStore:
    """Stores artifacts and controls which of them agents are allowed to see.

    Under ``SCOPE_CASE`` every stored artifact stays visible, which is what
    cross-turn evidence reuse relies on. Under ``SCOPE_TURN`` an artifact is
    only visible during the turn that produced it: nothing is deleted, so
    behavior logs and traces are unaffected, but the supervisor and the
    specialists can no longer read or reference evidence from earlier turns.
    """

    def __init__(self, scope: str = SCOPE_CASE) -> None:
        if scope not in _VALID_SCOPES:
            raise ValueError(f"Unknown artifact store scope: {scope!r}")
        self._scope = scope
        self._items: dict[str, ArtifactEnvelope] = {}
        self._turn_of: dict[str, int] = {}
        self._counters: dict[str, int] = {}
        self._turn_index = 0

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def turn_index(self) -> int:
        return self._turn_index

    def begin_turn(self) -> int:
        """Open a new turn. Under turn scope this hides all earlier artifacts."""
        self._turn_index += 1
        return self._turn_index

    def next_id(self, role_prefix: str) -> str:
        current = self._counters.get(role_prefix, 0) + 1
        self._counters[role_prefix] = current
        return f"artifact_{role_prefix}_{current:03d}"

    def save_many(self, artifacts: list[ArtifactEnvelope]) -> None:
        for artifact in artifacts:
            self._items[artifact.artifact_id] = artifact
            self._turn_of[artifact.artifact_id] = self._turn_index

    def _visible(self, artifact_id: str) -> bool:
        if artifact_id not in self._items:
            return False
        if self._scope == SCOPE_CASE:
            return True
        return self._turn_of.get(artifact_id) == self._turn_index

    def get(self, artifact_id: str) -> ArtifactEnvelope:
        if not self._visible(artifact_id):
            raise KeyError(artifact_id)
        return self._items[artifact_id]

    def get_many(self, artifact_ids: list[str]) -> list[ArtifactEnvelope]:
        return [self._items[i] for i in artifact_ids if self._visible(i)]

    def has(self, artifact_id: str) -> bool:
        return self._visible(artifact_id)

    def all(self) -> list[ArtifactEnvelope]:
        return [a for aid, a in self._items.items() if self._visible(aid)]

    def all_ever_stored(self) -> list[ArtifactEnvelope]:
        """Every artifact ever stored, ignoring visibility (for logging/analysis)."""
        return list(self._items.values())
