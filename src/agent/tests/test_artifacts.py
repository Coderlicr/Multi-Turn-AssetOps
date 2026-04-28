"""Tests for the Artifact registry (Phase 1)."""

from agent.artifacts import (
    Artifact,
    ArtifactRegistry,
    infer_type,
    truncate_for_llm,
)


# ── infer_type ───────────────────────────────────────────────────────────────


class TestInferType:
    def test_known_tool_name(self):
        assert infer_type("sites") == "sensor_list"
        assert infer_type("failure_modes") == "failure_modes"
        assert infer_type("create_work_order") == "work_order"

    def test_unknown_tool_name_returns_raw_json(self):
        assert infer_type("unknown_tool") == "raw_json"

    def test_case_insensitive(self):
        assert infer_type("OBSERVATIONS") == "timeseries_df"


# ── truncate_for_llm ────────────────────────────────────────────────────────


class TestTruncateForLlm:
    def test_short_text_unchanged(self):
        assert truncate_for_llm("hello", 200) == "hello"

    def test_long_text_truncated(self):
        text = "x" * 300
        result = truncate_for_llm(text, 200)
        assert len(result) == 200

    def test_exact_boundary(self):
        text = "a" * 200
        assert truncate_for_llm(text, 200) == text


# ── ArtifactRegistry ────────────────────────────────────────────────────────


def _make_artifact(step: int, server: str = "iot", deps: list[str] | None = None) -> Artifact:
    return Artifact(
        artifact_type="sensor_list",
        created_by_step=step,
        created_by_server=server,
        summary=f"Step {step} result",
        raw_data=f"raw data for step {step}",
        depends_on=deps or [],
    )


class TestArtifactRegistry:
    def test_register_and_get(self):
        reg = ArtifactRegistry()
        art = _make_artifact(1)
        aid = reg.register(art)
        assert reg.get(aid) is art

    def test_get_nonexistent_returns_none(self):
        reg = ArtifactRegistry()
        assert reg.get("ART-nonexistent") is None

    def test_get_summary(self):
        reg = ArtifactRegistry()
        art = _make_artifact(1)
        reg.register(art)
        assert reg.get_summary(art.id) == "Step 1 result"

    def test_get_summary_missing_returns_empty(self):
        reg = ArtifactRegistry()
        assert reg.get_summary("ART-missing") == ""

    def test_get_raw(self):
        reg = ArtifactRegistry()
        art = _make_artifact(1)
        reg.register(art)
        assert reg.get_raw(art.id) == "raw data for step 1"

    def test_get_raw_missing_returns_none(self):
        reg = ArtifactRegistry()
        assert reg.get_raw("ART-missing") is None

    def test_get_by_step(self):
        reg = ArtifactRegistry()
        art = _make_artifact(2)
        reg.register(art)
        assert reg.get_by_step(2) is art

    def test_get_by_step_missing_returns_none(self):
        reg = ArtifactRegistry()
        assert reg.get_by_step(99) is None

    def test_lineage_single(self):
        reg = ArtifactRegistry()
        art = _make_artifact(1)
        reg.register(art)
        assert reg.lineage(art.id) == [art.id]

    def test_lineage_chain(self):
        reg = ArtifactRegistry()
        a1 = _make_artifact(1)
        reg.register(a1)
        a2 = _make_artifact(2, deps=[a1.id])
        reg.register(a2)
        a3 = _make_artifact(3, deps=[a2.id])
        reg.register(a3)
        chain = reg.lineage(a3.id)
        assert chain == [a1.id, a2.id, a3.id]

    def test_lineage_missing_returns_empty(self):
        reg = ArtifactRegistry()
        assert reg.lineage("ART-missing") == []

    def test_all_ids(self):
        reg = ArtifactRegistry()
        a1 = _make_artifact(1)
        a2 = _make_artifact(2)
        reg.register(a1)
        reg.register(a2)
        assert set(reg.all_ids()) == {a1.id, a2.id}

    def test_len(self):
        reg = ArtifactRegistry()
        assert len(reg) == 0
        reg.register(_make_artifact(1))
        assert len(reg) == 1

    def test_artifact_id_format(self):
        art = _make_artifact(1)
        assert art.id.startswith("ART-")
        assert len(art.id) == 12  # "ART-" + 8 hex chars
