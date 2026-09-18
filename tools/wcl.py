"""Optional local-first Warcraft Logs V1 report/fight attendance importer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from import_to_sqlite import apply_migrations, backup_database


DEFAULTS = {
    "base_url": "https://fresh.warcraftlogs.com/v1",
    "api_key_env": "WCL_V1_KEY",
    "raw_dir": "data/raw/wcl",
    "game_version": "tbc-anniversary",
    "region": "eu",
    "realm": "spineshatter",
    "guild_character_keys": [],
}


class WclError(RuntimeError):
    pass


def normalize_identity(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip()).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def external_character_key(game_version: str, region: str, realm: str, name: str) -> str:
    game = str(game_version).strip().casefold()
    region_name = str(region).strip().casefold()
    parts = (game, region_name, normalize_identity(realm), normalize_identity(name))
    if not all(parts):
        raise WclError("Character identity fields must normalize to nonempty values")
    return "/".join(parts)


def settings(config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULTS)
    merged.update(config.get("wcl") or {})
    merged["base_url"] = str(merged["base_url"]).rstrip("/")
    return merged


def _validate_report_code(report_code: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]{8,32}", report_code):
        raise WclError("Invalid Warcraft Logs report code")
    return report_code


def fetch_fights(report_code: str, cfg: dict[str, Any], *, opener=urllib.request.urlopen) -> bytes:
    report_code = _validate_report_code(report_code)
    env_name = str(cfg.get("api_key_env") or "WCL_V1_KEY")
    api_key = os.getenv(env_name)
    if not api_key:
        raise WclError(f"Live WCL import unavailable: environment variable {env_name} is missing")
    public_url = f"{cfg['base_url']}/report/fights/{report_code}"
    authenticated_url = public_url + "?" + urllib.parse.urlencode({"api_key": api_key})
    request = urllib.request.Request(authenticated_url, headers={"Accept": "application/json", "User-Agent": "RingoWoWOps/1"})
    try:
        with opener(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise WclError(f"Warcraft Logs request failed with HTTP {exc.code} for report {report_code}") from None
    except urllib.error.URLError:
        raise WclError(f"Warcraft Logs request failed with a network error for report {report_code}") from None


def parse_response(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WclError(f"Warcraft Logs response is not valid JSON: {exc.msg if isinstance(exc, json.JSONDecodeError) else 'invalid UTF-8'}") from None
    if not isinstance(data, dict) or not isinstance(data.get("fights"), list) or not isinstance(data.get("friendlies"), list):
        raise WclError("Warcraft Logs response is missing fights or friendlies")
    return data


def atomic_archive(raw: bytes, destination: Path) -> None:
    parse_response(raw)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".fights-", suffix=".tmp", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _actor_fight_ids(actor: dict[str, Any], fights: list[dict[str, Any]]) -> set[int]:
    actor_id = actor.get("id")
    valid_fight_ids = {int(fight["id"]) for fight in fights if "id" in fight}
    attended = {
        int(item["id"]) for item in (actor.get("fights") or [])
        if isinstance(item, dict) and item.get("id") is not None and int(item["id"]) in valid_fight_ids
    }
    for fight in fights:
        if actor_id in (fight.get("friendlyPlayers") or []):
            attended.add(int(fight["id"]))
    return attended


def import_report(report_code: str, raw: bytes, db_path: Path, archive_path: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    report_code = _validate_report_code(report_code)
    data = parse_response(raw)
    source_hash = hashlib.sha256(raw).hexdigest()
    batch_id = "wcl-" + hashlib.sha256(f"{report_code}\n{source_hash}".encode()).hexdigest()[:32]
    fights = [fight for fight in data["fights"] if isinstance(fight, dict) and "id" in fight]
    actors = [actor for actor in data["friendlies"] if isinstance(actor, dict) and actor.get("id") is not None and actor.get("name")]
    guild_keys = {str(key).casefold() for key in cfg.get("guild_character_keys", [])}
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_database(db_path)
    conn = sqlite3.connect(db_path, timeout=1.0)
    conn.execute("PRAGMA foreign_keys=ON")
    inserted = {name: 0 for name in ("batches", "reports", "fights", "characters", "participants", "attendance")}
    try:
        apply_migrations(conn)
        conn.execute("BEGIN IMMEDIATE")
        def add(sql: str, values: tuple[Any, ...], bucket: str) -> None:
            before = conn.total_changes
            conn.execute(sql, values)
            inserted[bucket] += conn.total_changes - before
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        add("INSERT OR IGNORE INTO wcl_import_batches VALUES(?,?,?,?,?)", (batch_id, report_code, source_hash, str(archive_path), now), "batches")
        owner = data.get("owner")
        owner_name = owner.get("name") if isinstance(owner, dict) else owner
        add("""INSERT OR IGNORE INTO wcl_reports
            (report_code,title,owner_name,start_time,end_time,game_version,region,realm,source_sha256,last_import_batch_id)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (report_code, data.get("title"), owner_name, int(data.get("start", 0)), int(data.get("end", 0)), cfg["game_version"], cfg["region"], cfg["realm"], source_hash, batch_id), "reports")
        for fight in fights:
            add("INSERT OR IGNORE INTO wcl_fights VALUES(?,?,?,?,?)", (report_code, int(fight["id"]), fight.get("name"), int(fight.get("start_time", 0)), int(fight.get("end_time", 0))), "fights")
        keys: dict[int, str] = {}
        for actor in actors:
            actor_realm = actor.get("server") if isinstance(actor.get("server"), str) else cfg["realm"]
            key = external_character_key(cfg["game_version"], cfg["region"], actor_realm, actor["name"])
            keys[int(actor["id"])] = key
            add("INSERT OR IGNORE INTO wcl_characters VALUES(?,?,?,?,?,?,?,?)", (key, actor["name"], normalize_identity(actor["name"]), str(cfg["game_version"]).casefold(), str(cfg["region"]).casefold(), actor_realm, normalize_identity(actor_realm), int(key.casefold() in guild_keys)), "characters")
            add("INSERT OR IGNORE INTO wcl_report_participants VALUES(?,?,?)", (report_code, key, int(actor["id"])), "participants")
            for fight_id in _actor_fight_ids(actor, fights):
                add("INSERT OR IGNORE INTO wcl_fight_attendance VALUES(?,?,?)", (report_code, fight_id, key), "attendance")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"report_code": report_code, "title": data.get("title"), "owner": owner_name, "start": data.get("start"), "end": data.get("end"), "fights": len(fights), "characters": len(actors), "attendance": sum(len(_actor_fight_ids(a, fights)) for a in actors), "inserted": inserted, "unchanged": len(fights) + len(actors) + len(actors) + sum(len(_actor_fight_ids(a, fights)) for a in actors) + 2 - sum(inserted.values()), "archive": str(archive_path), "backup": str(backup) if backup else None, "character_keys": sorted(keys.values())}


def run_import(report_code: str, config: dict[str, Any], db_path: Path, *, offline_json: Path | None = None, opener=urllib.request.urlopen) -> dict[str, Any]:
    cfg = settings(config)
    raw = offline_json.read_bytes() if offline_json else fetch_fights(report_code, cfg, opener=opener)
    parse_response(raw)
    archive = Path(cfg["raw_dir"])
    if not archive.is_absolute():
        archive = Path(__file__).resolve().parents[1] / archive
    archive = archive / report_code / "fights.json"
    atomic_archive(raw, archive)
    return import_report(report_code, raw, db_path.resolve(), archive.resolve(), cfg)
