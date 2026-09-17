"""Shared normalization rules for RingoWoWOps source records."""

from __future__ import annotations

import hashlib
import json
from typing import Any


PHASE1_DATASETS = ("sessions", "snapshots", "notes", "activities", "events")
DATASETS = PHASE1_DATASETS + ("ledger_entries", "ledger_voids")

ACTIVITY_ALIASES = {
    "quest": "questing",
    "questin": "questing",
    "questing": "questing",
    "train": "training",
    "training": "training",
    "herb": "gathering",
    "herbalism": "gathering",
    "mine": "gathering",
    "mining": "gathering",
    "gather": "gathering",
    "gathering": "gathering",
    "ah": "auction",
    "auction": "auction",
    "bank": "banking",
    "banking": "banking",
    "dungeon": "dungeon",
    "raid": "raid",
    "team": "team",
    "idle": "idle",
    "other": "other",
}

REQUIRED_FIELDS = {
    "sessions": ("started_at", "character", "realm"),
    "snapshots": ("time", "character", "realm"),
    "notes": ("time", "character", "realm", "text"),
    "activities": ("time", "character", "realm", "activity"),
    "events": ("time", "character", "realm", "type"),
}

INTEGER_FIELDS = {
    "started_at", "ended_at", "duration_seconds", "level_start", "level_end",
    "xp_start", "xp_end", "gold_start", "gold_end", "time", "level", "xp",
    "xp_max", "rested_xp", "gold", "bags_free",
}

BOOLEAN_FIELDS = {"primary_realm"}

PROVENANCE_FIELDS = {
    "record_id", "source_file_sha256", "source_schema_version",
    "source_record_index", "source_dataset", "import_batch_id",
}


def canonical_activity(value: Any) -> str:
    original = str(value or "other").strip().lower() or "other"
    return ACTIVITY_ALIASES.get(original, original)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def logical_payload(dataset: str, row: dict[str, Any]) -> dict[str, Any]:
    """Return source-domain fields only, for deterministic compatibility IDs."""
    excluded = PROVENANCE_FIELDS | {"activity_original", "validation_status"}
    return {
        key: _canonical_value(value)
        for key, value in sorted(row.items())
        if key not in excluded and value not in (None, "")
    }


def compatibility_id(dataset: str, row: dict[str, Any], duplicate_ordinal: int = 0) -> str:
    payload = json.dumps(
        logical_payload(dataset, row), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    )
    digest = hashlib.sha256(f"{dataset}\n{payload}\n{duplicate_ordinal}".encode("utf-8")).hexdigest()
    return f"legacy-{dataset[:-1]}-{digest[:32]}"


def coerce_scalar(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in INTEGER_FIELDS:
        if value == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value
    if field in BOOLEAN_FIELDS:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no", ""}:
            return False
    return value


def normalize_record(
    dataset: str,
    source_row: dict[str, Any],
    *,
    source_file_sha256: str,
    source_schema_version: str,
    source_record_index: int,
    duplicate_ordinal: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    row = {str(key): coerce_scalar(str(key), value) for key, value in source_row.items()}
    warnings: list[dict[str, Any]] = []

    activity_fields = [field for field in ("activity", "activity_start", "activity_end") if field in row]
    for field in activity_fields:
        original = str(row.get(field) or "")
        if field == "activity":
            row["activity_original"] = original
        row[field] = canonical_activity(original)

    supplied_id = str(row.get("id") or row.get("record_id") or "").strip()
    row["record_id"] = supplied_id or compatibility_id(dataset, row, duplicate_ordinal)
    if dataset == "sessions" and not row.get("id"):
        row["id"] = row["record_id"]

    row["source_file_sha256"] = source_file_sha256
    row["source_schema_version"] = source_schema_version or "unknown"
    row["source_record_index"] = source_record_index
    row["source_dataset"] = dataset

    for field in REQUIRED_FIELDS[dataset]:
        if row.get(field) in (None, ""):
            warnings.append({
                "dataset": dataset,
                "source_record_index": source_record_index,
                "record_id": row["record_id"],
                "severity": "warning",
                "code": "missing_required_field",
                "field": field,
                "message": f"Missing required field: {field}",
            })

    for field in INTEGER_FIELDS.intersection(row):
        value = row.get(field)
        if value not in (None, "") and not isinstance(value, int):
            warnings.append({
                "dataset": dataset,
                "source_record_index": source_record_index,
                "record_id": row["record_id"],
                "severity": "warning",
                "code": "invalid_integer",
                "field": field,
                "message": f"Expected integer, retained original value: {value!r}",
            })

    if dataset == "sessions" and not row.get("status"):
        row["status"] = "completed" if row.get("ended_at") and row.get("duration_seconds") is not None else "incomplete"
        warnings.append({
            "dataset": dataset,
            "source_record_index": source_record_index,
            "record_id": row["record_id"],
            "severity": "info",
            "code": "legacy_session_status_inferred",
            "field": "status",
            "message": f"Legacy status inferred as {row['status']}",
        })
    if dataset == "sessions" and not row.get("ended_at"):
        warnings.append({
            "dataset": dataset,
            "source_record_index": source_record_index,
            "record_id": row["record_id"],
            "severity": "warning",
            "code": "incomplete_session",
            "field": "ended_at",
            "message": "Session has no end timestamp and remains visible as incomplete",
        })

    row["validation_status"] = "warning" if any(w["severity"] == "warning" for w in warnings) else "valid"
    return row, warnings
