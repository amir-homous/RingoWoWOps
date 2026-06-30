import argparse
import sqlite3
from pathlib import Path
from datetime import datetime


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

CITY_ACTIVITIES = {"training", "auction", "banking"}


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


def normalize_activity(value):
    value = (value or "other").strip().lower()
    return ACTIVITY_ALIASES.get(value, value or "other")


def is_primary_row(row):
    if row.get("realm") == "Spineshatter":
        return True
    if str(row.get("primary_realm", "")).lower() in ("true", "1", "yes"):
        return True
    return False


def is_completed_session(row):
    return bool(row.get("duration_seconds")) and row.get("status", "completed") in ("completed", "")


def latest_by_time(rows):
    if not rows:
        return {}
    return max(rows, key=lambda row: to_int(row.get("time", row.get("ended_at", row.get("started_at", 0)))))


def strongest_current_snapshot(snapshots):
    primary = [s for s in snapshots if is_primary_row(s)]
    if not primary:
        primary = snapshots[:]

    if not primary:
        return {}

    # Prefer the newest snapshot with valid level and non-empty zone.
    valid = [s for s in primary if to_int(s.get("level", 0)) > 0 and s.get("zone")]
    if valid:
        return latest_by_time(valid)

    return latest_by_time(primary)


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

    primary_sessions = [s for s in sessions if is_completed_session(s) and is_primary_row(s)]
    primary_snapshots = [s for s in snapshots if is_primary_row(s)]

    total_duration = sum(to_int(s.get("duration_seconds")) for s in primary_sessions)
    total_gold_raw = sum(to_int(s.get("gold_end")) - to_int(s.get("gold_start")) for s in primary_sessions)

    latest_snapshot = strongest_current_snapshot(snapshots)
    latest_level = to_int(latest_snapshot.get("level", 0))
    latest_zone = latest_snapshot.get("zone", "")
    latest_gold = to_int(latest_snapshot.get("gold", 0))
    latest_time = latest_snapshot.get("time", "")

    level_values = [to_int(s.get("level")) for s in primary_snapshots if to_int(s.get("level")) > 0]
    level_start = min(level_values) if level_values else latest_level
    level_end = max(level_values) if level_values else latest_level
    levels_gained = max(0, level_end - level_start)

    # Use the highest tracked level if newest snapshot looks stale or lower than max level.
    if level_end > latest_level:
        latest_level = level_end

    # Prefer the latest non-zero gold if current snapshot is zero but older snapshots had gold.
    gold_values = [to_int(s.get("gold")) for s in primary_snapshots if to_int(s.get("gold")) > 0]
    gold_warning = None
    if latest_gold == 0 and gold_values:
        latest_gold = gold_values[-1]
        gold_warning = "Latest snapshot had 0 copper; using latest known non-zero gold from tracked data."

    duration_hours = total_duration / 3600 if total_duration else 0
    levels_per_hour = levels_gained / duration_hours if duration_hours else 0
    gold_per_hour_raw = total_gold_raw / duration_hours if duration_hours else 0

    activity_counts = {}
    for activity in activities:
        if not is_primary_row(activity):
            continue
        name = normalize_activity(activity.get("activity"))
        activity_counts[name] = activity_counts.get(name, 0) + 1

    city_count = sum(count for name, count in activity_counts.items() if name in CITY_ACTIVITIES)
    action_count = sum(activity_counts.values())
    city_ratio = (city_count / action_count * 100) if action_count else 0

    gift_notes = [n for n in notes if (n.get("category") == "gift" or str(n.get("text", "")).lower().startswith("gift"))]
    training_notes = [n for n in notes if "training" in str(n.get("text", "")).lower()]
    ah_notes = [n for n in notes if (n.get("category") == "ah" or "auction" in str(n.get("text", "")).lower() or "scan" in str(n.get("text", "")).lower())]

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
    lines.append(f"- Latest snapshot time: {format_ts(latest_time)}")
    if gold_warning:
        lines.append(f"- Data warning: {gold_warning}")

    lines.append("")
    lines.append("## Progress Summary")
    lines.append("")
    lines.append(f"- Level range in tracked data: {level_start} -> {level_end}")
    lines.append(f"- Levels gained in primary data: {levels_gained}")
    lines.append(f"- Total tracked duration: {round(total_duration / 60, 1)} minutes")
    lines.append(f"- Estimated levels/hour: {round(levels_per_hour, 2)}")

    lines.append("")
    lines.append("## Economy Summary")
    lines.append("")
    lines.append(f"- Raw net copper change: {total_gold_raw} ({copper_to_gold(total_gold_raw)})")
    lines.append(f"- Raw gold/hour: {copper_to_gold(int(gold_per_hour_raw))}/hour")
    if gift_notes:
        lines.append("- Gift notes detected: yes")
        lines.append("- Gold/hour warning: gift income should be excluded from farming analysis.")
    else:
        lines.append("- Gift notes detected: no")

    lines.append("")
    lines.append("## Activity Summary")
    lines.append("")
    if activity_counts:
        for name, count in sorted(activity_counts.items(), key=lambda item: item[0]):
            lines.append(f"- {name}: {count}")
    else:
        lines.append("- No activity records.")
    lines.append("")
    lines.append(f"- City/setup activity ratio by activity events: {round(city_ratio, 1)}%")

    lines.append("")
    lines.append("## Important Notes")
    lines.append("")
    if notes:
        for note in notes[-25:]:
            t = format_ts(note.get("time"))
            category = note.get("category", "general") or "general"
            text = note.get("text", "")
            lines.append(f"- {t} [{category}] {text}")
    else:
        lines.append("- No notes recorded.")

    lines.append("")
    lines.append("## Detected Operational Events")
    lines.append("")
    lines.append(f"- Gift events: {len(gift_notes)}")
    lines.append(f"- Training/setup events: {len(training_notes)}")
    lines.append(f"- AH/scan events: {len(ah_notes)}")

    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    if latest_level < 12:
        lines.append("- Continue Eversong Woods until around level 12.")
        lines.append("- Keep activity as `questing` unless you intentionally switch to gathering/training/auction.")
    elif latest_level < 20:
        lines.append("- Move toward Ghostlands / Tranquillien and continue questing there.")
        lines.append("- Gather nodes only if they are on-route or require minimal detour.")
    else:
        lines.append("- Continue the planned Horde leveling route and begin watching dungeon opportunities.")

    lines.append("")
    lines.append("## AI Review Questions")
    lines.append("")
    lines.append("- Was the latest session mostly questing or city setup?")
    lines.append("- Did the gold change come from gameplay, training cost, AH, or gift?")
    lines.append("- Which notes should become structured commands later?")
    lines.append("- Is the next best step leveling, profession setup, AH, or travel?")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to: {out_path}")


if __name__ == "__main__":
    main()
