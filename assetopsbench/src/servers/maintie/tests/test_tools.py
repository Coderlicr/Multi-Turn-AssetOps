from servers.maintie.data import load_records
from servers.maintie.tools import QueryFilter, compare, count, get_text, rank, search


def test_official_gold_release_is_loaded():
    records = load_records()
    assert len(records) == 1076
    assert records[0]["wo_id"] == 1
    assert records[-1]["wo_id"] == 1076


def test_core_activity_counts_match_release():
    assert count(QueryFilter(activities=["Replace"]))["count"] == 347
    assert count(QueryFilter(activities=["Repair"]))["count"] == 127
    assert count(QueryFilter(activities=["Inspect"]))["count"] == 62


def test_fault_pareto_matches_maintie_annotations():
    rows = rank("fault_mode", n=5)["groups"]
    assert [(row["value"], row["count"]) for row in rows] == [
        ("Failed/broken", 215),
        ("Faulty", 178),
        ("Active failure (leak/overheat)", 146),
        ("Worn/degraded", 45),
        ("Defect (crack/hole/noise)", 32),
    ]


def test_replaced_component_ranking_uses_patient_relations():
    rows = rank(
        "object_class",
        n=3,
        filter=QueryFilter(activities=["Replace"]),
        patient_of_activity="Replace",
    )["groups"]
    assert [(row["value"], row["count"]) for row in rows] == [
        ("Lines & drives", 89),
        ("Engines & motors", 44),
        ("Structural/mounting parts", 36),
    ]


def test_aliases_are_ontology_filters_not_text_searches():
    assert (
        count(QueryFilter(object_terms=["bearing"], activities=["Replace"]))["count"]
        == 9
    )
    assert (
        count(QueryFilter(object_terms=["seal"], activities=["Replace"]))["count"] == 7
    )
    assert (
        count(QueryFilter(object_terms=["belt"], activities=["Replace"]))["count"] == 56
    )
    assert (
        count(
            QueryFilter(object_terms=["hose"], activities=["Replace"], has_fault=True)
        )["count"]
        == 24
    )


def test_search_ids_can_be_reused_to_refine_a_set():
    leaks = search(QueryFilter(fault_modes=["leak"]))
    replaced_leaks = search(QueryFilter(activities=["Replace"]), leaks["wo_ids"])
    assert leaks["count"] == 146
    assert replaced_leaks["count"] == 22


def test_text_and_absent_object_queries():
    assert count(QueryFilter(text_contains=["pump"]))["count"] == 42
    assert count(QueryFilter(no_physical_object=True))["count"] == 30


def test_compare_returns_fault_and_remedy_summary():
    result = compare(
        {
            "bearing": QueryFilter(object_terms=["bearing"]),
            "seal": QueryFilter(object_terms=["seal"]),
        }
    )["comparison"]
    assert result["bearing"]["fault_work_orders"] == 10
    assert result["bearing"]["activities"]["Replace"] == 9
    assert result["seal"]["fault_work_orders"] == 14
    assert result["seal"]["activities"]["Replace"] == 7


def test_get_text_rejects_unknown_id():
    assert "error" in get_text(1077)
