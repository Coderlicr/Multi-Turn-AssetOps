"""Tests for ArtifactStore."""

import pytest

from agent.supervisor_specialist.runtime.artifact_store import ArtifactStore
from agent.supervisor_specialist.schemas import ArtifactEnvelope, TimeWindow


def _make_artifact(artifact_id: str, artifact_type: str = "dataset_ref") -> ArtifactEnvelope:
    return ArtifactEnvelope(
        artifact_id=artifact_id,
        case_id="case_001",
        producer="data_collection_specialist",
        artifact_type=artifact_type,
        asset_ids=["Chiller 6"],
        time_window=TimeWindow(),
        source_tools=["iot.history_csv"],
        source_artifacts=[],
        payload={"key": "value"},
    )


def test_next_id_increments():
    store = ArtifactStore()
    assert store.next_id("dc") == "artifact_dc_001"
    assert store.next_id("dc") == "artifact_dc_002"
    assert store.next_id("ts") == "artifact_ts_001"


def test_save_and_get():
    store = ArtifactStore()
    art = _make_artifact("artifact_dc_001")
    store.save_many([art])
    retrieved = store.get("artifact_dc_001")
    assert retrieved.artifact_id == "artifact_dc_001"
    assert retrieved.payload == {"key": "value"}


def test_get_many():
    store = ArtifactStore()
    arts = [_make_artifact(f"artifact_dc_{i:03d}") for i in range(1, 4)]
    store.save_many(arts)
    ids = ["artifact_dc_001", "artifact_dc_003"]
    result = store.get_many(ids)
    assert len(result) == 2
    assert result[0].artifact_id == "artifact_dc_001"
    assert result[1].artifact_id == "artifact_dc_003"


def test_get_many_skips_missing():
    store = ArtifactStore()
    store.save_many([_make_artifact("artifact_dc_001")])
    result = store.get_many(["artifact_dc_001", "artifact_dc_999"])
    assert len(result) == 1


def test_has():
    store = ArtifactStore()
    store.save_many([_make_artifact("artifact_dc_001")])
    assert store.has("artifact_dc_001")
    assert not store.has("artifact_dc_999")


def test_get_missing_raises():
    store = ArtifactStore()
    with pytest.raises(KeyError):
        store.get("nonexistent")
