"""Local guild roster, manual raid event, and WCL attendance operations."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from import_to_sqlite import apply_migrations, backup_database
from wcl import external_character_key, normalize_identity


class RosterError(RuntimeError):
    pass


REQUIRED_FIELDS = ("member_id", "member_display_name", "game_version", "region", "realm", "character_name")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def guild_id(name: str, game_version: str, region: str, realm: str) -> str:
    parts = (str(game_version).casefold(), str(region).casefold(), normalize_identity(realm), normalize_identity(name))
    if not all(parts):
        raise RosterError("Guild identity fields must be nonempty")
    return "guild/" + "/".join(parts)


def _clean(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _reject(conn: sqlite3.Connection, path: Path, row_number: int, row: dict[str, Any], code: str, message: str) -> None:
    raw = json.dumps(row, sort_keys=True, ensure_ascii=False)
    key = "roster-reject-" + hashlib.sha256(f"{path.resolve()}\n{row_number}\n{code}\n{raw}".encode()).hexdigest()[:32]
    conn.execute("INSERT OR IGNORE INTO roster_import_rejections VALUES(?,?,?,?,?,?,?)",
                 (key, str(path.resolve()), row_number, code, message, raw, utc_now()))


def import_roster(path: Path, db_path: Path, *, guild_name: str = "Butter & Jam") -> dict[str, int | str | None]:
    if not path.exists():
        raise RosterError(f"Roster input does not exist: {path}")
    backup = backup_database(db_path)
    conn = sqlite3.connect(db_path, timeout=1.0)
    conn.execute("PRAGMA foreign_keys=ON")
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "rejected": 0}
    try:
        apply_migrations(conn)
        conn.execute("BEGIN IMMEDIATE")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing_headers = [field for field in REQUIRED_FIELDS if field not in (reader.fieldnames or [])]
            if missing_headers:
                raise RosterError("Roster CSV missing columns: " + ", ".join(missing_headers))
            for row_number, row in enumerate(reader, 2):
                missing = [field for field in REQUIRED_FIELDS if not _clean(row.get(field))]
                if missing:
                    _reject(conn, path, row_number, row, "missing_required", "Missing: " + ", ".join(missing))
                    counts["rejected"] += 1
                    continue
                member_id = _clean(row["member_id"])
                game = _clean(row["game_version"]).casefold()
                region = _clean(row["region"]).casefold()
                realm = _clean(row["realm"])
                character = _clean(row["character_name"])
                main_alt = (_clean(row.get("main_alt")) or "unspecified").casefold()
                if main_alt not in ("main", "alt", "unspecified"):
                    _reject(conn, path, row_number, row, "invalid_main_alt", "main_alt must be main, alt, or unspecified")
                    counts["rejected"] += 1
                    continue
                gid = guild_id(guild_name, game, region, realm)
                char_key = external_character_key(game, region, realm, character)
                now = utc_now()
                conn.execute("INSERT OR IGNORE INTO guilds VALUES(?,?,?,?,?,?,?,1)",
                             (gid, guild_name, normalize_identity(guild_name), game, region, realm, normalize_identity(realm)))
                owner = conn.execute("SELECT member_id FROM guild_characters WHERE external_character_key=?", (char_key,)).fetchone()
                if owner and owner[0] != member_id:
                    _reject(conn, path, row_number, row, "character_owner_conflict", "Character is already owned by another member")
                    counts["rejected"] += 1
                    continue
                member_values = (_clean(row["member_display_name"]), normalize_identity(row["member_display_name"]),
                                 _clean(row.get("discord_user_id")), _clean(row.get("member_status")) or "active",
                                 _clean(row.get("notes")))
                existing_member = conn.execute("SELECT guild_id,display_name,normalized_display_name,discord_user_id,membership_status,notes FROM guild_members WHERE member_id=?", (member_id,)).fetchone()
                if existing_member and existing_member[0] != gid:
                    _reject(conn, path, row_number, row, "member_guild_conflict", "Member ID belongs to another guild context")
                    counts["rejected"] += 1
                    continue
                changed = False
                if not existing_member:
                    conn.execute("INSERT INTO guild_members VALUES(?,?,?,?,?,?,?,?,?)", (member_id, gid, *member_values, now, now))
                    counts["inserted"] += 1; changed = True
                elif tuple(existing_member[1:]) != member_values:
                    conn.execute("UPDATE guild_members SET display_name=?,normalized_display_name=?,discord_user_id=?,membership_status=?,notes=?,updated_at=? WHERE member_id=?", (*member_values, now, member_id))
                    counts["updated"] += 1; changed = True
                char_values = (gid, member_id, game, region, realm, normalize_identity(realm), character,
                               normalize_identity(character), _clean(row.get("class")), _clean(row.get("primary_role")),
                               main_alt,
                               _clean(row.get("character_status")) or "active")
                existing_char = conn.execute("SELECT guild_id,member_id,game_version,region,realm,normalized_realm,character_name,normalized_character_name,class,primary_role,main_alt,character_status FROM guild_characters WHERE external_character_key=?", (char_key,)).fetchone()
                if not existing_char:
                    conn.execute("INSERT INTO guild_characters VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (char_key, *char_values, now, now))
                    if not changed: counts["inserted"] += 1
                    changed = True
                elif tuple(existing_char) != char_values:
                    conn.execute("UPDATE guild_characters SET class=?,primary_role=?,main_alt=?,character_status=?,updated_at=? WHERE external_character_key=?",
                                 (char_values[8], char_values[9], char_values[10], char_values[11], now, char_key))
                    if not changed: counts["updated"] += 1
                    changed = True
                if not changed:
                    counts["unchanged"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    counts["backup"] = str(backup) if backup else None
    return counts


def upsert_event(db_path: Path, *, source: str, external_id: str, title: str, scheduled_at: str | None,
                 instance: str | None, game_version: str, region: str, realm: str) -> dict[str, str]:
    source = source.strip().casefold(); external_id = external_id.strip()
    if not source or not external_id or not title.strip(): raise RosterError("Event source, external ID, and title are required")
    key = f"{source}/{external_id}"
    conn = sqlite3.connect(db_path); conn.execute("PRAGMA foreign_keys=ON")
    try:
        apply_migrations(conn); conn.execute("BEGIN IMMEDIATE"); now = utc_now()
        values = (source, external_id, title.strip(), _clean(scheduled_at), _clean(instance), game_version.casefold(), region.casefold(), realm.strip())
        old = conn.execute("SELECT external_source,external_event_id,title,scheduled_at,instance,game_version,region,realm FROM raid_events WHERE event_key=?", (key,)).fetchone()
        if old is None:
            conn.execute("INSERT INTO raid_events VALUES(?,?,?,?,?,?,?,?,?,?,?)", (key, *values, now, now)); action = "inserted"
        elif tuple(old) == values: action = "unchanged"
        else:
            conn.execute("UPDATE raid_events SET title=?,scheduled_at=?,instance=?,game_version=?,region=?,realm=?,updated_at=? WHERE event_key=?", (values[2], *values[3:], now, key)); action = "updated"
        conn.commit(); return {"event_key": key, "action": action}
    except Exception: conn.rollback(); raise
    finally: conn.close()


def link_report(db_path: Path, event_key: str, report_code: str) -> str:
    conn = sqlite3.connect(db_path); conn.execute("PRAGMA foreign_keys=ON")
    try:
        apply_migrations(conn); conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM raid_events WHERE event_key=?", (event_key,)).fetchone(): raise RosterError(f"Raid event not found: {event_key}")
        if not conn.execute("SELECT 1 FROM wcl_reports WHERE report_code=?", (report_code,)).fetchone(): raise RosterError(f"WCL report not found: {report_code}")
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO raid_event_reports VALUES(?,?,?)", (event_key, report_code, utc_now()))
        action = "inserted" if conn.total_changes > before else "unchanged"
        conn.commit(); return action
    except Exception: conn.rollback(); raise
    finally: conn.close()


def attendance_report(db_path: Path, event_key: str) -> dict[str, Any]:
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA foreign_keys=ON")
    try:
        apply_migrations(conn)
        event = conn.execute("SELECT * FROM raid_events WHERE event_key=?", (event_key,)).fetchone()
        if not event: raise RosterError(f"Raid event not found: {event_key}")
        rows = conn.execute("""SELECT p.report_code,p.external_character_key,w.display_name,
            gc.character_name,gm.member_id,gm.display_name AS member_display_name,
            (SELECT count(*) FROM wcl_fights f WHERE f.report_code=p.report_code) total_fights,
            (SELECT count(*) FROM wcl_fight_attendance a WHERE a.report_code=p.report_code AND a.external_character_key=p.external_character_key) attended
            FROM raid_event_reports er JOIN wcl_report_participants p ON p.report_code=er.report_code
            JOIN wcl_characters w ON w.external_character_key=p.external_character_key
            LEFT JOIN guild_characters gc ON gc.external_character_key=p.external_character_key
            LEFT JOIN guild_members gm ON gm.member_id=gc.member_id
            WHERE er.event_key=? ORDER BY p.report_code,w.display_name""", (event_key,)).fetchall()
        participants = []
        for row in rows:
            item = dict(row); item["matched_guild"] = item["member_id"] is not None
            item["attendance_percentage"] = round(100 * item["attended"] / item["total_fights"], 2) if item["total_fights"] else 0.0
            participants.append(item)
        return {"event": dict(event), "participants": participants,
                "matched": sum(p["matched_guild"] for p in participants),
                "unmatched": sum(not p["matched_guild"] for p in participants)}
    finally: conn.close()
