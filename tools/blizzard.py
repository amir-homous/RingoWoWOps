"""Local-first Blizzard character profile provider and importer."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from import_to_sqlite import apply_migrations, backup_database, utc_now
from wcl import external_character_key


DEFAULTS = {
    "token_url": "https://oauth.battle.net/token",
    "api_base_url": "https://eu.api.blizzard.com",
    "raw_dir": "data/raw/blizzard",
    "locale": "en_GB",
    "namespace": "profile-classic1x-eu",
    "client_id_env": "BLIZZARD_CLIENT_ID",
    "client_secret_env": "BLIZZARD_CLIENT_SECRET",
}
SENSITIVE_KEYS = {"access_token", "authorization", "client_id", "client_secret", "discord_user_id", "notes"}


class BlizzardError(RuntimeError):
    pass


@dataclass
class ProviderResponse:
    status: int
    body: dict[str, Any]


def settings(config: dict) -> dict:
    merged = dict(DEFAULTS)
    merged.update(config.get("blizzard") or {})
    return merged


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items() if k.casefold() not in SENSITIVE_KEYS}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(_sanitize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def atomic_archive(payload: bytes, destination: Path) -> None:
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BlizzardError("Blizzard response is not valid JSON") from None
    clean = _json_bytes(parsed)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=destination.parent, prefix=destination.name + ".", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(clean)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def parse_character_key(key: str) -> tuple[str, str, str, str]:
    parts = key.split("/")
    if len(parts) != 4 or any(not part for part in parts):
        raise BlizzardError("Invalid external character key")
    canonical = external_character_key(*parts)
    if canonical != key:
        raise BlizzardError(f"External character key must be canonical: {canonical}")
    return tuple(parts)  # type: ignore[return-value]


class BlizzardClient:
    def __init__(self, config: dict, opener: Callable[..., Any] = urllib.request.urlopen):
        self.config = settings(config)
        self.opener = opener
        self._token: str | None = None

    def token(self) -> str:
        if self._token:
            return self._token
        id_env = str(self.config["client_id_env"])
        secret_env = str(self.config["client_secret_env"])
        client_id, secret = os.getenv(id_env), os.getenv(secret_env)
        if not client_id or not secret:
            raise BlizzardError(f"Blizzard credentials are missing ({id_env} and {secret_env})")
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        request = urllib.request.Request(
            str(self.config["token_url"]), data=b"grant_type=client_credentials", method="POST",
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self.opener(request, timeout=20) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
            raise BlizzardError("Blizzard OAuth token request failed") from None
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise BlizzardError("Blizzard OAuth response did not contain an access token")
        self._token = token
        return token

    def get(self, path: str, namespace: str, locale: str) -> ProviderResponse:
        query = urllib.parse.urlencode({"namespace": namespace, "locale": locale})
        request = urllib.request.Request(
            str(self.config["api_base_url"]).rstrip("/") + path + "?" + query,
            headers={"Authorization": f"Bearer {self.token()}"},
        )
        try:
            with self.opener(request, timeout=20) as response:
                return ProviderResponse(response.status, json.loads(response.read()))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
            return ProviderResponse(exc.code, _sanitize(body) if isinstance(body, dict) else {})
        except (urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
            raise BlizzardError("Blizzard API request failed") from None

    def character_bundle(self, realm: str, name: str) -> tuple[int, dict[str, Any]]:
        namespace, locale = str(self.config["namespace"]), str(self.config["locale"])
        slug = urllib.parse.quote(realm, safe="")
        char = urllib.parse.quote(name, safe="")
        profile = self.get(f"/profile/wow/character/{slug}/{char}", namespace, locale)
        if profile.status != 200:
            return profile.status, {"profile": profile.body}
        bundle: dict[str, Any] = {"profile": profile.body}
        for label, suffix in (("equipment", "equipment"), ("professions", "professions")):
            response = self.get(f"/profile/wow/character/{slug}/{char}/{suffix}", namespace, locale)
            if response.status == 200:
                bundle[label] = response.body
        return 200, bundle


def _name(value: Any) -> str | None:
    if isinstance(value, dict):
        candidate = value.get("name")
        return str(candidate) if candidate not in (None, "") else None
    return str(value) if value not in (None, "") else None


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _source_url(config: dict, realm: str, name: str, namespace: str) -> str:
    base = str(config["api_base_url"]).rstrip("/")
    return f"{base}/profile/wow/character/{urllib.parse.quote(realm, safe='')}/{urllib.parse.quote(name, safe='')}?namespace={urllib.parse.quote(namespace)}"


def _status_for_http(game_version: str, status: int) -> str:
    if status == 404 and game_version == "tbc-anniversary":
        return "unsupported"
    if status == 404:
        return "missing"
    return "failed"


def import_character(character_key: str, config: dict, db_path: Path, *, offline_json: Path | None = None,
                     client: BlizzardClient | None = None) -> dict[str, Any]:
    game_version, region, realm, name = parse_character_key(character_key)
    cfg = settings(config)
    namespace = str(cfg["namespace"])
    backup = backup_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        apply_migrations(conn)
        if not conn.execute("SELECT 1 FROM guild_characters WHERE external_character_key=?", (character_key,)).fetchone():
            return {"character_key": character_key, "status": "missing", "fields": [], "archive": None, "backup": str(backup) if backup else None}
        fetched_at = utc_now()
        if offline_json:
            try:
                bundle = json.loads(offline_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                raise BlizzardError("Offline Blizzard fixture is not valid JSON") from None
            if not isinstance(bundle, dict):
                raise BlizzardError("Offline Blizzard fixture must contain a JSON object")
            status_code = int(bundle.pop("_http_status", 200))
        else:
            status_code, bundle = (client or BlizzardClient(config)).character_bundle(realm, name)
        bundle = _sanitize(bundle)
        archive = Path(str(cfg["raw_dir"])) / character_key / "profile.json"
        if not archive.is_absolute():
            archive = Path(__file__).resolve().parents[1] / archive
        atomic_archive(_json_bytes(bundle), archive)
        source_hash = hashlib.sha256(_json_bytes(bundle)).hexdigest()
        batch_id = "blizzard-" + hashlib.sha256(f"{character_key}\n{namespace}\n{source_hash}".encode()).hexdigest()[:32]
        if status_code != 200:
            status = _status_for_http(game_version, status_code)
            error = {"http_status": status_code, "response": bundle}
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO blizzard_profile_import_batches VALUES(?,?,?,?,?,?,?,?)",
                         (batch_id, character_key, namespace, source_hash, fetched_at, status, str(archive), json.dumps(error, sort_keys=True)))
            conn.commit()
            return {"character_key": character_key, "status": status, "fields": [], "archive": str(archive), "error": error, "backup": str(backup) if backup else None}
        profile = bundle.get("profile") if isinstance(bundle.get("profile"), dict) else bundle
        equipment = bundle.get("equipment") if isinstance(bundle.get("equipment"), dict) else {}
        professions = bundle.get("professions") if isinstance(bundle.get("professions"), dict) else None
        if not isinstance(profile, dict) or not _name(profile.get("name")):
            raise BlizzardError("Blizzard profile response is missing a character name")
        response_realm = _name(profile.get("realm")) or realm
        response_name = _name(profile.get("name")) or name
        response_key = external_character_key(game_version, region, response_realm, response_name)
        if response_key != character_key:
            raise BlizzardError("Blizzard profile identity does not match the requested character")
        existing = conn.execute("SELECT 1 FROM blizzard_profile_import_batches WHERE batch_id=?", (batch_id,)).fetchone()
        if existing:
            return {"character_key": character_key, "status": "unchanged", "fields": [], "archive": str(archive), "backup": str(backup) if backup else None}
        snapshot_id = "snapshot-" + hashlib.sha256(f"{character_key}\n{namespace}\n{source_hash}".encode()).hexdigest()[:32]
        avg_ilvl = _number(profile.get("average_item_level"))
        equipped_ilvl = _number(profile.get("equipped_item_level"))
        last_modified = profile.get("last_modified") or profile.get("lastModified")
        values = {
            "level": _number(profile.get("level")), "race": _name(profile.get("race")),
            "class": _name(profile.get("character_class")) or _name(profile.get("class")),
            "faction": _name(profile.get("faction")), "active_spec": _name(profile.get("active_spec")),
            "professions": professions, "average_item_level": avg_ilvl, "equipped_item_level": equipped_ilvl,
            "profile_last_modified": str(last_modified) if last_modified is not None else None,
        }
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO blizzard_profile_import_batches VALUES(?,?,?,?,?,'imported',?,NULL)",
                     (batch_id, character_key, namespace, source_hash, fetched_at, str(archive)))
        conn.execute("""INSERT INTO blizzard_character_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (snapshot_id, character_key, namespace, source_hash, fetched_at, response_name, response_realm,
                      region, game_version, values["level"], values["race"], values["class"], values["faction"],
                      values["active_spec"], json.dumps(professions, sort_keys=True) if professions else None,
                      avg_ilvl, equipped_ilvl, values["profile_last_modified"],
                      _source_url(cfg, realm, name, namespace), batch_id))
        for item in equipment.get("equipped_items", []):
            if not isinstance(item, dict):
                continue
            slot_data = item.get("slot")
            slot = str(slot_data.get("type")) if isinstance(slot_data, dict) and slot_data.get("type") else _name(slot_data)
            if not slot:
                continue
            level = item.get("level")
            if isinstance(level, dict):
                level = level.get("value")
            conn.execute("INSERT INTO blizzard_equipment_snapshots VALUES(?,?,?,?,?,?)",
                         (snapshot_id, slot, item.get("item", {}).get("id") if isinstance(item.get("item"), dict) else None,
                          _name(item), _number(level), json.dumps(_sanitize(item), sort_keys=True)))
        conn.commit()
        fields = [key for key, value in values.items() if value is not None]
        return {"character_key": character_key, "status": "imported", "fields": fields,
                "equipment_items": len(equipment.get("equipped_items", [])), "archive": str(archive),
                "backup": str(backup) if backup else None}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def roster_character_keys(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn)
        return [row[0] for row in conn.execute("SELECT external_character_key FROM guild_characters ORDER BY external_character_key")]
    finally:
        conn.close()
