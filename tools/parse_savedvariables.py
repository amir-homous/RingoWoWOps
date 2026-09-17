import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from lupa import LuaRuntime

from data_model import DATASETS, logical_payload, normalize_record
from ledger import LEDGER_DATASETS, normalize_ledger, payload


def lua_table_to_py(obj):
    if hasattr(obj, "items"):
        keys = list(obj.keys())
        is_array = bool(keys) and all(isinstance(key, int) for key in keys)
        if is_array:
            return [lua_table_to_py(obj[key]) for key in sorted(keys)]
        return {str(key): lua_table_to_py(value) for key, value in obj.items()}
    return obj


def parse_savedvariables(path: Path) -> dict[str, Any]:
    """Parse a trusted local WoW SavedVariables file.

    Lupa executes Lua. The runtime is stripped of common file/process/network entry
    points, but callers must still treat the input as trusted local data.
    """
    source = path.read_text(encoding="utf-8-sig")
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("os=nil; io=nil; package=nil; require=nil; dofile=nil; loadfile=nil")
    lua.execute(source)
    db = lua.globals().RingoWoWOpsDB
    if db is None:
        raise ValueError("RingoWoWOpsDB was not defined by the SavedVariables file")
    data = lua_table_to_py(db)
    if not isinstance(data, dict):
        raise ValueError("RingoWoWOpsDB must be a Lua table")
    return data


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_database(data: dict[str, Any], source_path: Path) -> tuple[dict[str, list[dict]], list[dict], dict]:
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    schema_version = str(data.get("version") or "unknown")
    normalized: dict[str, list[dict]] = {}
    warnings: list[dict] = []

    for dataset in DATASETS:
        source_rows = data.get(dataset, [])
        if source_rows in (None, {}):
            source_rows = []
        if not isinstance(source_rows, list):
            warnings.append({
                "dataset": dataset, "source_record_index": "", "record_id": "",
                "severity": "error", "code": "invalid_dataset_type", "field": "",
                "message": f"Expected array, retained dataset description: {type(source_rows).__name__}",
                "raw_record": repr(source_rows),
            })
            normalized[dataset] = []
            continue

        seen_payloads: Counter[str] = Counter()
        output_rows = []
        ledger_ids = {}
        for index, source_row in enumerate(source_rows, start=1):
            if not isinstance(source_row, dict):
                warnings.append({
                    "dataset": dataset, "source_record_index": index, "record_id": "",
                    "severity": "error", "code": "invalid_record_type", "field": "",
                    "message": f"Expected table, retained raw representation of {type(source_row).__name__}",
                    "raw_record": repr(source_row),
                })
                continue
            if dataset in LEDGER_DATASETS:
                row, errors = normalize_ledger(dataset, source_row)
                row.update(source_file_sha256=source_hash, source_schema_version=schema_version,
                           source_record_index=index, source_dataset=dataset,
                           validation_status="error" if errors else "valid",
                           raw_record=json.dumps(source_row, sort_keys=True, ensure_ascii=False))
                for message in errors:
                    warnings.append(dict(dataset=dataset, source_record_index=index,
                        record_id=row.get("record_id"), severity="error", code="invalid_ledger_record",
                        field="", message=message, raw_record=row["raw_record"]))
                prior = ledger_ids.get(str(row.get("record_id")))
                if prior and payload(dataset, prior) != payload(dataset, row):
                    warnings.append(dict(dataset=dataset, source_record_index=index,
                        record_id=row.get("record_id"), severity="error", code="ledger_id_conflict",
                        field="record_id", message="Same ID with conflicting payload", raw_record=row["raw_record"]))
                ledger_ids.setdefault(str(row.get("record_id")), row)
                output_rows.append(row)
                continue
            payload_key = json.dumps(logical_payload(dataset, source_row), sort_keys=True, ensure_ascii=False, default=str)
            ordinal = seen_payloads[payload_key]
            seen_payloads[payload_key] += 1
            row, row_warnings = normalize_record(
                dataset, source_row,
                source_file_sha256=source_hash,
                source_schema_version=schema_version,
                source_record_index=index,
                duplicate_ordinal=ordinal,
            )
            output_rows.append(row)
            warnings.extend(row_warnings)
        normalized[dataset] = output_rows

    metadata = {
        "parser_format_version": 2,
        "source_file": source_path.name,
        "source_file_sha256": source_hash,
        "source_schema_version": schema_version,
        "record_counts": {dataset: len(normalized[dataset]) for dataset in DATASETS},
        "validation_counts": dict(Counter(item["severity"] for item in warnings)),
    }
    return normalized, warnings, metadata


def export_normalized(input_path: Path, out_dir: Path) -> dict:
    data = parse_savedvariables(input_path)
    normalized, warnings, metadata = normalize_database(data, input_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for dataset in DATASETS:
        write_csv(out_dir / f"{dataset}.csv", normalized[dataset])
    write_csv(out_dir / "validation_errors.csv", warnings)
    (out_dir / "source_manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def main():
    parser = argparse.ArgumentParser(description="Parse trusted RingoWoWOps SavedVariables into normalized CSV files.")
    parser.add_argument("input", help="Path to a trusted local RingoWoWOps.lua SavedVariables file")
    parser.add_argument("--out", default="data/processed", help="Output folder")
    args = parser.parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    metadata = export_normalized(input_path, Path(args.out).resolve())
    print(f"Parsed trusted input: {input_path}")
    print(f"Schema version: {metadata['source_schema_version']}")
    print(f"Records: {sum(metadata['record_counts'].values())}; validation: {metadata['validation_counts']}")
    print(f"Output: {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
