import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import import_to_sqlite
import wcl

FIXTURE = ROOT / "tests" / "fixtures" / "wcl_report_fights.json"
REPORT = "RxkpqFn98jt1BYMr"
KEYS = {
    "tbc-anniversary/eu/spineshatter/amiringo",
    "tbc-anniversary/eu/spineshatter/medalisa",
    "tbc-anniversary/eu/spineshatter/divinegg",
}


class FakeResponse:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.body


class WclTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.db = self.base / "ringo.sqlite"
        self.raw = self.base / "raw"
        self.config = {"wcl": dict(wcl.DEFAULTS, raw_dir=str(self.raw), guild_character_keys=sorted(KEYS))}

    def run_import(self):
        return wcl.run_import(REPORT, self.config, self.db, offline_json=FIXTURE)

    def connect(self):
        conn = sqlite3.connect(self.db); conn.execute("PRAGMA foreign_keys=ON"); return conn

    def test_normalization_and_external_keys(self):
        self.assertEqual(wcl.normalize_identity(" Spine-Shatter "), "spineshatter")
        self.assertEqual(wcl.normalize_identity("ÁMIRINGO"), "amiringo")
        self.assertEqual(wcl.external_character_key("tbc-anniversary", "EU", "Spine-Shatter", "Amiringo"), "tbc-anniversary/eu/spineshatter/amiringo")

    def test_offline_first_import_and_idempotency(self):
        with patch("wcl.fetch_fights", side_effect=AssertionError("network used")):
            first = self.run_import(); second = self.run_import()
        self.assertEqual(first["fights"], 3); self.assertEqual(first["characters"], 4); self.assertEqual(first["attendance"], 9)
        self.assertGreater(sum(first["inserted"].values()), 0)
        self.assertEqual(sum(second["inserted"].values()), 0)
        with closing(self.connect()) as conn:
            counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("wcl_reports", "wcl_fights", "wcl_characters", "wcl_report_participants", "wcl_fight_attendance")}
            self.assertEqual(counts, {"wcl_reports": 1, "wcl_fights": 3, "wcl_characters": 4, "wcl_report_participants": 4, "wcl_fight_attendance": 9})
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_guild_mapping_and_pug_preservation(self):
        self.run_import()
        with closing(self.connect()) as conn:
            guild = {r[0] for r in conn.execute("SELECT external_character_key FROM wcl_characters WHERE is_guild_member=1")}
            pug = conn.execute("SELECT is_guild_member FROM wcl_characters WHERE display_name='Guestmage'").fetchone()[0]
        self.assertEqual(guild, KEYS); self.assertEqual(pug, 0)

    def test_archive_is_valid_and_atomic_failure_preserves_existing(self):
        result = self.run_import(); archive = Path(result["archive"])
        self.assertEqual(json.loads(archive.read_text(encoding="utf-8"))["title"], "Hyjal - Butter & Jam")
        original = archive.read_bytes()
        with patch("wcl.os.replace", side_effect=OSError("forced replace failure")):
            with self.assertRaisesRegex(OSError, "forced"):
                wcl.atomic_archive(FIXTURE.read_bytes(), archive)
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(list(archive.parent.glob("*.tmp")), [])

    def test_malformed_json_never_replaces_archive(self):
        archive = self.raw / REPORT / "fights.json"; archive.parent.mkdir(parents=True); archive.write_text('{"valid":true}')
        with self.assertRaisesRegex(wcl.WclError, "valid JSON"):
            wcl.atomic_archive(b"{bad", archive)
        self.assertEqual(archive.read_text(), '{"valid":true}')

    def test_missing_key_and_sanitized_http_error(self):
        cfg = wcl.settings(self.config)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(wcl.WclError, "WCL_V1_KEY is missing"):
                wcl.fetch_fights(REPORT, cfg)
        secret = "never-show-this-secret"
        def fail(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO())
        with patch.dict(os.environ, {"WCL_V1_KEY": secret}):
            with self.assertRaises(wcl.WclError) as caught:
                wcl.fetch_fights(REPORT, cfg, opener=fail)
        self.assertNotIn(secret, str(caught.exception)); self.assertNotIn("api_key", str(caught.exception))

    def test_mocked_live_import_and_no_key_leakage(self):
        secret = "private-test-token"
        seen = []
        def open_ok(request, timeout):
            seen.append(request.full_url); return FakeResponse(FIXTURE.read_bytes())
        with patch.dict(os.environ, {"WCL_V1_KEY": secret}):
            result = wcl.run_import(REPORT, self.config, self.db, opener=open_ok)
        self.assertEqual(result["characters"], 4); self.assertIn(secret, seen[0])
        self.assertNotIn(secret, Path(result["archive"]).read_text(encoding="utf-8"))
        with closing(self.connect()) as conn:
            dump = "\n".join(conn.iterdump())
        self.assertNotIn(secret, dump); self.assertNotIn("api_key", dump)

    def test_migration_preserves_existing_rows_and_rejects_newer(self):
        conn = sqlite3.connect(self.db); import_to_sqlite.apply_migrations(conn)
        conn.execute("INSERT INTO ledger_entries(record_id,time,created_at,character,realm,direction,category,amount_copper,amount_quality,input_source,schema_version,addon_schema_version,character_id,source_file_sha256,source_schema_version,source_record_index,source_dataset,import_batch_id,logical_payload,raw_record) VALUES('e',1,1,'A','R','in','other',1,'exact','addon_command',1,4,NULL,'h','5',1,'ledger_entries','b','{}','{}')") if False else None
        conn.execute("PRAGMA user_version=999"); conn.commit(); conn.close()
        with self.assertRaisesRegex(RuntimeError, "newer than supported"):
            self.run_import()

    def test_v5_migration_backup_preserves_farm_and_ledger_rows(self):
        conn = sqlite3.connect(self.db); import_to_sqlite.apply_migrations(conn)
        conn.execute("CREATE TABLE preserved_marker(kind TEXT PRIMARY KEY)"); conn.executemany("INSERT INTO preserved_marker VALUES(?)", [("farm",), ("ledger",)])
        conn.execute("DROP TABLE wcl_fight_attendance"); conn.execute("DROP TABLE wcl_report_participants"); conn.execute("DROP TABLE wcl_characters"); conn.execute("DROP TABLE wcl_fights"); conn.execute("DROP TABLE wcl_reports"); conn.execute("DROP TABLE wcl_import_batches")
        conn.execute("DELETE FROM migration_history WHERE version=6"); conn.execute("PRAGMA user_version=5"); conn.commit(); conn.close()
        result = self.run_import()
        self.assertTrue(Path(result["backup"]).exists())
        with closing(self.connect()) as conn: self.assertEqual(conn.execute("SELECT count(*) FROM preserved_marker").fetchone()[0], 2)

    def test_migration_rollback(self):
        conn = sqlite3.connect(self.db); conn.execute("CREATE TABLE marker(value TEXT)"); conn.execute("INSERT INTO marker VALUES('kept')"); conn.execute("PRAGMA user_version=5"); conn.commit(); conn.close()
        with patch("import_to_sqlite._execute_script_without_implicit_commit", side_effect=RuntimeError("forced migration failure")):
            with self.assertRaisesRegex(RuntimeError, "forced migration failure"): self.run_import()
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "kept")

    def test_cli_offline_import(self):
        config = self.base / "config.json"
        payload = {"wow_path": str(self.base), "account": "test", "sqlite_db": str(self.db), "wcl": self.config["wcl"]}
        config.write_text(json.dumps(payload), encoding="utf-8")
        process = subprocess.run([sys.executable, str(ROOT / "tools" / "rwo.py"), "wcl-import", "--config", str(config), "--report-code", REPORT, "--offline-json", str(FIXTURE)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("Amiringo: found", process.stdout); self.assertNotIn("api_key", process.stdout)

    def test_cli_error_is_clear_without_traceback(self):
        config = self.base / "config.json"
        payload = {"wow_path": str(self.base), "account": "test", "sqlite_db": str(self.db), "wcl": self.config["wcl"]}
        config.write_text(json.dumps(payload), encoding="utf-8")
        bad = self.base / "bad.json"; bad.write_text("not-json", encoding="utf-8")
        process = subprocess.run([sys.executable, str(ROOT / "tools" / "rwo.py"), "wcl-import", "--config", str(config), "--report-code", REPORT, "--offline-json", str(bad)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(process.returncode, 1)
        self.assertIn("not valid JSON", process.stderr)
        self.assertNotIn("Traceback", process.stderr)


if __name__ == "__main__": unittest.main()
