"""Deterministic query tools over the official MaintIE gold graph."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .data import (
    activities,
    entity_mentions,
    entity_types,
    fault_modes,
    has_fault,
    human_fault_mode,
    human_object_class,
    load_records,
    maintenance_activities,
    normalize_fault_mode,
    normalize_object_term,
    object_classes,
    object_types,
    patient_object_classes,
    patient_object_types,
)


class QueryFilter(BaseModel):
    """AND-combined filters; multiple values within one field are OR-combined."""

    model_config = ConfigDict(extra="forbid")

    activities: list[str] = Field(
        default_factory=list,
        description="Maintenance/supporting activity leaves, e.g. Replace, Repair, Inspect.",
    )
    object_terms: list[str] = Field(
        default_factory=list,
        description=(
            "Ontology class, readable class label, or standard alias such as bearing, "
            "seal, belt, hose, filter, pump, engine, sensor, or valve."
        ),
    )
    fault_modes: list[str] = Field(
        default_factory=list,
        description=(
            "Fault mode or alias: failed/broken, faulty, leak, worn/degraded, "
            "or crack/defect."
        ),
    )
    has_fault: bool | None = Field(
        default=None,
        description="True for work orders with an undesirable State, Process, or Property.",
    )
    text_contains: list[str] = Field(
        default_factory=list,
        description="Case-insensitive literal terms; every listed term must occur in text.",
    )
    no_physical_object: bool | None = Field(
        default=None,
        description="True to select records with no PhysicalObject entity.",
    )
    has_placeholder: bool | None = Field(
        default=None,
        description="True to select records containing <num> or <date> placeholders.",
    )


FilterArg = Annotated[
    QueryFilter | None,
    Field(
        description="Optional structured filter. Omit for the full 1,076-record corpus."
    ),
]
IdsArg = Annotated[
    list[int] | None,
    Field(
        description="Optional prior search result IDs; restrict this call to that set."
    ),
]


def _matches(record: dict[str, Any], query: QueryFilter | None) -> bool:
    if query is None:
        return True

    record_activities = {value.casefold() for value in activities(record)}
    if query.activities and not any(
        value.casefold() in record_activities for value in query.activities
    ):
        return False

    types = entity_types(record)
    if query.object_terms:
        normalized = [
            normalize_object_term(value).casefold() for value in query.object_terms
        ]
        if not any(
            term in type_name.casefold() for term in normalized for type_name in types
        ):
            return False

    if query.fault_modes:
        record_modes = {value.casefold() for value in fault_modes(record)}
        normalized_modes = {
            normalize_fault_mode(value).casefold() for value in query.fault_modes
        }
        if not (record_modes & normalized_modes):
            return False

    if query.has_fault is not None and has_fault(record) != query.has_fault:
        return False

    folded_text = record["text"].casefold()
    if query.text_contains and not all(
        term.casefold() in folded_text for term in query.text_contains
    ):
        return False

    no_object = not any(value.startswith("PhysicalObject") for value in types)
    if query.no_physical_object is not None and no_object != query.no_physical_object:
        return False

    has_placeholder = "<num>" in record["tokens"] or "<date>" in record["tokens"]
    if query.has_placeholder is not None and has_placeholder != query.has_placeholder:
        return False
    return True


def _select(
    query: QueryFilter | None, within_ids: list[int] | None
) -> list[dict[str, Any]]:
    allowed = set(within_ids) if within_ids is not None else None
    return [
        record
        for record in load_records()
        if (allowed is None or record["wo_id"] in allowed) and _matches(record, query)
    ]


def search(filter: FilterArg = None, within_ids: IdsArg = None) -> dict[str, Any]:
    """Find MaintIE work orders and return reusable stable IDs.

    Use ``within_ids`` to refine a set from an earlier turn instead of repeating
    the original search.  Empty filters return the whole corpus.
    """
    records = _select(filter, within_ids)
    return {"count": len(records), "wo_ids": [record["wo_id"] for record in records]}


def count(
    filter: FilterArg = None,
    within_ids: IdsArg = None,
    distinct_by: Annotated[
        Literal["work_order", "object_class", "object_type"],
        Field(description="Counting unit. Usually work_order."),
    ] = "work_order",
    patient_of_activity: Annotated[
        str | None,
        Field(
            description="For distinct object counts, use only patients linked to this activity."
        ),
    ] = None,
) -> dict[str, Any]:
    """Count matching work orders or distinct object ontology classes/types."""
    records = _select(filter, within_ids)
    if distinct_by == "work_order":
        value = len(records)
    else:
        values: set[str] = set()
        for record in records:
            if distinct_by == "object_class":
                current = (
                    patient_object_classes(record, patient_of_activity)
                    if patient_of_activity
                    else object_classes(record)
                )
            else:
                current = (
                    patient_object_types(record, patient_of_activity)
                    if patient_of_activity
                    else object_types(record)
                )
            values.update(current)
        value = len(values)
    return {"count": value, "unit": distinct_by, "matched_work_orders": len(records)}


def _group_values(
    record: dict[str, Any], by: str, patient_of_activity: str | None
) -> list[Any]:
    if by == "activity":
        return list(set(maintenance_activities(record)))
    if by == "fault_mode":
        return [human_fault_mode(value) for value in fault_modes(record)]
    if by == "object_class":
        raw = (
            patient_object_classes(record, patient_of_activity)
            if patient_of_activity
            else object_classes(record)
        )
        return [human_object_class(value) for value in raw]
    if by == "object_type":
        return list(
            patient_object_types(record, patient_of_activity)
            if patient_of_activity
            else object_types(record)
        )
    if by == "signature":
        objects = {human_object_class(value) for value in object_classes(record)} or {
            "(none)"
        }
        faults = {human_fault_mode(value) for value in fault_modes(record)} or {
            "(none)"
        }
        acts = set(maintenance_activities(record)) or {"(none)"}
        return [
            [obj, fault, action]
            for obj in objects
            for fault in faults
            for action in acts
        ]
    raise ValueError(f"Unsupported group: {by}")


def group_count(
    by: Annotated[
        Literal["activity", "object_class", "object_type", "fault_mode", "signature"],
        Field(description="Dimension to group by."),
    ],
    filter: FilterArg = None,
    within_ids: IdsArg = None,
    patient_of_activity: Annotated[
        str | None,
        Field(
            description=(
                "For object grouping, count only objects related as patients of this "
                "activity. Use Replace for exact replaced-component rankings."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Group matching work orders and count each value once per work order.

    ``patient_of_activity='Replace'`` follows MaintIE relations and is the
    correct definition of a replaced component, rather than merely co-occurring
    with a Replace annotation.
    """
    records = _select(filter, within_ids)
    grouped: Counter[Any] = Counter()
    for record in records:
        values = _group_values(record, by, patient_of_activity)
        normalized = [tuple(v) if isinstance(v, list) else v for v in values]
        # Co-occurring object categories count once per work order.  MaintIE
        # entity and relation groups count their actual annotated occurrences.
        if by in {"object_class", "object_type"} and not patient_of_activity:
            normalized = list(set(normalized))
        for value in normalized:
            grouped[value] += 1
    rows = [
        {
            "value": list(value) if isinstance(value, tuple) else value,
            "count": value_count,
        }
        for value, value_count in sorted(
            grouped.items(), key=lambda item: (-item[1], str(item[0]))
        )
    ]
    return {"by": by, "matched_work_orders": len(records), "groups": rows}


