from stirrup_benchmark.maintie.data import load_records
from stirrup_benchmark.maintie.tools import QueryFilter, group_count, rank


def test_gold_release_and_wtb01_truth():
    activity_counts = {
        row["value"]: row["count"] for row in group_count(by="activity")["groups"]
    }
    top = rank(
        by="object_class",
        n=3,
        filter=QueryFilter(activities=["Replace"]),
        patient_of_activity="Replace",
    )

    assert len(load_records()) == 1076
    assert activity_counts["Replace"] == 347
    assert activity_counts["Repair"] == 127
    assert top["groups"] == [
        {"value": "Lines & drives", "count": 89},
        {"value": "Engines & motors", "count": 44},
        {"value": "Structural/mounting parts", "count": 36},
    ]
