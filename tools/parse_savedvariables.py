import argparse
import csv
from pathlib import Path

from lupa import LuaRuntime


def lua_table_to_py(obj):
    if hasattr(obj, "items"):
        keys = list(obj.keys())
        is_array = keys and all(isinstance(k, int) for k in keys)

        if is_array:
            return [lua_table_to_py(obj[i]) for i in sorted(keys)]

        return {str(k): lua_table_to_py(v) for k, v in obj.items()}

    return obj


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Parse RingoWoWOps SavedVariables.lua into CSV files.")
    parser.add_argument("input", help="Path to RingoWoWOps.lua SavedVariables file")
    parser.add_argument("--out", default="data/processed", help="Output folder")
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.out)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(input_path.read_text(encoding="utf-8"))

    db = lua.globals().RingoWoWOpsDB
    data = lua_table_to_py(db)

    write_csv(out_dir / "sessions.csv", data.get("sessions", []))
    write_csv(out_dir / "snapshots.csv", data.get("snapshots", []))
    write_csv(out_dir / "notes.csv", data.get("notes", []))
    write_csv(out_dir / "activities.csv", data.get("activities", []))
    write_csv(out_dir / "events.csv", data.get("events", []))

    print(f"Parsed: {input_path}")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
