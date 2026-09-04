"""Read-only access to the official MaintIE gold knowledge graph.

The data is intentionally loaded once and queried directly.  There is no
generated cache, checksum registry, or hidden WTB answer table.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

DATA_FILE = Path(__file__).parent / "data" / "gold_release.json"

FAULT_PREFIXES = (
    "State/UndesirableState",
    "Process/UndesirableProcess",
    "Property/UndesirableProperty",
)

OBJECT_CLASS_LABELS = {
    "GuidingObject": "Lines & drives",
    "DrivingObject": "Engines & motors",
    "HoldingObject": "Structural/mounting parts",
    "GeneratingObject": "Pumps/fans/generators",
    "ControllingObject": "Valves/breakers/switches",
    "SensingObject": "Sensors & gauges",
    "TransformingObject": "Transformers/gearboxes",
    "MatterProcessingObject": "Filters & separators",
    "ProtectingObject": "Guards & protective parts",
    "CoveringObject": "Covers & seals",
    "StoringObject": "Tanks & storage",
    "PresentingObject": "Displays & alarms",
}
LABEL_TO_OBJECT_CLASS = {
    label.casefold(): raw for raw, label in OBJECT_CLASS_LABELS.items()
}

FAULT_MODE_LABELS = {
    "FailedState": "Failed/broken",
    "UndesirableState": "Faulty",
    "UndesirableProcess": "Active failure (leak/overheat)",
    "DegradedState": "Worn/degraded",
    "UndesirableProperty": "Defect (crack/hole/noise)",
}
LABEL_TO_FAULT_MODE = {
    label.casefold(): raw for raw, label in FAULT_MODE_LABELS.items()
}

# MaintIE ontology aliases used in ordinary maintenance language.  These map
# words to the ontology class that actually represents them in the release.
OBJECT_ALIASES = {
    "bearing": "JointingObject",
    "bearings": "JointingObject",
    "seal": "InfillingObject",
    "seals": "InfillingObject",
    "belt": "MechanicalEnergyGuidingObject",
    "belts": "MechanicalEnergyGuidingObject",
    "hose": "ClosedEnclosureGuidingObject",
    "hoses": "ClosedEnclosureGuidingObject",
    "filter": "MechanicalSeparatingObject",
    "filters": "MechanicalSeparatingObject",
    "pump": "LiquidFlowGeneratingObject",
    "pumps": "LiquidFlowGeneratingObject",
    "engine": "CombustionEngine",
    "engines": "CombustionEngine",
    "housing": "EnclosingObject",
    "housings": "EnclosingObject",
    "sensor": "SensingObject",
    "sensors": "SensingObject",
    "valve": "ControllingObject",
    "valves": "ControllingObject",
}


@lru_cache(maxsize=1)
def load_records() -> tuple[dict[str, Any], ...]:
    """Load the official MaintIE gold release and assign stable 1-based IDs."""
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return tuple({"wo_id": index, **record} for index, record in enumerate(raw, 1))


def entity_types(record: dict[str, Any]) -> list[str]:
    return [entity["type"] for entity in record["entities"]]


def activities(record: dict[str, Any]) -> list[str]:
    return [
        type_name.rsplit("/", 1)[-1]
        for type_name in entity_types(record)
        if type_name.startswith("Activity/")
    ]


def maintenance_activities(record: dict[str, Any]) -> list[str]:
    return [
        type_name.rsplit("/", 1)[-1]
        for type_name in entity_types(record)
        if type_name.startswith("Activity/MaintenanceActivity/")
    ]


def object_classes(record: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for type_name in entity_types(record):
        parts = type_name.split("/")
        if len(parts) >= 2 and parts[0] == "PhysicalObject":
            result.append(parts[1])
    return result


def object_types(record: dict[str, Any]) -> list[str]:
    return [
        type_name.rsplit("/", 1)[-1]
        for type_name in entity_types(record)
        if type_name.startswith("PhysicalObject/")
    ]


def fault_modes(record: dict[str, Any]) -> list[str]:
    modes: list[str] = []
    for type_name in entity_types(record):
        if type_name.startswith(FAULT_PREFIXES):
            modes.append(type_name.rsplit("/", 1)[-1])
    return modes


def has_fault(record: dict[str, Any]) -> bool:
    return bool(fault_modes(record))


def entity_mentions(record: dict[str, Any]) -> list[dict[str, Any]]:
    tokens = record["tokens"]
    return [
        {
            "text": " ".join(tokens[entity["start"] : entity["end"]]),
            "type": entity["type"],
        }
        for entity in record["entities"]
    ]


def patient_object_classes(record: dict[str, Any], activity: str) -> Iterable[str]:
    """Yield object classes linked as patients of one activity entity."""
    entities = record["entities"]
    target = activity.casefold()
    for relation in record["relations"]:
        if relation["type"] != "hasParticipant/hasPatient":
            continue
        head = entities[relation["head"]]["type"]
        tail = entities[relation["tail"]]["type"]
        if head.rsplit("/", 1)[-1].casefold() != target:
            continue
        parts = tail.split("/")
        if len(parts) >= 2 and parts[0] == "PhysicalObject":
            yield parts[1]


def patient_object_types(record: dict[str, Any], activity: str) -> Iterable[str]:
    entities = record["entities"]
    target = activity.casefold()
    for relation in record["relations"]:
        if relation["type"] != "hasParticipant/hasPatient":
            continue
        head = entities[relation["head"]]["type"]
        tail = entities[relation["tail"]]["type"]
        if head.rsplit("/", 1)[-1].casefold() == target and tail.startswith(
            "PhysicalObject/"
        ):
            yield tail.rsplit("/", 1)[-1]


def human_object_class(raw: str) -> str:
    return OBJECT_CLASS_LABELS.get(raw, raw)


def human_fault_mode(raw: str) -> str:
    return FAULT_MODE_LABELS.get(raw, raw)


def normalize_object_term(term: str) -> str:
    folded = term.strip().casefold()
    if folded in LABEL_TO_OBJECT_CLASS:
        return LABEL_TO_OBJECT_CLASS[folded]
    return OBJECT_ALIASES.get(folded, term.strip())


def normalize_fault_mode(term: str) -> str:
    folded = term.strip().casefold()
    aliases = {
        "failed": "FailedState",
        "broken": "FailedState",
        "seized": "FailedState",
        "faulty": "UndesirableState",
        "leak": "UndesirableProcess",
        "leaking": "UndesirableProcess",
        "overheat": "UndesirableProcess",
        "worn": "DegradedState",
        "degraded": "DegradedState",
        "crack": "UndesirableProperty",
        "cracked": "UndesirableProperty",
        "defect": "UndesirableProperty",
    }
    if folded in LABEL_TO_FAULT_MODE:
        return LABEL_TO_FAULT_MODE[folded]
    return aliases.get(folded, term.strip())
