import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import farm
import import_to_sqlite as importer
import rwo
from parse_savedvariables import export_normalized, lua_table_to_py, write_csv
from generate_daily_report import generate_report, report_window


class FarmTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute((ROOT/'tests/fixtures/wow_api_mock.lua').read_text())
        self.lua.globals().date=lambda fmt,stamp: datetime.fromtimestamp(stamp,timezone.utc).strftime(fmt.lstrip('!'))
        self.load()
        self.lua.execute("fire('ADDON_LOADED','RingoWoWOps'); fire('PLAYER_LOGIN'); fire('PLAYER_ENTERING_WORLD',true,false)")

    def load(self):
        for name in ('FarmPresets.lua','FarmCore.lua','FarmDashboard.lua','RingoWoWOps.lua'):
            self.lua.execute((ROOT/'addon/RingoWoWOps'/name).read_text(encoding='utf-8'))

    def command(self,text): self.lua.globals().SlashCmdList.RINGOWOWOPS(text)
    def runrow(self):
        value=self.lua.globals().RingoWoWOpsFarm.Current()
        return lua_table_to_py(value) if value else None
    def rows(self,table): return lua_table_to_py(self.lua.globals().RingoWoWOpsDB[table]) or []
    def advance(self,seconds=30): self.lua.globals().clock+=seconds
    def prepare_start(self): self.command('farm prepare'); self.command('farm start')
    def complete(self):
        self.prepare_start(); self.advance(); self.lua.globals().gold-=123
        self.command('farm finish'); self.command('farm complete')
    def reload(self,clean=True,is_reload=True):
        if clean: self.lua.execute("fire('PLAYER_LOGOUT')")
        # Simulate a new Lua process's event registrations, preserving only SV.
        self.lua.execute('frames={}; RingoWoWOpsFarmWindow=nil')
        self.load()
        self.lua.execute("fire('ADDON_LOADED','RingoWoWOps'); fire('PLAYER_LOGIN')")
        self.lua.globals().fire('PLAYER_ENTERING_WORLD',not is_reload,is_reload)

    def export(self):
        self.lua.execute('''function serialize(value)
          if type(value)=='table' then local parts={}; for k,v in pairs(value) do
            table.insert(parts,'['..serialize(k)..']='..serialize(v)) end
            return '{'..table.concat(parts,',')..'}'
          elseif type(value)=='string' then return string.format('%q',value)
          else return tostring(value) end end''')
        source=self.base/'saved.lua'
        source.write_text('RingoWoWOpsDB='+self.lua.globals().serialize(self.lua.globals().RingoWoWOpsDB),encoding='utf-8')
        out=self.base/'processed'; metadata=export_normalized(source,out)
        return out,metadata

    def test_registry_and_disabled_presets(self):
        self.assertEqual(len(farm.presets()),3)
        for name in ('BOTANICA_TANK_HR','SHADOW_LAB_MAGE_BOOST','unknown'):
            self.command('farm prepare '+name)
        self.assertEqual(self.rows('farm_runs'),[])
        self.assertTrue(farm.presets()['STRATHOLME_PALADIN']['enabled'])
        self.assertNotIn('instance_id',farm.presets()['STRATHOLME_PALADIN'])

    def test_state_machine_and_immutable_terminal_history(self):
        self.command('farm finish'); self.assertEqual(self.rows('farm_runs'),[])
        self.command('farm prepare'); header=self.rows('farm_runs')[0]
        self.command('farm complete'); self.assertEqual(len(self.rows('farm_run_events')),1)
        self.command('farm start'); self.assertEqual(self.runrow()['status'],'running')
        self.command('farm start'); self.command('farm prepare'); self.assertEqual(len(self.rows('farm_runs')),1)
        self.advance(); self.command('farm finish'); self.assertEqual(self.runrow()['status'],'review')
        self.command('farm complete'); self.assertIsNone(self.runrow())
        events=self.rows('farm_run_events'); self.command('farm note forbidden'); self.command('farm complete')
        self.assertEqual(events,self.rows('farm_run_events')); self.assertEqual(header,self.rows('farm_runs')[0])
        self.assertEqual(events[-1]['duration_seconds'],30)
        self.assertTrue(events[-1]['reset_confirmed'])

    def test_abandon_requires_confirmation(self):
        self.prepare_start(); self.command('farm abandon')
        self.assertEqual(self.runrow()['status'],'running')
        self.command('farm abandon confirm'); self.assertIsNone(self.runrow())
        last=self.rows('farm_run_events')[-1]
        self.assertEqual(last['status'],'abandoned'); self.assertNotIn('finished_at',last)

    def test_reload_preserves_ids_and_active_timer(self):
        self.prepare_start(); before=self.rows('farm_run_events'); header=self.rows('farm_runs')
        self.advance(); self.reload()
        self.assertEqual(self.runrow()['status'],'running')
        self.assertEqual(self.rows('farm_runs'),header); self.assertEqual(self.rows('farm_run_events'),before)
        self.reload(); self.assertEqual(self.rows('farm_run_events'),before)

    def test_crash_and_normal_logout_never_invent_finish(self):
        for clean in (True,False):
            self.prepare_start(); self.advance(); self.reload(clean=clean,is_reload=False)
            last=self.rows('farm_run_events')[-1]
            self.assertEqual(last['status'],'incomplete')
            self.assertNotIn('finished_at',last); self.assertNotIn('duration_seconds',last)
            self.assertIsNone(self.runrow())

    def test_prepared_and_review_restore_after_clean_logout(self):
        self.command('farm prepare'); self.reload(is_reload=False)
        self.assertEqual(self.runrow()['status'],'prepared')
        self.command('farm start'); self.advance(); self.command('farm finish'); self.reload(is_reload=False)
        self.assertEqual(self.runrow()['status'],'review')
        self.assertEqual(self.runrow()['duration_seconds'],30)

    def test_character_isolation(self):
        self.prepare_start(); first=self.runrow()['farm_run_id']
        self.lua.globals().character='Other'; self.assertIsNone(self.runrow())
        self.prepare_start(); self.assertNotEqual(first,self.runrow()['farm_run_id'])
        self.lua.globals().character='Testpal'; self.assertEqual(first,self.runrow()['farm_run_id'])
        self.assertEqual(len(self.rows('farm_runs')),2)

    def test_missing_gold_and_negative_delta(self):
        self.complete(); self.assertEqual(self.rows('farm_run_events')[-1]['raw_gold_delta_copper'],-123)
        self.lua.globals().gold=None; self.prepare_start(); self.advance(); self.command('farm finish')
        self.assertNotIn('raw_gold_delta_copper',self.runrow())

    def test_day_number_offset_and_unicode_notes(self):
        self.lua.execute('RingoWoWOpsFarm.Settings().day_offset_minutes=210')
        # 20:29 UTC is 23:59 in the selected fixed offset.
        self.lua.globals().clock=int(datetime(2026,5,31,20,29,tzinfo=timezone.utc).timestamp())
        self.prepare_start(); self.command('farm note یادداشت ماهیگیری')
        first=self.runrow(); self.assertEqual(first['run_number_local_day'],1)
        self.advance(1); self.command('farm finish'); self.command('farm complete')
        self.prepare_start(); self.assertEqual(self.runrow()['run_number_local_day'],2)
        self.command('farm abandon confirm'); self.advance(60)
        self.prepare_start(); self.assertEqual(self.runrow()['run_number_local_day'],1)
        out,_=self.export(); self.assertIn('یادداشت', (out/'farm_run_events.csv').read_text(encoding='utf-8'))

    def test_end_to_end_determinism_idempotency_and_foreign_keys(self):
        self.complete(); out,meta=self.export(); first=(out/'farm_run_events.csv').read_bytes()
        self.export(); self.assertEqual(first,(out/'farm_run_events.csv').read_bytes())
        self.assertEqual(meta['record_counts']['farm_runs'],1)
        self.assertEqual(meta['record_counts']['farm_run_events'],4)
        db=self.base/'db.sqlite'; result=importer.import_directory(out,db)
        self.assertEqual(result['inserted']['farm_run_events'],4)
        self.assertEqual(sum(importer.import_directory(out,db)['inserted'].values()),0)
        with closing(sqlite3.connect(db)) as conn:
            conn.row_factory=sqlite3.Row
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(farm.current_runs(conn)[0]['status'],'completed')
            self.assertEqual(conn.execute("SELECT count(*) FROM validation_errors WHERE dataset LIKE 'farm%'").fetchone()[0],0)

    def test_import_running_then_completed_is_append_only(self):
        self.prepare_start(); out,_=self.export(); db=self.base/'db.sqlite'; importer.import_directory(out,db)
        self.advance(); self.command('farm finish'); self.command('farm complete'); out,_=self.export()
        result=importer.import_directory(out,db)
        self.assertEqual(result['inserted']['farm_runs'],0)
        self.assertEqual(result['inserted']['farm_run_events'],2)
        self.assertEqual(sum(importer.import_directory(out,db)['inserted'].values()),0)

    def test_conflicting_id_keeps_original(self):
        self.complete(); out,_=self.export(); db=self.base/'db.sqlite'; importer.import_directory(out,db)
        rows=self.rows('farm_runs'); rows[0]['note']='conflict'; write_csv(out/'farm_runs.csv',rows)
        importer.import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertIsNone(conn.execute('SELECT note FROM farm_runs').fetchone()[0])
            self.assertEqual(conn.execute("SELECT count(*) FROM validation_errors WHERE code='farm_id_conflict'").fetchone()[0],1)

    def test_malformed_transition_and_duration_are_retained(self):
        self.complete()
        self.lua.execute('RingoWoWOpsDB.farm_run_events[3].duration_seconds=999')
        out,_=self.export()
        self.assertIn('invalid_farm_record',(out/'validation_errors.csv').read_text())
        self.assertIn('999',(out/'farm_run_events.csv').read_text())
        db=self.base/'db.sqlite'; importer.import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM farm_run_events').fetchone()[0],2)

    def v4(self):
        source=subprocess.check_output(['git','show','237318d:tools/import_to_sqlite.py'],cwd=ROOT,text=True)
        module={'__file__':str(ROOT/'tools/import_to_sqlite.py'),'__name__':'v4_fixture'}
        exec(compile(source,'v4_fixture','exec'),module)
        path=self.base/'v4.sqlite'
        with closing(sqlite3.connect(path)) as conn: module['apply_migrations'](conn)
        return path

    def test_v4_migration_backup_repeat_and_rollback(self):
        self.complete(); out,_=self.export(); db=self.v4()
        original=importer._execute_script_without_implicit_commit
        def fail(conn,script):
            original(conn,script)
            if 'CREATE TABLE farm_runs' in script: raise RuntimeError('farm DDL failure')
        with patch.object(importer,'_execute_script_without_implicit_commit',side_effect=fail):
            with self.assertRaises(RuntimeError): importer.import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],4)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='farm_runs'").fetchone())
        result=importer.import_directory(out,db); self.assertTrue(Path(result['backup']).exists())
        self.assertIsNone(importer.import_directory(out,db)['backup'])
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],importer.SCHEMA_VERSION)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_failed_farm_batch_rolls_back(self):
        self.complete(); out,_=self.export(); db=self.base/'db.sqlite'
        original=importer._import_farm
        def fail(*args):
            result=original(*args)
            if args[1]=='farm_run_events': raise RuntimeError('farm batch failure')
            return result
        with patch.object(importer,'_import_farm',side_effect=fail):
            with self.assertRaises(RuntimeError): importer.import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM farm_runs').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM import_batches').fetchone()[0],0)

    def test_locked_database_and_newer_schema(self):
        self.complete(); out,_=self.export(); db=self.base/'db.sqlite'; importer.import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            conn.execute('BEGIN EXCLUSIVE')
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError,'locked'): importer.import_directory(out,db)
            finally: conn.rollback()
            conn.execute(f'PRAGMA user_version={importer.SCHEMA_VERSION + 1}'); conn.commit()
        with self.assertRaisesRegex(RuntimeError,'newer'): importer.import_directory(out,db)

    def test_ui_buttons_timer_and_old_commands(self):
        self.command('ui')
        self.assertTrue(self.lua.globals().RingoWoWOpsFarmWindow.IsShown(self.lua.globals().RingoWoWOpsFarmWindow))
        self.lua.globals().clickText('Prepare'); self.lua.globals().clickText('Start Run')
        self.assertEqual(self.runrow()['status'],'running')
        before=self.rows('farm_run_events')
        self.lua.execute('for i=1,100 do RingoWoWOpsFarmWindow.scripts.OnUpdate(RingoWoWOpsFarmWindow,0.05) end')
        self.assertEqual(before,self.rows('farm_run_events'))
        self.lua.globals().clickText('Abandon...'); self.assertEqual(self.runrow()['status'],'running')
        self.lua.globals().clickText('Confirm Abandon'); self.assertIsNone(self.runrow())
        self.command('mini'); self.assertIsNotNone(self.lua.globals().RingoWoWOpsMiniPanel)
        self.command('income 1g service'); self.assertEqual(len(self.rows('ledger_entries')),1)
        self.command('snap'); self.command('note legacy note'); self.command('status')
        self.assertEqual(len(self.rows('notes')),1)

    def test_context_never_starts_or_completes_or_opens_in_combat(self):
        self.lua.execute('RingoWoWOpsFarm.Settings().auto_open=true; inside=true; combat=true; RingoWoWOpsFarm.ObserveContext()')
        self.assertIsNone(self.lua.globals().RingoWoWOpsFarmWindow)
        self.assertEqual(self.rows('farm_runs'),[])
        self.lua.execute('inside=false; RingoWoWOpsFarm.ObserveContext(); inside=true; combat=false; RingoWoWOpsFarm.ObserveContext()')
        self.assertIsNotNone(self.lua.globals().RingoWoWOpsFarmWindow)
        self.prepare_start(); self.lua.execute('inside=false; RingoWoWOpsFarm.ObserveContext()')
        self.assertEqual(self.runrow()['status'],'running')

    def test_report_scope_and_voided_ledger(self):
        self.complete(); self.command('income 1g service')
        rid=self.rows('ledger_entries')[0]['id']; self.command('ledger undo '+rid)
        out,_=self.export(); db=self.base/'db.sqlite'; importer.import_directory(out,db)
        result=generate_report(db,self.base/'report.md',report_date='2026-05-31',character='Testpal',realm='Testrealm')
        self.assertEqual(result['farm']['completed'],1)
        self.assertEqual(result['farm']['average_duration'],30)
        self.assertEqual(result['farm']['raw_total'],-123)
        self.assertEqual(result['economy']['active'],[])
        section=(self.base/'report.md').read_text().split('## Farm Runs')[1].split('## Activity')[0]
        self.assertIn('Raw gold change',section)
        for word in ('profit','Gold/hour','loot gold'): self.assertNotIn(word,section)
        result=generate_report(db,self.base/'other.md',report_date='2026-05-31',character='Other',realm='Testrealm')
        self.assertEqual(result['farm']['completed'],0)

    def test_private_exports_and_no_network_or_protected_actions(self):
        self.complete(); out,_=self.export()
        config={'raw_output':'missing.lua','processed_dir':str(out),'daily_report':str(out/'report.md')}
        with patch.object(rwo,'PROJECT_ROOT',self.base),patch.object(rwo,'update'): rwo.make_upload_zip(config)
        with zipfile.ZipFile(next((self.base/'data/upload').glob('*.zip'))) as archive:
            manifest=json.loads(archive.read('upload_manifest.json'))
            self.assertEqual(sum(f['privacy']=='private_farm_history' for f in manifest['files']),2)
        source='\n'.join((ROOT/'addon/RingoWoWOps'/n).read_text() for n in ('FarmCore.lua','FarmDashboard.lua'))
        for forbidden in ('ResetInstances(', 'InviteUnit(', 'SendChatMessage(', 'CastSpell', 'MoveForward', 'LootSlot('):
            self.assertNotIn(forbidden,source)
        self.assertNotIn('requests', (ROOT/'tools/farm.py').read_text())

    def test_history_paging_settings_and_focus(self):
        for _ in range(12): self.complete()
        self.command('ui'); self.lua.globals().RingoWoWOpsFarmDashboard.Tab('History')
        self.lua.globals().clickText('Older'); self.lua.globals().clickText('Newer')
        self.lua.globals().RingoWoWOpsFarmDashboard.Tab('Settings')
        self.lua.globals().clickText('Scale +')
        self.lua.globals().clickText('Window position: UNLOCKED')
        self.assertTrue(self.lua.globals().RingoWoWOpsFarm.Settings().locked)
        self.assertAlmostEqual(self.lua.globals().RingoWoWOpsFarm.Settings().scale,1.1)
        self.lua.globals().clickText('Reset position')
        self.reload(); self.assertTrue(self.lua.globals().RingoWoWOpsFarm.Settings().locked)
        self.assertEqual(len(self.rows('farm_runs')),12)
        self.assertEqual(len(self.rows('farm_run_events')),48)

    def test_invalid_transition_after_completion_and_event_conflict(self):
        self.complete(); out,_=self.export(); db=self.base/'db.sqlite'; importer.import_directory(out,db)
        rows=self.rows('farm_run_events')
        bad=dict(rows[-1],record_id='after-complete',revision=5,event_type='note_added',from_status='completed',note='bad')
        write_csv(out/'farm_run_events.csv',[*rows,bad])
        importer.import_directory(out,db)
        rows[-1]['note']='conflicting completed snapshot'
        write_csv(out/'farm_run_events.csv',rows); importer.import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM farm_run_events').fetchone()[0],4)
            codes={r[0] for r in conn.execute('SELECT code FROM validation_errors')}
            self.assertIn('invalid_farm_transition',codes); self.assertIn('farm_id_conflict',codes)

    def test_reordered_events_and_duplicate_conflicting_header(self):
        self.complete(); out,_=self.export(); db=self.base/'db.sqlite'
        write_csv(out/'farm_run_events.csv',list(reversed(self.rows('farm_run_events'))))
        self.assertEqual(importer.import_directory(out,db)['inserted']['farm_run_events'],4)
        self.lua.execute('''local old=RingoWoWOpsDB.farm_runs[1]; local other={}
          for k,v in pairs(old) do other[k]=v end
          other.preset_version=9; table.insert(RingoWoWOpsDB.farm_runs,other)''')
        out,_=self.export()
        db2=self.base/'duplicate.sqlite'; result=importer.import_directory(out,db2)
        self.assertEqual(result['inserted']['farm_runs'],1)
        self.assertEqual(result['inserted']['farm_run_events'],4)

    def test_partial_runs_report_and_calendar_boundary(self):
        _,start,end,_=report_window('2026-06-01','Asia/Tehran')
        self.lua.globals().clock=start
        self.complete(); self.prepare_start(); self.command('farm abandon confirm')
        self.prepare_start(); self.reload(clean=False,is_reload=False)
        self.lua.globals().clock=end; self.complete()
        out,_=self.export(); db=self.base/'db.sqlite'; importer.import_directory(out,db)
        result=generate_report(db,self.base/'report.md',report_date='2026-06-01',timezone_name='Asia/Tehran',character='Testpal',realm='Testrealm')
        self.assertEqual(result['farm']['completed'],1)
        self.assertEqual(result['farm']['abandoned'],1)
        self.assertEqual(result['farm']['incomplete'],1)
        self.assertEqual(result['farm']['average_duration'],30)

    def test_migration_preserves_phase2_rows_and_global_sequence(self):
        self.command('income 2g service'); ledger=self.rows('ledger_entries')
        sequence=self.lua.globals().RingoWoWOpsDB.settings.next_record_sequence
        self.lua.execute('RingoWoWOpsDB.schema_version=4')
        self.reload()
        self.assertEqual(ledger,self.rows('ledger_entries'))
        self.assertGreaterEqual(self.lua.globals().RingoWoWOpsDB.settings.next_record_sequence,sequence)
        self.assertEqual(self.rows('farm_runs'),[])
        db=self.v4()
        with closing(sqlite3.connect(db)) as conn:
            conn.execute("INSERT INTO source_identities(character,realm) VALUES('Preserved','Realm')")
            conn.commit(); before=conn.execute('SELECT * FROM source_identities').fetchall()
            importer.apply_migrations(conn)
            self.assertEqual(before,conn.execute('SELECT * FROM source_identities').fetchall())
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])


if __name__=='__main__': unittest.main()
