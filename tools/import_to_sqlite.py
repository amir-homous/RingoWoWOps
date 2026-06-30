import argparse
import csv
import sqlite3
from pathlib import Path


TABLES = {
    "sessions": "sessions.csv",
    "snapshots": "snapshots.csv",
    "notes": "notes.csv",
    "activities": "activities.csv",
}


def read_csv(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def create_table(conn, table_name, rows):
    if not rows:
        return

    columns = sorted({key for row in rows for key in row.keys()})
    column_defs = ", ".join([f'"{col}" TEXT' for col in columns])

    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(f'CREATE TABLE "{table_name}" ({column_defs})')

    placeholders = ", ".join(["?"] * len(columns))
    column_names = ", ".join([f'"{col}"' for col in columns])

    for row in rows:
        values = [row.get(col, "") for col in columns]
        conn.execute(
            f'INSERT INTO "{table_name}" ({column_names}) VALUES ({placeholders})',
            values,
        )


def main():
    parser = argparse.ArgumentParser(description="Import RingoWoWOps CSV files into SQLite.")
    parser.add_argument("csv_dir", help="Directory containing sessions.csv, snapshots.csv, notes.csv, activities.csv")
    parser.add_argument("--db", default="data/ringo_ops.sqlite", help="SQLite database output path")
    args = parser.parse_args()

    csv_dir = Path(args.csv_dir)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)

    try:
        for table, filename in TABLES.items():
            rows = read_csv(csv_dir / filename)
            create_table(conn, table, rows)
            print(f"Imported {len(rows)} rows into {table}")

        conn.commit()
        print(f"SQLite database written to: {db_path}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
