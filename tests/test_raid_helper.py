import io
import hashlib
import hmac
import json
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
import import_to_sqlite as importer
import raid_helper
import roster
import wcl

EVENT_ID = "1546729699479257104"
EVENT_KEY = f"raid-helper/{EVENT_ID}"
REPORT = "RxkpqFn98jt1BYMr"
RH_FIXTURE = ROOT / "tests/fixtures/raid_helper_event.json"
WCL_FIXTURE = ROOT / "tests/fixtures/wcl_report_fights.json"
SECOND_EVENT_ID = "1545073223689969799"
SECOND_RH_FIXTURE = ROOT / "tests/fixtures/raid_helper_event_1545073223689969799.json"


class FakeResponse:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.body


class RaidHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.db = self.base / "ops.sqlite"; self.archive = self.base / "raw" / EVENT_ID / "event.json"
        self.config = {"raid_helper": {"raw_dir": str(self.base / "raw")}}
        self.roster_csv = self.base / "roster.csv"
        self.roster_csv.write_text(
            "member_id,member_display_name,discord_user_id,game_version,region,realm,character_name,class,primary_role,main_alt,member_status,character_status,notes\n"
            "member-amir,Amir,111111111111111111,tbc-anniversary,eu,spineshatter,Amiringo,,,main,active,active,\n"
            "member-medalisa,Medalisa,,tbc-anniversary,eu,spineshatter,Medalisa,,,main,active,active,\n"
            "member-divinegg,Divinegg,,tbc-anniversary,eu,spineshatter,Divinegg,,,main,active,active,\n", encoding="utf-8")
        roster.import_roster(self.roster_csv, self.db)
        roster.upsert_event(self.db, source="raid-helper", external_id=EVENT_ID, title="Butter & Jam Hyjal",
                            scheduled_at="2026-09-13", instance="Hyjal", game_version="tbc-anniversary", region="eu", realm="spineshatter")

    def import_fixture(self):
        return raid_helper.run_import(EVENT_ID, self.config, self.db, offline_json=RH_FIXTURE)

    def add_wcl(self):
        wcl.run_import(REPORT, {"wcl": {"raw_dir": str(self.base / "wcl")}}, self.db, offline_json=WCL_FIXTURE)
        roster.link_report(self.db, EVENT_KEY, REPORT)

    def test_offline_shape_idempotency_event_identity_and_unique_signups(self):
        first = self.import_fixture(); second = self.import_fixture()
        self.assertEqual(first["signups"], 9); self.assertEqual(first["inserted"], 9)
        self.assertEqual(second["inserted"], 0); self.assertEqual(second["updated"], 0); self.assertEqual(second["unchanged"], 9)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM raid_events WHERE event_key=?", (EVENT_KEY,)).fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM raid_helper_signups").fetchone()[0], 9)
            self.assertEqual(conn.execute("SELECT count(*) FROM raid_helper_import_batches").fetchone()[0], 1)

    def test_exact_resolution_order_optional_fields_and_slash_is_unmatched(self):
        data = json.loads(RH_FIXTURE.read_text(encoding="utf-8")); data["signUps"][0]["userId"] = "111111111111111111"
        private = self.base / "private-match.json"; private.write_text(json.dumps(data), encoding="utf-8")
        raid_helper.run_import(EVENT_ID, self.config, self.db, offline_json=private)
        with closing(sqlite3.connect(self.db)) as conn:
            amir = conn.execute("SELECT resolution_method,resolved_member_id,resolved_character_key,spec_name FROM raid_helper_signups WHERE display_name='Amiringo'").fetchone()
            medalisa = conn.execute("SELECT resolution_method,resolved_character_key FROM raid_helper_signups WHERE display_name='Medalisa'").fetchone()
            slash = conn.execute("SELECT resolved_member_id,resolved_character_key FROM raid_helper_signups WHERE display_name='Eggslayer/Mosesa'").fetchone()
            divine = conn.execute("SELECT spec_name,signup_at FROM raid_helper_signups WHERE display_name='Divinegg'").fetchone()
        self.assertEqual(amir[:2], ("discord_id", "member-amir")); self.assertTrue(amir[2].endswith("/amiringo")); self.assertEqual(amir[3], "Holy")
        self.assertEqual(medalisa[0], "character_key"); self.assertTrue(medalisa[1].endswith("/medalisa"))
        self.assertEqual(slash, (None, None)); self.assertEqual(divine, (None, None))

    def test_private_id_is_hmac_only_and_removed_from_raw_storage(self):
        data = json.loads(RH_FIXTURE.read_text(encoding="utf-8")); data["signUps"][0]["userId"] = "111111111111111111"; data["signUps"][0]["notes"] = "private test note"
        private = self.base / "private.json"; private.write_text(json.dumps(data), encoding="utf-8")
        with patch.dict("os.environ", {"RWO_IDENTITY_HASH_KEY": "private-test-key"}):
            raid_helper.run_import(EVENT_ID, self.config, self.db, offline_json=private)
        archive = json.loads(self.archive.read_text(encoding="utf-8"))
        self.assertNotIn("userId", archive["signUps"][0]); self.assertNotIn("notes", archive["signUps"][0])
        with closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute("SELECT discord_user_id,discord_user_hash,notes,raw_record FROM raid_helper_signups WHERE display_name='Amiringo'").fetchone()
        expected = hmac.new(b"private-test-key", b"111111111111111111", hashlib.sha256).hexdigest()
        self.assertEqual(row[:3], (None, expected, "private test note"))
        self.assertNotIn("111111111111111111", row[3]); self.assertNotIn("userId", row[3]); self.assertNotIn("private test note", row[3])

    def test_discord_identity_multiple_characters_and_display_mismatch(self):
        with closing(sqlite3.connect(self.db)) as conn:
            guild_id = conn.execute("SELECT guild_id FROM guild_members WHERE member_id='member-amir'").fetchone()[0]
            conn.execute("INSERT INTO guild_characters VALUES('tbc-anniversary/eu/spineshatter/amiringoalt',?,'member-amir','tbc-anniversary','eu','spineshatter','spineshatter','Amiringoalt','amiringoalt',NULL,NULL,'alt','active','now','now')", (guild_id,))
            conn.commit()
        data = json.loads(RH_FIXTURE.read_text(encoding="utf-8")); data["signUps"][0].update(userId="111111111111111111", name="CompletelyDifferent")
        private = self.base / "mismatch.json"; private.write_text(json.dumps(data), encoding="utf-8")
        raid_helper.run_import(EVENT_ID, self.config, self.db, offline_json=private)
        with closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute("SELECT resolved_member_id,resolved_character_key,resolution_method FROM raid_helper_signups WHERE display_name='CompletelyDifferent'").fetchone()
        self.assertEqual(row, ("member-amir", None, "discord_id"))

    def test_missing_discord_exact_name_and_no_fuzzy_matching(self):
        data = json.loads(RH_FIXTURE.read_text(encoding="utf-8")); data["signUps"][0].pop("userId", None); data["signUps"][0]["name"] = "Amiring"
        private = self.base / "no-fuzzy.json"; private.write_text(json.dumps(data), encoding="utf-8")
        raid_helper.run_import(EVENT_ID, self.config, self.db, offline_json=private)
        with closing(sqlite3.connect(self.db)) as conn:
            fuzzy = conn.execute("SELECT resolved_member_id,resolved_character_key FROM raid_helper_signups WHERE display_name='Amiring'").fetchone()
            exact = conn.execute("SELECT resolution_method FROM raid_helper_signups WHERE display_name='Medalisa'").fetchone()
        self.assertEqual(fuzzy, (None, None)); self.assertEqual(exact[0], "character_key")

    def test_explicit_external_character_key_precedes_display_name(self):
        data = json.loads(RH_FIXTURE.read_text(encoding="utf-8")); data["signUps"][0].update(name="DifferentName", externalCharacterKey="tbc-anniversary/eu/spineshatter/divinegg")
        private = self.base / "explicit-key.json"; private.write_text(json.dumps(data), encoding="utf-8")
        raid_helper.run_import(EVENT_ID, self.config, self.db, offline_json=private)
        with closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute("SELECT resolved_character_key,resolution_method FROM raid_helper_signups WHERE display_name='DifferentName'").fetchone()
        self.assertEqual(row, ("tbc-anniversary/eu/spineshatter/divinegg", "external_character_key"))

    def test_conflicting_discord_ownership_stays_unresolved(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("INSERT INTO guilds VALUES('g-other','Other','other','tbc-anniversary','eu','spineshatter','spineshatter',1)")
            conn.execute("INSERT INTO guild_members VALUES('member-other','g-other','Other','other','111111111111111111','active',NULL,'now','now')")
            conn.execute("INSERT INTO guild_characters VALUES('tbc-anniversary/eu/spineshatter/other','g-other','member-other','tbc-anniversary','eu','spineshatter','spineshatter','Other','other',NULL,NULL,'main','active','now','now')")
            conn.commit()
        data = json.loads(RH_FIXTURE.read_text(encoding="utf-8")); data["signUps"][0]["userId"] = "111111111111111111"
        private = self.base / "conflict.json"; private.write_text(json.dumps(data), encoding="utf-8")
        raid_helper.run_import(EVENT_ID, self.config, self.db, offline_json=private)
        with closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute("SELECT resolved_member_id,resolved_character_key,resolution_method FROM raid_helper_signups WHERE display_name='Amiringo'").fetchone()
        self.assertEqual(row, (None, None, "discord_id_conflict"))

    def test_alias_matches_only_when_explicitly_configured(self):
        data = json.loads(RH_FIXTURE.read_text(encoding="utf-8")); data["signUps"][0]["name"] = "ExplicitAlias"
        private = self.base / "alias-event.json"; private.write_text(json.dumps(data), encoding="utf-8")
        raid_helper.run_import(EVENT_ID, self.config, self.db, offline_json=private)
        aliases = self.base / "aliases.json"
        aliases.write_text(json.dumps({"aliases": [{"game_version":"tbc-anniversary","region":"eu","realm":"spineshatter","raid_helper_name":"ExplicitAlias","external_character_key":"tbc-anniversary/eu/spineshatter/divinegg"}]}), encoding="utf-8")
        with_alias = {"raid_helper": {"raw_dir": str(self.base / "raw"), "identity_aliases_file": str(aliases)}}
        raid_helper.run_import(EVENT_ID, with_alias, self.db, offline_json=private)
        with closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute("SELECT resolved_character_key,resolution_method FROM raid_helper_signups WHERE display_name='ExplicitAlias'").fetchone()
        self.assertEqual(row, ("tbc-anniversary/eu/spineshatter/divinegg", "explicit_alias"))

    def test_both_real_event_shapes_use_sanitized_fixtures(self):
        second_db = self.base / "second.sqlite"
        roster.import_roster(self.roster_csv, second_db)
        roster.upsert_event(second_db, source="raid-helper", external_id=SECOND_EVENT_ID, title="SSC TK Saturday 16:30",
                            scheduled_at="2026-09-05", instance="SSC/TK", game_version="tbc-anniversary", region="eu", realm="spineshatter")
        result = raid_helper.run_import(SECOND_EVENT_ID, self.config, second_db, offline_json=SECOND_RH_FIXTURE)
        self.assertEqual(result["signups"], 3)
        text = SECOND_RH_FIXTURE.read_text(encoding="utf-8")
        self.assertNotIn("userId", text); self.assertNotIn("discord", text.casefold()); self.assertNotIn("note", text.casefold())

    def test_atomic_archive_failure_preserves_previous_and_database(self):
        self.archive.parent.mkdir(parents=True); self.archive.write_text('{"kept":true}', encoding="utf-8")
        with patch("raid_helper.os.replace", side_effect=OSError("forced replace failure")):
            with self.assertRaisesRegex(OSError, "forced"): self.import_fixture()
        self.assertEqual(self.archive.read_text(encoding="utf-8"), '{"kept":true}')
        with closing(sqlite3.connect(self.db)) as conn: self.assertEqual(conn.execute("SELECT count(*) FROM raid_helper_signups").fetchone()[0], 0)
        self.assertEqual(list(self.archive.parent.glob("*.tmp")), [])

    def test_mocked_public_fetch_and_sanitized_error(self):
        seen=[]
        def opened(request, timeout): seen.append(request.full_url); return FakeResponse(RH_FIXTURE.read_bytes())
        raid_helper.run_import(EVENT_ID, self.config, self.db, opener=opened)
        self.assertEqual(seen, [f"https://raid-helper.xyz/api/v4/events/{EVENT_ID}"])
        def failed(request, timeout): raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, io.BytesIO())
        with self.assertRaisesRegex(raid_helper.RaidHelperError, "HTTP 404") as caught: raid_helper.fetch_event(EVENT_ID, opener=failed)
        self.assertNotIn("userId", str(caught.exception))

    def test_reconciliation_categories_and_unmatched_preservation(self):
        self.import_fixture(); self.add_wcl(); result = raid_helper.reconcile(self.db, EVENT_KEY)
        self.assertEqual((result["signups"], result["matched"], result["unresolved"]), (9, 3, 6))
        self.assertEqual(result["categories"]["signed_up_and_attended"], 1)
        self.assertEqual(result["categories"]["tentative_attended"], 1)
        self.assertEqual(result["categories"]["bench_attended"], 1)
        self.assertEqual(result["categories"]["unmatched_signup"], 6)
        self.assertEqual(result["categories"]["unmatched_wcl_participant_pug"], 1)

    def test_v7_to_current_preserves_existing_domains_and_foreign_keys(self):
        self.add_wcl()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TABLE preserved(kind TEXT PRIMARY KEY)"); conn.executemany("INSERT INTO preserved VALUES(?)", [("farm",),("ledger",),("wcl",),("roster",)])
            conn.execute("DROP TABLE raid_helper_signups"); conn.execute("DROP TABLE raid_helper_import_batches")
            conn.execute("DELETE FROM migration_history WHERE version>=8"); conn.execute("PRAGMA user_version=7"); conn.commit()
        result = self.import_fixture(); self.assertTrue(Path(result["backup"]).exists())
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], importer.SCHEMA_VERSION)
            self.assertEqual(conn.execute("SELECT count(*) FROM preserved").fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT count(*) FROM wcl_fight_attendance").fetchone()[0], 9)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_v9_migration_scrubs_historical_raw_discord_ids(self):
        self.import_fixture()
        with closing(sqlite3.connect(self.db)) as conn:
            signup_key = conn.execute("SELECT signup_key FROM raid_helper_signups ORDER BY signup_key LIMIT 1").fetchone()[0]
            conn.execute("UPDATE raid_helper_signups SET discord_user_id='historical-private-id',raw_record=? WHERE signup_key=?",
                         ('{"name":"Fixture","userId":"historical-private-id","notes":"private"}', signup_key))
            conn.execute("DELETE FROM migration_history WHERE version=10"); conn.execute("PRAGMA user_version=9"); conn.commit()
            # Recreate the v9 shape so the v10 ALTER TABLE is exercised.
            conn.execute("DROP INDEX idx_raid_helper_signups_discord_hash")
            conn.execute("ALTER TABLE raid_helper_signups DROP COLUMN discord_user_hash"); conn.commit()
            importer.apply_migrations(conn)
            row = conn.execute("SELECT discord_user_id,raw_record,discord_user_hash FROM raid_helper_signups WHERE signup_key=?", (signup_key,)).fetchone()
            self.assertIsNone(row[0]); self.assertNotIn("historical-private-id", row[1]); self.assertNotIn("userId", row[1]); self.assertIsNone(row[2])
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 10)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migration_rollback_and_newer_schema_rejection(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("DROP TABLE raid_helper_signups"); conn.execute("DROP TABLE raid_helper_import_batches")
            conn.execute("DELETE FROM migration_history WHERE version>=8"); conn.execute("PRAGMA user_version=7"); conn.commit()
        with patch("import_to_sqlite._execute_script_without_implicit_commit", side_effect=RuntimeError("forced")):
            with self.assertRaisesRegex(RuntimeError, "forced"): self.import_fixture()
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 7)
            conn.execute(f"PRAGMA user_version={importer.SCHEMA_VERSION + 1}"); conn.commit()
        with self.assertRaisesRegex(RuntimeError, "newer"): self.import_fixture()

    def test_cli_output_contains_no_private_fields(self):
        config = self.base / "config.json"; config.write_text(json.dumps({"wow_path":str(self.base),"account":"x","sqlite_db":str(self.db),"raid_helper":self.config["raid_helper"]}), encoding="utf-8")
        data=json.loads(RH_FIXTURE.read_text(encoding="utf-8")); data["signUps"][0]["userId"]="111111111111111111"; private=self.base/"private-cli.json"; private.write_text(json.dumps(data), encoding="utf-8")
        process = subprocess.run([sys.executable, str(ROOT/"tools/rwo.py"), "raid-helper-import", "--config", str(config), "--event-id", EVENT_ID, "--offline-json", str(private)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn("111111111111111111", process.stdout+process.stderr); self.assertNotIn("note", process.stdout.casefold())


if __name__ == "__main__": unittest.main()
