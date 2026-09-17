import csv
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from data_model import canonical_activity, compatibility_id
from generate_daily_report import generate_report
from import_to_sqlite import SCHEMA_VERSION, backup_database, import_directory
import import_to_sqlite
from parse_savedvariables import export_normalized
import rwo


FIXTURES = ROOT / "tests" / "fixtures"


class PipelineTests(unittest.TestCase):
    def read_csv(self, path):
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def parse_fixture(self, name, base):
        out = base / "processed"
        metadata = export_normalized(FIXTURES / name, out)
        return out, metadata

    def test_legacy_parser_stable_ids_incomplete_rows_and_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first, metadata = self.parse_fixture("legacy_savedvariables.lua", base)
            rows = self.read_csv(first / "sessions.csv")
            self.assertEqual(metadata["source_schema_version"], "0.1.0")
            self.assertEqual(rows[0]["status"], "completed")
            self.assertEqual(rows[1]["status"], "incomplete")
            self.assertTrue(rows[1]["record_id"].startswith("legacy-session-"))
            stable_id = rows[1]["record_id"]
            second = base / "second"
            export_normalized(FIXTURES / "legacy_savedvariables.lua", second)
            second_rows = self.read_csv(second / "sessions.csv")
            self.assertEqual(stable_id, second_rows[1]["record_id"])
            activities = self.read_csv(first / "activities.csv")
            self.assertEqual(activities[0]["activity"], "questing")
            self.assertEqual(activities[0]["activity_original"], "questin")
            warnings = self.read_csv(first / "validation_errors.csv")
            self.assertIn("incomplete_session", {row["code"] for row in warnings})

    def test_current_parser_preserves_identity_and_session_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = self.parse_fixture("current_savedvariables.lua", Path(tmp))
            snapshots = self.read_csv(out / "snapshots.csv")
            self.assertEqual(snapshots[0]["record_id"], "snapshot-current-1")
            self.assertEqual(snapshots[0]["session_id"], "session-current-1")
            self.assertEqual(snapshots[0]["character"], "Testpal")
            self.assertEqual(snapshots[0]["realm"], "Testrealm")
            warnings = self.read_csv(out / "validation_errors.csv")
            malformed = [row for row in warnings if row["code"] == "invalid_record_type"]
            self.assertEqual(len(malformed), 1)
            self.assertIn("malformed snapshot", malformed[0]["raw_record"])

    def test_aliases(self):
        self.assertEqual(canonical_activity("questin"), "questing")
        self.assertEqual(canonical_activity("Mining"), "gathering")
        self.assertEqual(canonical_activity("custom-run"), "custom-run")

    def test_legacy_ids_ignore_order_paths_and_import_time(self):
        first = {"time": 100, "character": "One", "realm": "Realm", "text": "alpha"}
        second = {"time": 200, "character": "Two", "realm": "Realm", "text": "beta"}
        expected = {compatibility_id("notes", first), compatibility_id("notes", second)}
        reordered = {compatibility_id("notes", row) for row in (second, first)}
        decorated = dict(first, source_file_sha256="different", source_record_index=999, import_batch_id="later")
        self.assertEqual(expected, reordered)
        self.assertEqual(compatibility_id("notes", first), compatibility_id("notes", decorated))

    def test_timestamps_are_stored_without_timezone_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out, _ = self.parse_fixture("current_savedvariables.lua", base)
            db = base / "test.sqlite"
            import_directory(out, db)
            conn = sqlite3.connect(db)
            stored = conn.execute("SELECT started_at FROM sessions WHERE record_id='session-current-1'").fetchone()[0]
            conn.close()
            self.assertEqual(stored, 1780261200)

    def test_import_is_idempotent_and_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out, _ = self.parse_fixture("current_savedvariables.lua", base)
            db = base / "test.sqlite"
            first = import_directory(out, db)
            second = import_directory(out, db)
            self.assertEqual(first["inserted"]["sessions"], 1)
            self.assertEqual(sum(second["inserted"].values()), 0)
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM import_batches").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM validation_errors").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT character||'@'||realm FROM source_identities").fetchone()[0], "Testpal@Testrealm")
            conn.close()

    def test_existing_legacy_database_is_backed_up_and_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "legacy.sqlite"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE sessions (id TEXT, character TEXT, realm TEXT)")
            conn.execute("INSERT INTO sessions VALUES ('old','Oldchar','Oldrealm')")
            conn.commit()
            conn.close()
            out, _ = self.parse_fixture("current_savedvariables.lua", base)
            result = import_directory(out, db)
            self.assertIsNotNone(result["backup"])
            self.assertTrue(Path(result["backup"]).exists())
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("SELECT count(*) FROM legacy_sessions_pre_v2").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
            conn.close()

    def test_failed_migration_rolls_back_and_leaves_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = base / "legacy.sqlite"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE sessions (id TEXT, character TEXT, realm TEXT)")
            conn.execute("INSERT INTO sessions VALUES ('old','Oldchar','Oldrealm')")
            conn.commit(); conn.close()
            out, _ = self.parse_fixture("current_savedvariables.lua", base)
            with patch.object(import_to_sqlite, "_execute_script_without_implicit_commit", side_effect=RuntimeError("forced migration failure")):
                with self.assertRaisesRegex(RuntimeError, "forced migration failure"):
                    import_directory(out, db)
            backups = list(base.glob("legacy.pre_migration_v*.sqlite"))
            self.assertEqual(len(backups), 1)
            conn = sqlite3.connect(db)
            self.assertIn("sessions", {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")})
            self.assertNotIn("legacy_sessions_pre_v2", {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")})
            self.assertEqual(conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
            conn.close()

    def test_locked_database_fails_without_changing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out, _ = self.parse_fixture("current_savedvariables.lua", base)
            db = base / "test.sqlite"
            import_directory(out, db)
            lock = sqlite3.connect(db)
            lock.execute("BEGIN EXCLUSIVE")
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    import_directory(out, db)
            finally:
                lock.rollback(); lock.close()
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
            conn.close()

    def test_backup_name_collision_uses_numbered_suffix(self):
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 1, 2, 3, 4, 5)

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.sqlite"
            conn = sqlite3.connect(db); conn.execute("CREATE TABLE old_data(id INTEGER)"); conn.commit(); conn.close()
            collision = db.with_name(f"legacy.pre_migration_v{SCHEMA_VERSION}_20260102_030405.sqlite")
            collision.write_bytes(b"existing backup")
            with patch.object(import_to_sqlite, "datetime", FrozenDateTime):
                result = backup_database(db)
            self.assertEqual(result.name, f"legacy.pre_migration_v{SCHEMA_VERSION}_20260102_030405_1.sqlite")
            self.assertEqual(collision.read_bytes(), b"existing backup")

    def test_end_to_end_scoped_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out, _ = self.parse_fixture("current_savedvariables.lua", base)
            db, report = base / "test.sqlite", base / "report.md"
            import_directory(out, db)
            result = generate_report(db, report, report_date="2026-05-31", timezone_name="UTC", character="Testpal", realm="Testrealm")
            text = report.read_text(encoding="utf-8")
            self.assertEqual(result["counts"]["sessions"], 1)
            self.assertIn("Raw balance change", text)
            self.assertIn("is not profit", text)
            self.assertNotIn("Gold/hour", text)

    def test_report_rejects_silent_multi_character_combination(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out, _ = self.parse_fixture("current_savedvariables.lua", base)
            snapshot_path = out / "snapshots.csv"
            rows = self.read_csv(snapshot_path)
            fields = list(rows[0])
            extra = dict(rows[0], record_id="other-snapshot", character="Otherchar")
            with snapshot_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader(); writer.writerows([*rows, extra])
            db = base / "test.sqlite"
            import_directory(out, db)
            with self.assertRaisesRegex(ValueError, "multiple characters"):
                generate_report(db, base / "report.md", report_date="2026-05-31", timezone_name="UTC")

    def test_upload_package_contains_privacy_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "data/raw/RingoWoWOps.lua"
            processed = root / "data/processed"
            raw.parent.mkdir(parents=True); processed.mkdir(parents=True)
            raw.write_text("sanitized", encoding="utf-8")
            (processed / "daily_report.md").write_text("sanitized", encoding="utf-8")
            config = {
                "wow_path": str(root), "account": "TEST",
                "raw_output": "data/raw/RingoWoWOps.lua",
                "processed_dir": "data/processed",
                "sqlite_db": "data/test.sqlite",
                "daily_report": "data/processed/daily_report.md",
            }
            with patch.object(rwo, "PROJECT_ROOT", root), patch.object(rwo, "update", return_value=None):
                rwo.make_upload_zip(config)
            packages = list((root / "data/upload").glob("*.zip"))
            self.assertEqual(len(packages), 1)
            with zipfile.ZipFile(packages[0]) as archive:
                self.assertIn("upload_manifest.json", archive.namelist())
                manifest = json.loads(archive.read("upload_manifest.json"))
                self.assertIn("private raw WoW SavedVariables", manifest["privacy_warning"])
                self.assertEqual(manifest["network_transmission"], "none; this command creates a local ZIP only")
                raw_entries = [item for item in manifest["files"] if item["privacy"] == "private_raw_savedvariables"]
                self.assertEqual(len(raw_entries), 1)


if __name__ == "__main__":
    unittest.main()
