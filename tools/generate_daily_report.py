import argparse
import sqlite3
import json
from ledger_report import economy, render_economy
import farm
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def to_int(value, default=0):
    try:
        return default if value in (None, "") else int(float(value))
    except (TypeError, ValueError):
        return default


def copper_to_gold(copper):
    sign = "-" if copper < 0 else ""
    copper = abs(int(copper))
    return f"{sign}{copper // 10000}g {(copper % 10000) // 100}s {copper % 100}c"


def resolve_timezone(timezone_name: str) -> tzinfo:
    if timezone_name == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        # Iran abolished seasonal clock changes in 2022. This standard-library
        # fallback is correct for this project's 2026+ default reporting dates.
        if timezone_name == "Asia/Tehran":
            return timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")
        raise ValueError(f"Unknown timezone {timezone_name!r}; install system timezone data or choose a supported IANA timezone") from exc


def report_window(report_date: str | None, timezone_name: str) -> tuple[date, int, int, tzinfo]:
    tz = resolve_timezone(timezone_name)
    selected = date.fromisoformat(report_date) if report_date else datetime.now(tz).date()
    start = datetime.combine(selected, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1)
    return selected, int(start.timestamp()), int(end.timestamp()), tz


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _scope_sql(character: str | None, realm: str | None, alias: str = "") -> tuple[str, list[str]]:
    prefix = f"{alias}." if alias else ""
    clauses, values = [], []
    if character:
        clauses.append(f"{prefix}character = ?")
        values.append(character)
    if realm:
        clauses.append(f"{prefix}realm = ?")
        values.append(realm)
    return (" AND " + " AND ".join(clauses)) if clauses else "", values


def _rows(conn, table, time_column, start_ts, end_ts, character, realm):
    if not _table_exists(conn, table):
        return []
    scope, params = _scope_sql(character, realm)
    return [dict(row) for row in conn.execute(
        f'SELECT * FROM "{table}" WHERE {time_column} >= ? AND {time_column} < ?{scope} ORDER BY {time_column}, record_id',
        [start_ts, end_ts, *params],
    )]


