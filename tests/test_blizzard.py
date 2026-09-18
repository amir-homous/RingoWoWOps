import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import blizzard
import import_to_sqlite


FIXTURES = ROOT / "tests" / "fixtures"
KEYS = [f"tbc-anniversary/eu/spineshatter/{name}" for name in ("amiringo", "medalisa", "divinegg")]


class FakeResponse:
    def __init__(self, body, status=200): self.body, self.status = body, status
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.body


class BlizzardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.db = self.base / "ringo.sqlite"
        self.raw = self.base / "raw"
        self.config = {"blizzard": dict(blizzard.DEFAULTS, raw_dir=str(self.raw))}
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("PRAGMA foreign_keys=ON"); import_to_sqlite.apply_migrations(conn)
            conn.execute("INSERT INTO guilds VALUES('g','Guild','guild','tbc-anniversary','eu','Spineshatter','spineshatter',1)")
            for i, key in enumerate(KEYS):
                name = key.rsplit('/', 1)[-1].title(); member = f"m{i}"
                conn.execute("INSERT INTO guild_members VALUES(?, 'g', ?, ?, NULL, 'active', ?, 'now', 'now')", (member, name, name.casefold(), "manual private note"))
                conn.execute("INSERT INTO guild_characters VALUES(?, 'g', ?, 'tbc-anniversary','eu','Spineshatter','spineshatter',?,?,?,'healer','main','active','now','now')",
                             (key, member, name, name.casefold(), "ManualClass"))
            conn.commit()

    def fixture(self, name): return FIXTURES / f"blizzard_{name}_profile.json"

    def test_oauth_request_and_token_cached_without_leakage(self):
        secret = "do-not-leak-client-secret"; seen = []
        def opener(request, timeout):
            seen.append(request)
            return FakeResponse(b'{"access_token":"short-lived-token","expires_in":86399}')
        with patch.dict(os.environ, {"BLIZZARD_CLIENT_ID": "test-client", "BLIZZARD_CLIENT_SECRET": secret}):
            client = blizzard.BlizzardClient(self.config, opener=opener)
            self.assertEqual(client.token(), "short-lived-token"); self.assertEqual(client.token(), "short-lived-token")
        self.assertEqual(len(seen), 1); self.assertEqual(seen[0].method, "POST")
        self.assertEqual(seen[0].data, b"grant_type=client_credentials")
        self.assertNotIn(secret, seen[0].full_url)

    def test_missing_credentials_and_http_errors_are_sanitized(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(blizzard.BlizzardError) as caught: blizzard.BlizzardClient(self.config).token()
        self.assertIn("BLIZZARD_CLIENT_SECRET", str(caught.exception))
        secret = "never-output-this"; token = "never-output-token"
        def opener(request, timeout):
            if request.full_url.endswith("/token"): return FakeResponse(json.dumps({"access_token": token}).encode())
            raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, io.BytesIO(b'{"code":404,"detail":"Not Found"}'))
        with patch.dict(os.environ, {"BLIZZARD_CLIENT_ID": "id", "BLIZZARD_CLIENT_SECRET": secret}):
            response = blizzard.BlizzardClient(self.config, opener=opener).get("/profile/wow/character/x/y", "profile-classic1x-eu", "en_GB")
        self.assertEqual(response.status, 404)
        self.assertNotIn(secret, json.dumps(response.body)); self.assertNotIn(token, json.dumps(response.body))

    def test_success_missing_optional_idempotency_identity_and_manual_preservation(self):
        first = blizzard.import_character(KEYS[0], self.config, self.db, offline_json=self.fixture("amiringo"))
        second = blizzard.import_character(KEYS[0], self.config, self.db, offline_json=self.fixture("amiringo"))
        minimal = blizzard.import_character(KEYS[1], self.config, self.db, offline_json=self.fixture("medalisa"))
        self.assertEqual(first["status"], "imported"); self.assertEqual(second["status"], "unchanged")
        self.assertEqual(minimal["status"], "imported")
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM blizzard_character_snapshots").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM blizzard_equipment_snapshots").fetchone()[0], 1)
            manual = conn.execute("SELECT class,primary_role,main_alt FROM guild_characters WHERE external_character_key=?", (KEYS[0],)).fetchone()
            self.assertEqual(manual, ("ManualClass", "healer", "main"))
            self.assertIsNone(conn.execute("SELECT active_spec_name FROM blizzard_character_snapshots WHERE external_character_key=?", (KEYS[1],)).fetchone()[0])
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_all_acceptance_characters(self):
        for key in KEYS:
            name = key.rsplit('/', 1)[-1]
            self.assertEqual(blizzard.import_character(key, self.config, self.db, offline_json=self.fixture(name))["status"], "imported")
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual({r[0] for r in conn.execute("SELECT external_character_key FROM blizzard_character_snapshots")}, set(KEYS))

    def test_unsupported_and_missing_continue_data(self):
        unsupported = self.base / "unsupported.json"
        unsupported.write_text('{"_http_status":404,"profile":{"code":404,"type":"BLZWEBAPI00000404","detail":"Not Found"}}')
        result = blizzard.import_character(KEYS[0], self.config, self.db, offline_json=unsupported)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(blizzard.import_character("tbc-anniversary/eu/spineshatter/unknown", self.config, self.db, offline_json=unsupported)["status"], "missing")
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT status FROM blizzard_profile_import_batches").fetchone()[0], "unsupported")

    def test_malformed_and_atomic_archive(self):
        destination = self.raw / "profile.json"; destination.parent.mkdir(parents=True)
        destination.write_text('{"valid":true}')
        with self.assertRaisesRegex(blizzard.BlizzardError, "valid JSON"):
            blizzard.atomic_archive(b"{bad", destination)
        self.assertEqual(destination.read_text(), '{"valid":true}')
        malformed = self.base / "bad.json"; malformed.write_text("{bad")
        with self.assertRaisesRegex(blizzard.BlizzardError, "not valid JSON"):
            blizzard.import_character(KEYS[0], self.config, self.db, offline_json=malformed)

    def test_archive_sanitization(self):
        destination = self.raw / "safe.json"
        blizzard.atomic_archive(json.dumps({"name":"A", "access_token":"x", "client_secret":"y", "nested":{"discord_user_id":"z"}}).encode(), destination)
        text = destination.read_text(); self.assertNotIn("access_token", text); self.assertNotIn("client_secret", text); self.assertNotIn("discord_user_id", text)

    def test_v9_migration_rollback_and_newer_rejection(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("DROP VIEW blizzard_character_sync_summary")
            for table in ("blizzard_equipment_snapshots", "blizzard_character_snapshots", "blizzard_profile_import_batches"):
                conn.execute(f"DROP TABLE {table}")
            conn.execute("DELETE FROM migration_history WHERE version=9"); conn.execute("PRAGMA user_version=8"); conn.commit()
        with patch("import_to_sqlite._execute_script_without_implicit_commit", side_effect=RuntimeError("forced migration failure")):
            with closing(sqlite3.connect(self.db)) as conn:
                with self.assertRaisesRegex(RuntimeError, "forced"): import_to_sqlite.apply_migrations(conn)
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 8)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute(f"PRAGMA user_version={import_to_sqlite.SCHEMA_VERSION + 1}"); conn.commit()
            with self.assertRaisesRegex(RuntimeError, "newer"): import_to_sqlite.apply_migrations(conn)

    def test_existing_domains_survive_v9(self):
        with closing(sqlite3.connect(self.db)) as conn:
            for table in ("ledger_entries", "farm_runs", "wcl_reports", "raid_helper_signups", "guild_characters"):
                self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


if __name__ == "__main__": unittest.main()
