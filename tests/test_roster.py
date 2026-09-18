import csv
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import import_to_sqlite as importer
import roster
import rwo
import wcl

REPORT = "RxkpqFn98jt1BYMr"
EVENT = "raid-helper/1546729699479257104"
HEADERS = ["member_id","member_display_name","discord_user_id","game_version","region","realm","character_name","class","primary_role","main_alt","member_status","character_status","notes"]


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.db = self.base / "ops.sqlite"; self.csv = self.base / "roster.csv"
        self.rows = [
            ["member-amir","Amir","","tbc-anniversary","eu","spineshatter","Amiringo","","","main","active","active",""],
            ["member-medalisa","Medalisa","","tbc-anniversary","eu","spineshatter","Medalisa","","","unspecified","active","active",""],
            ["member-divinegg","Divinegg","","tbc-anniversary","eu","spineshatter","Divinegg","","","unspecified","active","active",""]]
        self.write(self.rows)

    def write(self, rows):
        with self.csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle); writer.writerow(HEADERS); writer.writerows(rows)

    def migrate(self):
        with closing(sqlite3.connect(self.db)) as conn: importer.apply_migrations(conn)

    def wcl(self, code=REPORT):
        raw = json.loads((ROOT / "tests/fixtures/wcl_report_fights.json").read_text(encoding="utf-8"))
        body = json.dumps(raw).encode()
        return wcl.import_report(code, body, self.db, self.base / code / "fights.json", wcl.settings({"wcl": {}}))

    def event(self):
        return roster.upsert_event(self.db, source="raid-helper", external_id="1546729699479257104", title="Butter & Jam Hyjal", scheduled_at=None, instance="Hyjal", game_version="tbc-anniversary", region="eu", realm="spineshatter")

    def test_v6_to_v7_preserves_wcl_farm_ledger_and_foreign_keys(self):
        self.wcl()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TABLE preserved(kind TEXT PRIMARY KEY)"); conn.executemany("INSERT INTO preserved VALUES(?)", [("farm",),("ledger",)])
            for table in ("raid_event_reports","raid_events","roster_import_rejections","guild_characters","guild_members","guilds"): conn.execute(f"DROP TABLE {table}")
            conn.execute("DELETE FROM migration_history WHERE version=7"); conn.execute("PRAGMA user_version=6"); conn.commit()
        result = roster.import_roster(self.csv, self.db)
        self.assertTrue(Path(result["backup"]).exists())
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(conn.execute("SELECT count(*) FROM wcl_fights").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT count(*) FROM preserved").fetchone()[0], 2)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migration_rollback_and_newer_rejection(self):
        conn=sqlite3.connect(self.db); conn.execute("CREATE TABLE marker(v TEXT)"); conn.execute("INSERT INTO marker VALUES('kept')"); conn.execute("PRAGMA user_version=6"); conn.commit(); conn.close()
        with patch("import_to_sqlite._execute_script_without_implicit_commit", side_effect=RuntimeError("forced")):
            with self.assertRaisesRegex(RuntimeError,"forced"): roster.import_roster(self.csv,self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0],6); self.assertEqual(conn.execute("SELECT v FROM marker").fetchone()[0],"kept")
            conn.execute("PRAGMA user_version=8"); conn.commit()
        with self.assertRaisesRegex(RuntimeError,"newer"): roster.import_roster(self.csv,self.db)

    def test_roster_idempotency_updates_multiple_characters_and_uniqueness(self):
        first=roster.import_roster(self.csv,self.db); second=roster.import_roster(self.csv,self.db)
        self.assertEqual(first["inserted"],3); self.assertEqual(second["unchanged"],3)
        rows=self.rows+[["member-amir","Amir","","tbc-anniversary","eu","spineshatter","Amiralt","Mage","dps","alt","active","active",""]]
        self.write(rows); result=roster.import_roster(self.csv,self.db); self.assertEqual(result["inserted"],1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM guilds").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM guild_members").fetchone()[0],3)
            self.assertEqual(conn.execute("SELECT count(*) FROM guild_characters WHERE member_id='member-amir'").fetchone()[0],2)

    def test_versions_realms_normalization_optional_discord_and_safe_update(self):
        rows=[self.rows[0], ["member-cf","Classic Amir","","classic-forever","eu","spineshatter","Amiringo","","","main","active","active",""],
              ["member-other","Other Realm","","tbc-anniversary","eu","mirage-raceway","Ami ringo","","","main","active","active",""]]
        self.write(rows); roster.import_roster(self.csv,self.db)
        self.assertEqual(roster.external_character_key("TBC-ANNIVERSARY","EU","Spine Shatter","Ami-ringo"),"tbc-anniversary/eu/spineshatter/amiringo")
        rows[0][2]="123456789012345678"; rows[0][7]="Paladin"; self.write(rows)
        result=roster.import_roster(self.csv,self.db); self.assertEqual(result["updated"],1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM guild_characters").fetchone()[0],3)
            self.assertEqual(conn.execute("SELECT discord_user_id FROM guild_members WHERE member_id='member-amir'").fetchone()[0],rows[0][2])

    def test_conflicting_owner_and_invalid_rows_are_retained(self):
        roster.import_roster(self.csv,self.db)
        bad=[self.rows[0][:], ["member-other","Other","","tbc-anniversary","eu","spineshatter","Amiringo","","","main","active","active",""],
             ["member-bad","Bad","","tbc-anniversary","eu","spineshatter","","","","wrong","active","active",""]]
        self.write(bad); result=roster.import_roster(self.csv,self.db)
        self.assertEqual(result["rejected"],2)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT member_id FROM guild_characters WHERE external_character_key LIKE '%/amiringo'").fetchone()[0],"member-amir")
            self.assertEqual(conn.execute("SELECT count(*) FROM roster_import_rejections").fetchone()[0],2)

    def test_events_links_attendance_pugs_counts_and_multiple_reports(self):
        roster.import_roster(self.csv,self.db); self.wcl(); self.event()
        self.assertEqual(roster.link_report(self.db,EVENT,REPORT),"inserted"); self.assertEqual(roster.link_report(self.db,EVENT,REPORT),"unchanged")
        self.assertEqual(self.event()["action"],"unchanged")
        summary=roster.attendance_report(self.db,EVENT)
        self.assertEqual(summary["matched"],3); self.assertEqual(summary["unmatched"],1)
        known={p["display_name"]:p for p in summary["participants"] if p["matched_guild"]}
        self.assertEqual(known["Amiringo"]["attended"],3); self.assertEqual(known["Amiringo"]["attendance_percentage"],100.0)
        self.assertEqual(known["Medalisa"]["attended"],2); self.assertEqual(known["Divinegg"]["attended"],2)
        self.wcl("OtherRpt1"); roster.link_report(self.db,EVENT,"OtherRpt1")
        self.assertEqual(len(roster.attendance_report(self.db,EVENT)["participants"]),8)

    def test_missing_event_and_report_rejected(self):
        self.migrate()
        with self.assertRaisesRegex(roster.RosterError,"event not found"): roster.link_report(self.db,"missing/1",REPORT)
        self.event()
        with self.assertRaisesRegex(roster.RosterError,"report not found"): roster.link_report(self.db,EVENT,"Missing1")

    def test_cli_discord_privacy_and_upload_excludes_private_roster(self):
        self.rows[0][2]="999999999999999999"; self.write(self.rows)
        config=self.base/"config.json"; private=self.base/"data/private"; private.mkdir(parents=True); private_file=private/"guild_roster.csv"; private_file.write_bytes(self.csv.read_bytes())
        config.write_text(json.dumps({"wow_path":str(self.base),"account":"x","sqlite_db":str(self.db)}))
        process=subprocess.run([sys.executable,str(ROOT/"tools/rwo.py"),"roster-import","--config",str(config),"--input",str(private_file)],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(process.returncode,0,process.stderr); self.assertNotIn(self.rows[0][2],process.stdout+process.stderr)
        raw=self.base/"raw.lua"; raw.write_text("x"); processed=self.base/"processed"; processed.mkdir()
        report=self.base/"report.md"; report.write_text("x")
        upload_config={"wow_path":str(self.base),"account":"x","raw_output":str(raw),"processed_dir":str(processed),"daily_report":str(report)}
        with patch.object(rwo,"PROJECT_ROOT",self.base), patch.object(rwo,"update"):
            rwo.make_upload_zip(upload_config)
        with zipfile.ZipFile(next((self.base/"data/upload").glob("*.zip"))) as archive:
            self.assertFalse(any("guild_roster" in name or "private" in name for name in archive.namelist()))


if __name__ == "__main__": unittest.main()