def rank(
    by: Annotated[
        Literal["activity", "object_class", "object_type", "fault_mode", "signature"],
        Field(description="Dimension to rank."),
    ],
    n: Annotated[int, Field(ge=1, le=100, description="Number of ranked rows.")] = 10,
    filter: FilterArg = None,
    within_ids: IdsArg = None,
    ascending: Annotated[
        bool, Field(description="Return least frequent rows first.")
    ] = False,
    patient_of_activity: Annotated[
        str | None, Field(description="See group_count.")
    ] = None,
) -> dict[str, Any]:
    """Return the top or bottom N grouped counts without a separate client-side sort."""
    result = group_count(by, filter, within_ids, patient_of_activity)
    rows = result["groups"]
    if ascending:
        rows = sorted(rows, key=lambda row: (row["count"], str(row["value"])))
    return {**result, "ascending": ascending, "groups": rows[:n]}


def get_text(
    wo_id: Annotated[int, Field(ge=1, description="Stable 1-based work-order ID.")],
) -> dict[str, Any]:
    """Return the original text and full MaintIE annotations for one work order."""
    records = load_records()
    if wo_id > len(records):
        return {"error": f"Unknown wo_id {wo_id}; valid range is 1..{len(records)}"}
    record = records[wo_id - 1]
    return {
        "wo_id": wo_id,
        "text": record["text"],
        "tokens": record["tokens"],
        "entities": entity_mentions(record),
        "relations": record["relations"],
    }


def extract(
    wo_ids: Annotated[list[int], Field(description="IDs returned by search.")],
    limit: Annotated[
        int, Field(ge=1, le=200, description="Maximum detailed records.")
    ] = 50,
) -> dict[str, Any]:
    """Extract text plus normalized activities, objects, and faults for selected IDs."""
    selected = _select(None, wo_ids)
    rows = [
        {
            "wo_id": record["wo_id"],
            "text": record["text"],
            "activities": activities(record),
            "object_classes": [
                human_object_class(value) for value in object_classes(record)
            ],
            "object_types": object_types(record),
            "fault_modes": [human_fault_mode(value) for value in fault_modes(record)],
        }
        for record in selected[:limit]
    ]
    return {"matched": len(selected), "returned": len(rows), "records": rows}


def compare(
    queries: Annotated[
        dict[str, QueryFilter],
        Field(description="Named filters to compare, e.g. bearing and seal."),
    ],
    within_ids: IdsArg = None,
) -> dict[str, Any]:
    """Compare named subsets using the same deterministic metrics.

    Returns work-order count, fault-work-order count, and distributions of
    activities, fault modes, and object classes for every named subset.
    """
    comparison: dict[str, Any] = {}
    for name, query in queries.items():
        records = _select(query, within_ids)
        activity_count: Counter[str] = Counter()
        fault_count: Counter[str] = Counter()
        object_count: Counter[str] = Counter()
        for record in records:
            activity_count.update(set(maintenance_activities(record)))
            fault_count.update(human_fault_mode(value) for value in fault_modes(record))
            object_count.update(
                {human_object_class(value) for value in object_classes(record)}
            )
        comparison[name] = {
            "work_orders": len(records),
            "fault_work_orders": sum(has_fault(record) for record in records),
            "activities": dict(activity_count.most_common()),
            "fault_modes": dict(fault_count.most_common()),
            "object_classes": dict(object_count.most_common()),
        }
    return {"comparison": comparison}
