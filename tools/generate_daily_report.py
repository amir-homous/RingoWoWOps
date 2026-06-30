import argparse
import sqlite3
from pathlib import Path
from datetime import datetime


def fetch_all(conn, query):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query).fetchall()]


def to_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def copper_to_gold(copper):
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    gold = copper // 10000
    silver = (copper % 10000) // 100
    copper = copper % 100
    return f"{sign}{gold}g {silver}s {copper}c"


def format_ts(ts):
    ts = to_int(ts)
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def main():
    parser = argparse.ArgumentParser(description="Generate a Markdown daily report from RingoWoWOps SQLite data.")
    parser.add_argument("--db", default="data/ringo_ops.sqlite", help="SQLite database path")
    parser.add_argument("--out", default="data/processed/daily_report.md", help="Output markdown path")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)

    sessions = fetch_all(conn, "SELECT * FROM sessions")
    snapshots = fetch_all(conn, "SELECT * FROM snapshots")
    notes = fetch_all(conn, "SELECT * FROM notes")
    activities = fetch_all(conn, "SELECT * FROM activities")

    completed_sessions = [s for s in sessions if s.get("status", "") in ("completed", "") and s.get("duration_seconds", "")]
    primary_sessions = [s for s in completed_sessions if s.get("realm") == "Spineshatter" or s.get("primary_realm") in ("True", "true", "1")]

    total_duration = sum(to_int(s.get("duration_seconds")) for s in primary_sessions)
    total_gold = sum(to_int(s.get("gold_end")) - to_int(s.get("gold_start")) for s in primary_sessions)

    latest_snapshot = snapshots[-1] if snapshots else {}
    latest_level = latest_snapshot.get("level", "")
    latest_zone = latest_snapshot.get("zone", "")
    latest_gold = to_int(latest_snapshot.get("gold", 0))

    lines = []
    lines.append("# RingoWoWOps Daily Report")
    lines.append("")
    lines.append("## Current State")
    lines.append("")
    lines.append(f"- Character: {latest_snapshot.get('character', '')}")
    lines.append(f"- Realm: {latest_snapshot.get('realm', '')}")
    lines.append(f"- Level: {latest_level}")
    lines.append(f"- Zone: {latest_zone}")
    lines.append(f"- Gold: {copper_to_gold(latest_gold)}")
    lines.append("")
    lines.append("## Session Summary")
    lines.append("")
    lines.append(f"- Total sessions: {len(sessions)}")
    lines.append(f"- Completed primary sessions: {len(primary_sessions)}")
    lines.append(f"- Total tracked duration: {round(total_duration / 60, 1)} minutes")
    lines.append(f"- Net copper change: {total_gold} ({copper_to_gold(total_gold)})")
    lines.append("")
    lines.append("## Activity Counts")
    lines.append("")

    activity_counts = {}
    for activity in activities:
        name = activity.get("activity", "unknown") or "unknown"
        activity_counts[name] = activity_counts.get(name, 0) + 1

    for name, count in sorted(activity_counts.items(), key=lambda item: item[0]):
        lines.append(f"- {name}: {count}")

    lines.append("")
    lines.append("## Notes")
    lines.append("")

    if notes:
        for note in notes[-20:]:
            t = format_ts(note.get("time"))
            category = note.get("category", "general")
            text = note.get("text", "")
            lines.append(f"- {t} [{category}] {text}")
    else:
        lines.append("- No notes recorded.")

    lines.append("")
    lines.append("## AI Review Questions")
    lines.append("")
    lines.append("- Was leveling speed good for the current zone?")
    lines.append("- Did city/training time reduce efficiency too much?")
    lines.append("- Should the next session focus on questing, gathering, or city setup?")
    lines.append("- Which notes should be converted into structured events later?")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to: {out_path}")


if __name__ == "__main__":
    main()