def generate_report(
    db_path: Path,
    out_path: Path,
    *,
    report_date: str | None = None,
    timezone_name: str = "UTC",
    character: str | None = None,
    realm: str | None = None,
    end_date: str | None = None,
) -> dict:
    selected, start_ts, end_ts, tz = report_window(report_date, timezone_name)
    if end_date:
        _, end_ts, _, _ = report_window(end_date, timezone_name)
        if end_ts <= start_ts:
            raise ValueError("--end-date is exclusive and must follow --date")
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sessions = _rows(conn, "sessions", "started_at", start_ts, end_ts, character, realm)
        snapshots = _rows(conn, "snapshots", "time", start_ts, end_ts, character, realm)
        notes = _rows(conn, "notes", "time", start_ts, end_ts, character, realm)
        activities = _rows(conn, "activities", "time", start_ts, end_ts, character, realm)
        events = _rows(conn, "events", "time", start_ts, end_ts, character, realm)
        ledger_entries = _rows(conn, "ledger_entries", "time", start_ts, end_ts + 1, character, realm)
        observations = _rows(conn, "snapshots", "time", start_ts, end_ts + 1, character, realm)
        void_ids = {r[0] for r in conn.execute("SELECT entry_id FROM ledger_voids")} if _table_exists(conn,"ledger_voids") else set()
        farm_summary = farm.summarize(farm.current_runs(conn),start_ts,end_ts,character,realm)
        findings = []
        if _table_exists(conn,"validation_errors"):
            findings = [dict(r) for r in conn.execute("SELECT record_id,raw_record FROM validation_errors WHERE dataset IN ('ledger_entries','ledger_voids') AND severity='error'")]

    finally:
        conn.close()

    identities = sorted({(row.get("character") or "", row.get("realm") or "") for rows in (sessions, snapshots, notes, activities, events, ledger_entries, observations, farm_summary["rows"]) for row in rows})
    if not character and len({name for name, _ in identities if name}) > 1:
        names = ", ".join(name for name, _ in identities)
        raise ValueError(f"Report scope contains multiple characters ({names}); specify --character")
    if not realm and len({name for _, name in identities if name}) > 1:
        names = ", ".join(name for _, name in identities)
        raise ValueError(f"Report scope contains multiple realms ({names}); specify --realm")

    review = False
    for finding in findings:
        if any(r['record_id'] == finding['record_id'] for r in ledger_entries):
            review = True
        try:
            raw = json.loads(finding['raw_record'] or '{}')
            if isinstance(raw, dict) and any(r['record_id'] == raw.get('entry_id') for r in ledger_entries):
                review = True
            if isinstance(raw, dict) and (not character or raw.get('character') == character) and (not realm or raw.get('realm') == realm):
                when = int(raw.get('time', -1))
                review |= start_ts <= when < end_ts
        except (TypeError, ValueError):
            pass
    econ = economy(ledger_entries, observations, void_ids, start_ts, end_ts, review)

    complete = [row for row in sessions if row.get("ended_at") is not None and row.get("duration_seconds") is not None and row.get("status") in ("completed", "")]
    incomplete = [row for row in sessions if row not in complete]
    total_duration = sum(to_int(row.get("duration_seconds")) for row in complete)
    latest = snapshots[-1] if snapshots else {}

    def fmt_ts(value):
        return datetime.fromtimestamp(to_int(value), tz=timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z") if value else ""

    lines = [
        "# RingoWoWOps Daily Report", "",
        "## Report Scope", "",
        f"- Window type: {'Selected date range' if end_date else 'Calendar day'}",
        f"- Date: {selected.isoformat()}",
        f"- Exclusive end date: {end_date or datetime.fromtimestamp(end_ts, tz).date().isoformat()}",
        f"- Resolved identity: {identities[0][0]}@{identities[0][1]}" if len(identities) == 1 else "- Resolved identity: no observations or records",
        f"- Timezone: {timezone_name}",
        f"- Character filter: {character or 'auto (single-character scope required)'}",
        f"- Realm filter: {realm or 'auto (single-realm scope required)'}",
        f"- UTC interval: {datetime.fromtimestamp(start_ts, timezone.utc).isoformat()} to {datetime.fromtimestamp(end_ts, timezone.utc).isoformat()}", "",
        "## Current State", "",
        f"- Character: {latest.get('character', character or '')}",
        f"- Realm: {latest.get('realm', realm or '')}",
        f"- Level: {latest.get('level', '')}",
        f"- Zone: {latest.get('zone', '')}",
        f"- Exact observed money: {copper_to_gold(to_int(latest.get('gold')))}" if latest else "- Exact observed money: Missing",
        f"- Latest snapshot: {fmt_ts(latest.get('time'))}" if latest else "- Latest snapshot: Missing", "",
        "## Session Summary", "",
        f"- Completed sessions started in scope: {len(complete)}",
        f"- Incomplete sessions started in scope: {len(incomplete)}",
        f"- Derived tracked duration: {round(total_duration / 60, 1)} minutes", "",
        *render_economy(econ, copper_to_gold, fmt_ts),
        *farm.render(farm_summary, copper_to_gold, fmt_ts),
        "## Activity Records", "",
    ]
    counts = {}
    for row in activities:
        key = row.get("activity") or "other"
        counts[key] = counts.get(key, 0) + 1
    lines.extend([f"- {key}: {counts[key]} event(s)" for key in sorted(counts)] or ["- No activity records in scope."])
    lines.extend(["", "## Notes", ""])
    lines.extend([f"- {fmt_ts(row.get('time'))} [{row.get('category') or 'general'}] {row.get('text') or ''}" for row in notes] or ["- No notes in scope."])
    lines.extend(["", "## Structured Events", ""])
    lines.extend([f"- {fmt_ts(row.get('time'))} [{row.get('type') or 'unknown'}] {row.get('text') or ''}" for row in events] or ["- No structured events in scope."])
    lines.extend([
        "", "## Data Quality", "",
        "- Exact: timestamps and point-in-time game-state observations captured by the addon.",
        "- Derived: durations and raw balance changes calculated from captured values.",
        "- Manual: notes and structured events entered by the player.",
        "- Estimated: explicitly marked ledger amounts and player material costs remain separate.",
        "- Missing: inventory valuation and attributable activity profitability.",
        f"- Records in scope: {len(sessions)} sessions, {len(snapshots)} snapshots, {len(notes)} notes, {len(activities)} activities, {len(events)} events.",
        "", "## Neutral Next Step", "",
        "- Review incomplete sessions and validation warnings before interpreting trends.",
        "- Review ledger omissions and observation coverage before interpreting cash totals.",
    ])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"farm": farm_summary, "economy": econ, "date": selected.isoformat(), "timezone": timezone_name, "identities": identities, "counts": {"sessions": len(sessions), "snapshots": len(snapshots), "notes": len(notes), "activities": len(activities), "events": len(events), "ledger_entries": len(econ["active"]) + len(econ["voided"]), "ledger_voids": len(econ["voided"])}}


def main():
    parser = argparse.ArgumentParser(description="Generate a scoped calendar-day Markdown report.")
    parser.add_argument("--db", default="data/ringo_ops.sqlite")
    parser.add_argument("--out", default="data/processed/daily_report.md")
    parser.add_argument("--date", help="Calendar date in YYYY-MM-DD; defaults to today in --timezone")
    parser.add_argument("--end-date", help="Exclusive end calendar date for a selected range")
    parser.add_argument("--timezone", default="UTC", help="IANA timezone name")
    parser.add_argument("--character")
    parser.add_argument("--realm")
    args = parser.parse_args()
    result = generate_report(Path(args.db), Path(args.out), report_date=args.date, timezone_name=args.timezone, character=args.character, realm=args.realm, end_date=args.end_date)
    print(f"Report written: {Path(args.out).resolve()} ({result['date']} {result['timezone']})")


if __name__ == "__main__":
    main()
