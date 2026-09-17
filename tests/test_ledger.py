import csv
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

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from ledger import parse_money, normalize_ledger
from ledger_report import economy, totals, render_economy
from parse_savedvariables import export_normalized, lua_table_to_py, write_csv
from import_to_sqlite import import_directory, apply_migrations
import import_to_sqlite as importer
from generate_daily_report import generate_report, report_window
import rwo


def entry(**changes):
    row = dict(record_id='ledger-1', time=150, created_at=150, character='Testpal', realm='Testrealm',
               direction='in', category='service', amount_copper=100, amount_quality='exact',
               input_source='addon_command', schema_version=1, addon_schema_version=4)
    row.update(changes)
    return row


def observations(start=100, end=200, change=100):
    return [dict(record_id='s1', time=start, gold=1000), dict(record_id='s2', time=end, gold=1000+change)]


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def addon(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
            messages = {}; frames = {}; SlashCmdList = {}; clock = 150
            function print(s) table.insert(messages, s) end
            function time() return clock end
            function GetMoney() return 1000 end
            function UnitName() return 'Testpal' end
            function GetRealmName() return 'Testrealm' end
            function UnitClass() return 'Paladin','PALADIN' end
            function UnitFactionGroup() return 'Horde' end
            function UnitLevel() return 20 end
            function UnitXP() return 0 end
            function UnitXPMax() return 100 end
            function GetXPExhaustion() return 0 end
            function GetZoneText() return 'Test Zone' end
            function GetSubZoneText() return '' end
            function CreateFrame()
              local f = {}
              function f:RegisterEvent(e) end
              function f:SetScript(name, fn) self[name] = fn end
              table.insert(frames,f); return f
            end
        ''')
        lua.execute((ROOT / 'addon/RingoWoWOps/RingoWoWOps.lua').read_text())
        lua.execute("frames[#frames].OnEvent(nil,'ADDON_LOADED','RingoWoWOps')")
        return lua

    def command(self, lua, command):
        lua.globals().SlashCmdList['RINGOWOWOPS'](command)

    def rows(self, lua, dataset='ledger_entries'):
        return lua_table_to_py(lua.globals().RingoWoWOpsDB[dataset]) or []

    def export(self, rows=None, voids=None):
        out = self.base / 'csv'
        export_normalized(ROOT / 'tests/fixtures/current_savedvariables.lua', out)
        write_csv(out / 'ledger_entries.csv', rows if rows is not None else [entry()])
        write_csv(out / 'ledger_voids.csv', voids or [])
        return out

    def test_money_lua_python_shared_cases(self):
        cases = json.loads((ROOT / 'tests/fixtures/money_cases.json').read_text())
        lua = self.addon()
        for token, expected in cases['valid'].items():
            with self.subTest(token=token):
                self.assertEqual(parse_money(token), tuple(expected))
                before = len(self.rows(lua))
                self.command(lua, f'income {token} service')
                rows = self.rows(lua)
                self.assertEqual(len(rows), before+1)
                self.assertEqual([rows[-1]['amount_copper'],rows[-1]['amount_quality']], expected)
        for token in cases['invalid']:
            with self.subTest(token=token):
                with self.assertRaises(ValueError): parse_money(token)
                before = len(self.rows(lua))
                self.command(lua, f'income {token} service')
                self.assertEqual(len(self.rows(lua)), before)
        self.assertEqual(parse_money('0c',allow_zero=True),(0,'exact'))
        self.assertEqual(parse_money('~0c',allow_zero=True),(0,'estimated'))

    def test_addon_materials_and_no_partial_records(self):
        lua = self.addon()
        self.command(lua, 'income 250g craft --cost ~80g --materials mixed -- crafted legs')
        self.command(lua, 'income 25g service --cost 0c --materials customer -- enchanting tip')
        self.command(lua, 'income 50g activity --activity fishing -- catch sales')
        rows = self.rows(lua)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['player_material_cost_copper'],800000)
        self.assertEqual(rows[0]['material_cost_quality'],'estimated')
        self.assertEqual(rows[1]['player_material_cost_copper'],0)
        self.assertEqual(rows[2]['activity'],'fishing')
        for command in ['income 1g repair','expense 1g craft','income 1g adjustment',
                        'income 1g craft --cost 2g --materials customer',
                        'expense 1g repair --cost 0c','income 1g craft --materials invalid',
                        'income 1g craft --cost 1g --cost 2g','transfer sideways 1g Bankalt']:
            self.command(lua,command)
        self.assertEqual(len(self.rows(lua)),3)
        self.assertEqual(len(self.rows(lua,'snapshots')),3)

    def test_addon_void_ambiguous_id_and_reload(self):
        lua = self.addon()
        self.command(lua,'income 1g service')
        original = self.rows(lua)[0]
        lua.execute("RingoWoWOpsDB.ledger_entries[2] = {id='other-1',character='Testpal',realm='Testrealm'}")
        self.command(lua,'ledger undo 1')
        self.assertEqual(len(self.rows(lua,'ledger_voids')),0)
        lua.execute('RingoWoWOpsDB.ledger_entries[2] = nil')
        self.command(lua,'ledger undo 1')
        self.command(lua,'ledger undo 1')
        self.assertEqual(len(self.rows(lua,'ledger_voids')),1)
        seq = lua.globals().RingoWoWOpsDB.settings.next_record_sequence
        lua.execute((ROOT / 'addon/RingoWoWOps/RingoWoWOps.lua').read_text())
        lua.execute("frames[#frames].OnEvent(nil,'ADDON_LOADED','RingoWoWOps')")
        self.assertEqual(self.rows(lua)[0],original)
        self.assertEqual(lua.globals().RingoWoWOpsDB.settings.next_record_sequence,seq)
        self.assertEqual(len(self.rows(lua,'ledger_voids')),1)

    def test_addon_v3_migration_and_legacy_gift(self):
        lua = self.addon()
        lua.execute("RingoWoWOpsDB.schema_version=3; RingoWoWOpsDB.settings.next_record_sequence=42")
        lua.execute("frames[#frames].OnEvent(nil,'ADDON_LOADED','RingoWoWOps')")
        self.assertEqual(lua.globals().RingoWoWOpsDB.schema_version,4)
        self.assertEqual(lua.globals().RingoWoWOpsDB.settings.next_record_sequence,42)
        self.command(lua,'gift 250 Friend')
        self.command(lua,'train ambiguous training text')
        self.assertEqual(len(self.rows(lua)),0)
        self.assertEqual(len(self.rows(lua,'events')),2)
        self.assertEqual(self.rows(lua,'events')[0]['gold'],1000)
        self.command(lua,'transfer out 1g "Guild bank" retained ownership')
        self.assertEqual(self.rows(lua)[0]['counterparty'],'Guild bank')

    def test_strict_validation_and_customer_materials(self):
        for changes in [dict(amount_copper=1.5),dict(amount_copper=True),dict(amount_quality='maybe'),
                        dict(direction='out'),dict(category='gift'),dict(category='adjustment'),
                        dict(player_material_cost_copper=2,material_cost_quality='exact',material_provision='customer'),
                        dict(material_cost_quality='exact'),dict(schema_version=9)]:
            self.assertTrue(normalize_ledger('ledger_entries',entry(**changes))[1],changes)
        self.assertFalse(normalize_ledger('ledger_entries',entry(player_material_cost_copper=0,material_cost_quality='exact',material_provision='customer'))[1])

    def test_cash_signs_special_movements_and_materials(self):
        rows=[entry(amount_copper=1000,player_material_cost_copper=200,material_cost_quality='exact'),
              entry(direction='out',category='materials',amount_copper=200),
              entry(category='gift',amount_copper=50),entry(direction='out',category='transfer',amount_copper=100)]
        sums=totals(rows)
        self.assertEqual(sums['cash_result']['exact'],800)
        self.assertEqual(sums['movement']['exact'],750)

    def test_reconciliation_exact_estimated_partial_and_missing(self):
        result=economy([entry()],observations(),set(),100,200)
        self.assertEqual(result['status'],'reconciled_exact')
        estimated=economy([entry(amount_quality='estimated')],observations(),set(),100,200)
        self.assertEqual(estimated['status'],'provisional_estimates')
        self.assertEqual(estimated['provisional_residual'],0)
        self.assertEqual(estimated['exact_residual'],100)
        partial=economy([entry(),entry(record_id='outside',time=90,amount_copper=999)],observations(),set(),0,300)
        self.assertEqual(partial['status'],'partial_coverage')
        self.assertEqual(partial['interval_totals']['income']['exact'],100)
        self.assertEqual(partial['totals']['income']['exact'],1099)
        self.assertEqual(economy([],[],set(),0,300)['status'],'insufficient_observations')
        self.assertEqual(economy([],observations(),set(),100,200)['status'],'unexplained')
        self.assertEqual(economy([entry(time=100)],observations(),set(),100,200)['status'],'review_required')

    def test_void_and_one_sided_transfer_report(self):
        result=economy([entry(),entry(record_id='transfer',category='transfer',counterparty='Alt')],observations(),{'ledger-1'},100,200)
        self.assertEqual(result['totals']['cash_result']['exact'],0)
        self.assertEqual(len(result['one_sided']),1)
        self.assertEqual(len(result['voided']),1)

    def test_all_voided_movements_leave_only_unexplained_observation_change(self):
        rows = [entry(record_id='receipt', player_material_cost_copper=50, material_cost_quality='estimated'),
                entry(record_id='expense', direction='out', category='materials'),
                entry(record_id='transfer-in', category='transfer', counterparty='Alt'),
                entry(record_id='transfer-out', direction='out', category='transfer', counterparty='Alt'),
                entry(record_id='gift-in', category='gift', counterparty='Friend', amount_quality='estimated'),
                entry(record_id='gift-out', direction='out', category='gift', counterparty='Friend')]
        result = economy(rows, observations(change=-123), {r['record_id'] for r in rows}, 0, 300)
        self.assertEqual(len(result['voided']), 6)
        self.assertEqual(result['active'], [])
        for group in ('totals', 'interval_totals'):
            self.assertTrue(all(value == 0 for qualities in result[group].values() for value in qualities.values()))
        self.assertEqual(result['status'], 'partial_coverage')
        self.assertEqual(result['exact_residual'], -123)
        self.assertEqual(result['provisional_residual'], -123)
        text = '\n'.join(render_economy(result, str, str))
        self.assertIn('Requested-window totals', text)
        self.assertIn('Observed-interval totals', text)
        self.assertIn('not additive totals', text)
        self.assertEqual(text.count('- Voided entry:'), 6)
        self.assertNotIn('Declared material margin', text)
        self.assertNotIn('profit/hour', text.lower())

    def test_repeated_import_conflict_and_foreign_keys(self):
        out=self.export(); db=self.base/'db.sqlite'
        self.assertEqual(import_directory(out,db)['inserted']['ledger_entries'],1)
        self.assertEqual(sum(import_directory(out,db)['inserted'].values()),0)
        write_csv(out/'ledger_entries.csv',[entry(amount_copper=900)])
        import_directory(out,db); import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT amount_copper FROM ledger_entries').fetchone()[0],100)
            self.assertEqual(conn.execute("SELECT count(*) FROM validation_errors WHERE code='ledger_id_conflict'").fetchone()[0],1)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_void_import_and_invalid_rows(self):
        void=dict(record_id='void-1',entry_id='ledger-1',time=170,created_at=170,character='Testpal',realm='Testrealm',
                  input_source='addon_command',reason='manual undo',schema_version=1,addon_schema_version=4)
        out=self.export([entry(),entry(record_id='bad',amount_copper='1.5')],[void]); db=self.base/'db.sqlite'
        first=import_directory(out,db)
        self.assertEqual(first['inserted']['ledger_entries'],1)
        self.assertEqual(first['inserted']['ledger_voids'],1)
        self.assertEqual(sum(import_directory(out,db)['inserted'].values()),0)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def v3_database(self):
        # Build an authentic v3 fixture using the approved base implementation.
        source=subprocess.check_output(['git','show','1224aac:tools/import_to_sqlite.py'],cwd=ROOT,text=True)
        module={ '__file__':str(ROOT/'tools/import_to_sqlite.py'), '__name__':'phase1_fixture' }
        exec(compile(source,'phase1_fixture','exec'),module)
        db=self.base/'v3.sqlite'
        with closing(sqlite3.connect(db)) as conn:
            module['apply_migrations'](conn)
        return db

    def test_v3_migration_backup_repeat_and_rollback(self):
        db=self.v3_database(); out=self.export()
        original=importer._execute_script_without_implicit_commit
        def fail(conn,script):
            original(conn,script)
            if 'CREATE TABLE ledger_entries' in script: raise RuntimeError('after ledger DDL')
        with patch.object(importer,'_execute_script_without_implicit_commit',side_effect=fail):
            with self.assertRaises(RuntimeError): import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertFalse(conn.execute("SELECT 1 FROM sqlite_master WHERE name='ledger_entries'").fetchone())
        first=import_directory(out,db)
        self.assertTrue(Path(first['backup']).exists())
        self.assertIsNone(import_directory(out,db)['backup'])
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],4)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_failed_batch_rolls_back_and_newer_schema_rejected(self):
        out=self.export([entry(),entry(record_id='second')]); db=self.base/'db.sqlite'
        original=importer._import_ledger
        def fail(conn,dataset,row,*args):
            result=original(conn,dataset,row,*args)
            if row.get('record_id')=='second': raise RuntimeError('batch failure')
            return result
        with patch.object(importer,'_import_ledger',side_effect=fail):
            with self.assertRaises(RuntimeError): import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM ledger_entries').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM import_batches').fetchone()[0],0)
            conn.execute('PRAGMA user_version=5'); conn.commit()
        with self.assertRaisesRegex(RuntimeError,'newer'): import_directory(out,db)

    def test_parser_preserves_malformed_and_conflicts(self):
        source=self.base/'source.lua'
        source.write_text('''RingoWoWOpsDB={version="0.4.0",ledger_entries={
          {id="x",time=150,created_at=150,character="Testpal",realm="Testrealm",direction="in",category="service",amount_copper=100,amount_quality="exact",input_source="addon_command",schema_version=1,addon_schema_version=4},
          {id="x",time=150,created_at=150,character="Testpal",realm="Testrealm",direction="in",category="service",amount_copper=101,amount_quality="exact",input_source="addon_command",schema_version=1,addon_schema_version=4},
          {id="bad",amount_copper=1.5}, "broken"}}''')
        out=self.base/'parsed'; metadata=export_normalized(source,out)
        first=(out/'ledger_entries.csv').read_bytes()
        export_normalized(source,out)
        self.assertEqual(first,(out/'ledger_entries.csv').read_bytes())
        self.assertEqual(metadata['record_counts']['ledger_entries'],3)
        self.assertIn('ledger_id_conflict',(out/'validation_errors.csv').read_text())
        self.assertIn('1.5',(out/'ledger_entries.csv').read_text())

    def test_csv_cannot_repair_parser_rejected_record(self):
        # A table-valued identity becomes text in CSV. It must not become trusted.
        out=self.export([entry(character="['invalid source table']",validation_status='error')])
        db=self.base/'db.sqlite'
        self.assertEqual(import_directory(out,db)['inserted']['ledger_entries'],0)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM validation_errors WHERE code='invalid_ledger_record'").fetchone()[0],1)

    def test_timezone_boundaries_scope_and_date_range(self):
        _,start,end,_=report_window('2026-05-31','Asia/Tehran')
        self.assertEqual(end-start,86400)
        out=self.export([entry(time=start),entry(record_id='excluded',time=end),
                         entry(record_id='other',time=start,character='Other'),
                         entry(record_id='realm',time=start,realm='Otherrealm')])
        db=self.base/'db.sqlite'; import_directory(out,db)
        report=self.base/'report.md'
        result=generate_report(db,report,report_date='2026-05-31',timezone_name='Asia/Tehran',character='Testpal',realm='Testrealm')
        self.assertEqual(result['economy']['totals']['income']['exact'],100)
        result=generate_report(db,report,report_date='2026-05-31',end_date='2026-06-02',timezone_name='Asia/Tehran',character='Testpal',realm='Testrealm')
        self.assertEqual(result['economy']['totals']['income']['exact'],200)
        with self.assertRaisesRegex(ValueError,'multiple characters'):
            generate_report(db,report,report_date='2026-05-31',timezone_name='Asia/Tehran')

    def test_upload_financial_privacy(self):
        root=self.base; processed=root/'data/processed'; processed.mkdir(parents=True)
        for name in ('ledger_entries','ledger_voids'): (processed/f'{name}.csv').write_text('sanitized')
        config={'raw_output':'data/raw/source.lua','processed_dir':'data/processed','daily_report':'data/processed/report.md'}
        with patch.object(rwo,'PROJECT_ROOT',root),patch.object(rwo,'update'):
            rwo.make_upload_zip(config)
        with zipfile.ZipFile(next((root/'data/upload').glob('*.zip'))) as archive:
            manifest=json.loads(archive.read('upload_manifest.json'))
            self.assertEqual(len([f for f in manifest['files'] if f['privacy']=='private_financial_history']),2)
            self.assertIn('none',manifest['network_transmission'])

    def test_addon_login_logout_and_crash_recovery(self):
        lua=self.addon()
        lua.execute("frames[#frames].OnEvent(nil,'PLAYER_LOGIN')")
        self.command(lua,'income 1g service')
        session_id=self.rows(lua)[0]['session_id']
        lua.execute("clock=160; frames[#frames].OnEvent(nil,'PLAYER_LOGOUT')")
        self.assertEqual(self.rows(lua,'sessions')[0]['status'],'completed')
        lua.execute((ROOT/'addon/RingoWoWOps/RingoWoWOps.lua').read_text())
        lua.execute("frames[#frames].OnEvent(nil,'ADDON_LOADED','RingoWoWOps'); frames[#frames].OnEvent(nil,'PLAYER_LOGIN')")
        self.assertEqual(len(self.rows(lua)),1)
        self.assertEqual(self.rows(lua)[0]['session_id'],session_id)
        lua.execute((ROOT/'addon/RingoWoWOps/RingoWoWOps.lua').read_text())
        lua.execute("frames[#frames].OnEvent(nil,'ADDON_LOADED','RingoWoWOps'); frames[#frames].OnEvent(nil,'PLAYER_LOGIN')")
        self.assertEqual(self.rows(lua,'sessions')[1]['status'],'incomplete')
        self.assertEqual(len(self.rows(lua)),1)

    def test_database_constraints_and_ledger_lock(self):
        out=self.export(); db=self.base/'db.sqlite'; import_directory(out,db)
        with closing(sqlite3.connect(db)) as conn:
            for assignment in ["amount_copper=0", "amount_copper=1.5", "direction='out'",
                               "amount_quality='unknown'", "material_cost_quality='exact'",
                               "category='transfer',counterparty=NULL"]:
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(f'UPDATE ledger_entries SET {assignment}')
                conn.rollback()
            conn.execute('BEGIN EXCLUSIVE')
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError,'locked'): import_directory(out,db)
            finally: conn.rollback()
            self.assertEqual(conn.execute('SELECT count(*) FROM ledger_entries').fetchone()[0],1)

    def test_backup_retains_committed_wal_and_v3_records(self):
        db=self.v3_database()
        with closing(sqlite3.connect(db)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("INSERT INTO source_identities(character,realm) VALUES('Preserved','Realm')")
            writer.commit()
            backup=importer.backup_database(db)
            with closing(sqlite3.connect(backup)) as conn:
                self.assertEqual(conn.execute('SELECT character FROM source_identities').fetchone()[0],'Preserved')
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        import_directory(self.export(),db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM source_identities WHERE character='Preserved'").fetchone()[0],1)

    def test_report_exact_full_pipeline_and_conflict_review(self):
        _,start,end,_=report_window('2026-05-31','UTC')
        out=self.export([entry(time=start+100)])
        write_csv(out/'snapshots.csv',[
            dict(record_id='open',time=start,gold=1000,character='Testpal',realm='Testrealm'),
            dict(record_id='close',time=end,gold=1100,character='Testpal',realm='Testrealm')])
        db=self.base/'db.sqlite'; import_directory(out,db)
        report=self.base/'report.md'
        result=generate_report(db,report,report_date='2026-05-31',character='Testpal',realm='Testrealm')
        self.assertEqual(result['economy']['status'],'reconciled_exact')
        write_csv(out/'ledger_entries.csv',[entry(time=start+100,amount_copper=200)])
        import_directory(out,db)
        result=generate_report(db,report,report_date='2026-05-31',character='Testpal',realm='Testrealm')
        self.assertEqual(result['economy']['status'],'review_required')

    def test_addon_savedvariables_to_sqlite_end_to_end(self):
        lua=self.addon()
        lua.execute("frames[#frames].OnEvent(nil,'PLAYER_LOGIN')")
        self.command(lua,'income 250g craft --cost ~80g --materials mixed -- crafted legs')
        self.command(lua,'expense 80g materials cloth')
        self.command(lua,'giftout 1g Friend')
        lua.execute("clock=160; frames[#frames].OnEvent(nil,'PLAYER_LOGOUT')")
        lua.execute('''
          function serialize(value)
            if type(value)=='table' then
              local parts={}
              for key,item in pairs(value) do
                table.insert(parts,'['..serialize(key)..']='..serialize(item))
              end
              return '{'..table.concat(parts,',')..'}'
            elseif type(value)=='string' then return string.format('%q',value)
            else return tostring(value) end
          end
        ''')
        source=self.base/'SavedVariables.lua'
        source.write_text('RingoWoWOpsDB='+lua.globals().serialize(lua.globals().RingoWoWOpsDB),encoding='utf-8')
        out=self.base/'generated'; export_normalized(source,out)
        db=self.base/'db.sqlite'; first=import_directory(out,db)
        self.assertEqual(first['inserted']['ledger_entries'],3)
        # Source hash changes, but source IDs and domain payloads are unchanged.
        source.write_text(source.read_text(encoding='utf-8')+'\n-- later save\n',encoding='utf-8')
        export_normalized(source,out)
        self.assertEqual(sum(import_directory(out,db)['inserted'].values()),0)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(conn.execute('SELECT count(*) FROM validation_errors').fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT player_material_cost_copper,material_cost_quality FROM ledger_entries WHERE category='craft'").fetchone(),(800000,'estimated'))


if __name__ == '__main__': unittest.main()
