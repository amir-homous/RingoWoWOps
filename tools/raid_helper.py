"""Optional public Raid-Helper event importer and signup/WCL reconciliation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from import_to_sqlite import apply_migrations, backup_database
from wcl import normalize_identity

BASE_URL = "https://raid-helper.xyz/api/v4/events"


class RaidHelperError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_event_id(event_id: str) -> str:
    if not re.fullmatch(r"[0-9]{10,24}", str(event_id)):
        raise RaidHelperError("Invalid Raid-Helper event ID")
    return str(event_id)


def fetch_event(event_id: str, *, opener=urllib.request.urlopen) -> bytes:
    event_id = validate_event_id(event_id)
    request = urllib.request.Request(f"{BASE_URL}/{event_id}", headers={"Accept": "application/json", "User-Agent": "RingoWoWOps/1"})
    try:
        with opener(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RaidHelperError(f"Raid-Helper request failed with HTTP {exc.code} for event {event_id}") from None
    except urllib.error.URLError:
        raise RaidHelperError(f"Raid-Helper request failed with a network error for event {event_id}") from None


def parse_response(raw: bytes, event_id: str) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        message = exc.msg if isinstance(exc, json.JSONDecodeError) else "invalid UTF-8"
        raise RaidHelperError(f"Raid-Helper response is not valid JSON: {message}") from None
    if not isinstance(data, dict) or not isinstance(data.get("signUps"), list):
        raise RaidHelperError("Raid-Helper response is missing signUps")
    if str(data.get("id")) != str(event_id):
        raise RaidHelperError("Raid-Helper response event ID does not match the requested event")
    return data


def sanitized_response(data: dict[str, Any]) -> dict[str, Any]:
    private_root = {"creator", "coLeaders", "leaderId", "serverId", "channelId", "announcements"}
    private_signup = {"userId", "note", "notes", "comment", "comments"}
    clean = {key: value for key, value in data.items() if key not in private_root and key != "signUps"}
    clean["signUps"] = [{key: value for key, value in item.items() if key not in private_signup}
                        for item in data["signUps"] if isinstance(item, dict)]
    return clean


def atomic_archive(data: dict[str, Any], destination: Path) -> None:
    payload = (json.dumps(sanitized_response(data), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".event-", suffix=".tmp", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _value(item: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return str(value).strip() or None
    return None


def _resolve(conn: sqlite3.Connection, item: dict[str, Any], event: sqlite3.Row) -> tuple[str | None, str | None, str | None]:
    discord_id = _value(item, "userId")
    if discord_id:
        row = conn.execute("SELECT member_id FROM guild_members WHERE discord_user_id=?", (discord_id,)).fetchone()
        if row:
            member_id = row[0]
            name = _value(item, "name") or ""
            chars = conn.execute("SELECT external_character_key,normalized_character_name FROM guild_characters WHERE member_id=?", (member_id,)).fetchall()
            exact = next((char[0] for char in chars if char[1] == normalize_identity(name)), None)
            return member_id, exact, "discord_id"
    name = _value(item, "name") or ""
    normalized = normalize_identity(name)
    if "/" in name or not normalized:
        return None, None, None
    key = f"{event['game_version'].casefold()}/{event['region'].casefold()}/{normalize_identity(event['realm'])}/{normalized}"
    row = conn.execute("SELECT member_id FROM guild_characters WHERE external_character_key=?", (key,)).fetchone()
    if row:
        return row[0], key, "character_key"
    row = conn.execute("""SELECT member_id,external_character_key FROM guild_characters
        WHERE game_version=? AND region=? AND normalized_realm=? AND normalized_character_name=?""",
        (event["game_version"].casefold(), event["region"].casefold(), normalize_identity(event["realm"]), normalized)).fetchone()
    return (row[0], row[1], "normalized_character") if row else (None, None, None)


def import_event(event_id: str, raw: bytes, db_path: Path, archive: Path) -> dict[str, Any]:
    event_id = validate_event_id(event_id); data = parse_response(raw, event_id)
    atomic_archive(data, archive)
    event_key = f"raid-helper/{event_id}"; source_hash = hashlib.sha256(raw).hexdigest()
    batch_id = "rh-" + hashlib.sha256(f"{event_key}\n{source_hash}".encode()).hexdigest()[:32]
    backup = backup_database(db_path)
    conn = sqlite3.connect(db_path, timeout=1.0); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA foreign_keys=ON")
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    try:
        apply_migrations(conn); conn.execute("BEGIN IMMEDIATE"); now = utc_now()
        existing = conn.execute("SELECT * FROM raid_events WHERE event_key=?", (event_key,)).fetchone()
        if existing is None:
            raise RaidHelperError(f"Raid event not found: {event_key}; create its local game/realm context first")
        conn.execute("INSERT OR IGNORE INTO raid_helper_import_batches VALUES(?,?,?,?,?)", (batch_id, event_key, source_hash, str(archive), now))
        for index, item in enumerate(data["signUps"]):
            if not isinstance(item, dict): continue
            name = _value(item, "name")
            if not name: continue
            external_id = _value(item, "id")
            identity = external_id or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:24]
            signup_key = f"{event_key}/{identity}"
            member_id, character_key, method = _resolve(conn, item, existing)
            values = (event_key, external_id, int(item["position"]) if item.get("position") is not None else index,
                      name, normalize_identity(name), _value(item, "userId"), _value(item, "status") or "unknown",
                      _value(item, "className", "cClassName"), _value(item, "roleName", "cRoleName"),
                      _value(item, "specName", "cSpecName"), _value(item, "notes", "note", "comments", "comment"),
                      _value(item, "entryTime"), member_id, character_key, method, batch_id,
                      json.dumps(item, sort_keys=True, ensure_ascii=False))
            old = conn.execute("""SELECT event_key,external_signup_id,position,display_name,normalized_name,discord_user_id,
                signup_status,class_name,role_name,spec_name,notes,signup_at,resolved_member_id,resolved_character_key,
                resolution_method,import_batch_id,raw_record FROM raid_helper_signups WHERE signup_key=?""", (signup_key,)).fetchone()
            if old is None:
                conn.execute("INSERT INTO raid_helper_signups VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (signup_key, *values)); counts["inserted"] += 1
            elif tuple(old) == values: counts["unchanged"] += 1
            else:
                conn.execute("""UPDATE raid_helper_signups SET position=?,display_name=?,normalized_name=?,discord_user_id=?,signup_status=?,
                    class_name=?,role_name=?,spec_name=?,notes=?,signup_at=?,resolved_member_id=?,resolved_character_key=?,resolution_method=?,
                    import_batch_id=?,raw_record=? WHERE signup_key=?""", (values[2], *values[3:], signup_key)); counts["updated"] += 1
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()
    return {"event_key": event_key, "signups": len(data["signUps"]), **counts, "backup": str(backup) if backup else None, "archive": str(archive)}


def run_import(event_id: str, config: dict[str, Any], db_path: Path, *, offline_json: Path | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    raw = offline_json.read_bytes() if offline_json else fetch_event(event_id, opener=opener)
    data = parse_response(raw, event_id)
    raw_dir = Path((config.get("raid_helper") or {}).get("raw_dir", "data/raw/raid-helper"))
    if not raw_dir.is_absolute(): raw_dir = Path(__file__).resolve().parents[1] / raw_dir
    archive = (raw_dir / str(event_id) / "event.json").resolve()
    result = import_event(event_id, raw, db_path.resolve(), archive)
    return result


def reconcile(db_path: Path, event_key: str) -> dict[str, Any]:
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA foreign_keys=ON")
    categories = {name: 0 for name in ("signed_up_and_attended", "signed_up_no_wcl_attendance", "bench_attended",
                  "tentative_attended", "no_signup_but_attended", "unmatched_signup", "unmatched_wcl_participant_pug")}
    try:
        apply_migrations(conn)
        if not conn.execute("SELECT 1 FROM raid_events WHERE event_key=?", (event_key,)).fetchone(): raise RaidHelperError(f"Raid event not found: {event_key}")
        signups = conn.execute("SELECT * FROM raid_helper_signups WHERE event_key=?", (event_key,)).fetchall()
        accounted_chars: set[str] = set()
        matched = unresolved = 0
        for signup in signups:
            if not signup["resolved_member_id"] and not signup["resolved_character_key"]:
                categories["unmatched_signup"] += 1; unresolved += 1; continue
            matched += 1
            if signup["resolved_member_id"]:
                member_chars = {row[0] for row in conn.execute("SELECT external_character_key FROM guild_characters WHERE member_id=?", (signup["resolved_member_id"],))}
            else: member_chars = set()
            if signup["resolved_character_key"]: member_chars.add(signup["resolved_character_key"])
            accounted_chars.update(member_chars)
            attended = conn.execute("""SELECT count(*) FROM wcl_fight_attendance a JOIN raid_event_reports er ON er.report_code=a.report_code
                WHERE er.event_key=? AND a.external_character_key IN ({})""".format(",".join("?" for _ in member_chars) or "NULL"), (event_key, *member_chars)).fetchone()[0]
            status = signup["signup_status"].casefold()
            if attended and "bench" in status: category = "bench_attended"
            elif attended and ("tentative" in status or "maybe" in status): category = "tentative_attended"
            elif attended: category = "signed_up_and_attended"
            else: category = "signed_up_no_wcl_attendance"
            categories[category] += 1
        participants = conn.execute("""SELECT DISTINCT p.external_character_key,
            EXISTS(SELECT 1 FROM wcl_fight_attendance a WHERE a.report_code=p.report_code AND a.external_character_key=p.external_character_key) attended,
            EXISTS(SELECT 1 FROM guild_characters gc WHERE gc.external_character_key=p.external_character_key) rostered
            FROM raid_event_reports er JOIN wcl_report_participants p ON p.report_code=er.report_code WHERE er.event_key=?""", (event_key,)).fetchall()
        for participant in participants:
            if not participant["attended"] or participant["external_character_key"] in accounted_chars: continue
            categories["no_signup_but_attended" if participant["rostered"] else "unmatched_wcl_participant_pug"] += 1
        return {"event_key": event_key, "signups": len(signups), "matched": matched, "unresolved": unresolved, "categories": categories}
    finally: conn.close()
