"""Farm record validation and append-only state projection; no financial inference."""
import json
import re
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from lupa import LuaRuntime

FARM_DATASETS = ('farm_runs', 'farm_run_events')
BASE_FIELDS = ('record_id', 'record_schema_version', 'preset_id', 'preset_version', 'status',
    'character', 'realm', 'session_id', 'started_at', 'finished_at', 'completed_at', 'duration_seconds',
    'start_zone', 'end_zone', 'start_instance_name', 'end_instance_name', 'instance_id', 'difficulty_id',
    'run_number_local_day', 'local_day', 'day_offset_minutes', 'start_gold_copper', 'end_gold_copper',
    'raw_gold_delta_copper', 'started_manually', 'finished_manually', 'reset_confirmed',
    'interruption_reason', 'note', 'created_at', 'updated_at', 'addon_schema_version', 'revision')
EVENT_FIELDS = BASE_FIELDS + ('farm_run_id', 'event_type', 'from_status', 'time')
FLAGS = {'started_manually', 'finished_manually', 'reset_confirmed'}
INTEGERS = {'record_schema_version','preset_version','started_at','finished_at','completed_at',
    'duration_seconds','instance_id','difficulty_id','run_number_local_day','day_offset_minutes',
    'start_gold_copper','end_gold_copper','raw_gold_delta_copper','created_at','updated_at',
    'addon_schema_version','revision','time'}
TERMINAL = {'completed','abandoned','incomplete'}
TRANSITIONS = {'prepared': {'started':'running','abandoned':'abandoned','interrupted':'incomplete','note_added':'prepared'},
    'running': {'finish_requested':'review','abandoned':'abandoned','interrupted':'incomplete','note_added':'running'},
    'review': {'completed':'completed','abandoned':'abandoned','interrupted':'incomplete','note_added':'review'}}


@lru_cache(maxsize=1)
def presets():
    lua = LuaRuntime()
    lua.execute((Path(__file__).resolve().parents[1] / 'addon/RingoWoWOps/FarmPresets.lua').read_text(encoding='utf-8'))
    return {p['id']: dict(p.items()) for _, p in lua.globals().RingoWoWOpsFarmPresets.items()}


def payload(dataset, row):
    return json.dumps({k: row.get(k) if row.get(k) != '' else None
                       for k in (BASE_FIELDS if dataset == 'farm_runs' else EVENT_FIELDS)},
                      sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def normalize(dataset, source):
    row = {k: (v if v != '' else None) for k,v in source.items()}
    row['record_id'] = row.get('record_id') or row.get('id')
    errors = []
    for k in INTEGERS:
        value = row.get(k)
        if isinstance(value,str) and re.fullmatch(r'-?[0-9]{1,16}',value): row[k]=int(value)
        if row.get(k) is not None and (type(row[k]) is not int or abs(row[k])>9_007_199_254_740_991): errors.append(f'{k}: integer required')
    for k in FLAGS:
        if isinstance(row.get(k),str) and row[k] in ('True','False','true','false','0','1'):
            row[k] = row[k] in ('True','true','1')
        if type(row.get(k)) is not bool: errors.append(f'{k}: boolean required')
    for k in ('record_id','character','realm','preset_id','status'):
        if not isinstance(row.get(k),str) or not row[k].strip(): errors.append(f'{k}: text required')
    fields = BASE_FIELDS if dataset == 'farm_runs' else EVENT_FIELDS
    for k in set(fields)-INTEGERS-FLAGS:
        if row.get(k) is not None and not isinstance(row[k],str): errors.append(f'{k}: text required')
    for k in ('created_at','updated_at','revision','preset_version','record_schema_version','addon_schema_version'):
        if type(row.get(k)) is not int or row[k]<0: errors.append(f'{k}: nonnegative integer required')
    if errors: return row, errors
    preset=presets().get(row['preset_id'])
    if not preset or not preset['enabled'] or row['preset_version']!=preset['version']: errors.append('unknown, disabled or unsupported preset version')
    if row['record_schema_version']!=1 or row['addon_schema_version']!=5: errors.append('unsupported farm record/addon schema')
    if row['status'] not in {'prepared','running','review',*TERMINAL}: errors.append('invalid status')
    if row['updated_at']<row['created_at']: errors.append('updated_at precedes creation')
    for k in ('started_at','finished_at','completed_at','duration_seconds','start_gold_copper','end_gold_copper','instance_id','difficulty_id'):
        if row.get(k) is not None and row[k]<0: errors.append(f'{k}: negative value')
    start, finish = row.get('started_at'), row.get('finished_at')
    if start is not None:
        if start<row['created_at'] or start>row['updated_at']: errors.append('invalid start time')
        offset=row.get('day_offset_minutes')
        if offset is None or not -720<=offset<=840: errors.append('invalid day offset')
        elif start<=253402250000:
            expected=datetime.fromtimestamp(start,timezone(timedelta(minutes=offset))).date().isoformat()
            if row.get('local_day')!=expected: errors.append('local day does not match start and offset')
        else: errors.append('start time out of calendar range')
        if type(row.get('run_number_local_day')) is not int or row['run_number_local_day']<1: errors.append('run number required')
        if not row['started_manually']: errors.append('start must be manual')
    elif any(row.get(k) is not None for k in ('local_day','day_offset_minutes','run_number_local_day','start_gold_copper')) or row['started_manually']:
        errors.append('start metadata without start')
    if finish is not None:
        if start is None or finish<start or finish>row['updated_at']: errors.append('invalid finish time')
        elif row.get('duration_seconds')!=finish-start: errors.append('duration must equal observed finish minus start')
        if not row['finished_manually']: errors.append('finish must be manual')
    elif row.get('duration_seconds') is not None or row['finished_manually'] or row.get('end_gold_copper') is not None:
        errors.append('finish metadata without observed finish')
    a,b=row.get('start_gold_copper'),row.get('end_gold_copper')
    expected=b-a if a is not None and b is not None else None
    if row.get('raw_gold_delta_copper')!=expected: errors.append('raw gold delta must use both observations, or remain missing')
    if row['status'] in ('running','review','completed') and start is None: errors.append('start required for this status')
    if row['status'] in ('review','completed') and finish is None: errors.append('finish required for this status')
    if row['status']=='completed':
        if row.get('completed_at') is None or finish is None or row['completed_at']<finish or row['completed_at']>row['updated_at'] or not row['reset_confirmed']:
            errors.append('completion requires finish and explicit reset confirmation')
    elif row.get('completed_at') is not None or row['reset_confirmed']: errors.append('completion fields on non-completed run')
    if row['status'] in ('incomplete','abandoned') and not row.get('interruption_reason'): errors.append('interruption/abandonment reason required')
    if dataset=='farm_runs':
        if row['status']!='prepared' or row['revision']!=0 or start is not None or finish is not None: errors.append('run header must be immutable prepared revision zero')
    else:
        if not row.get('farm_run_id') or not row.get('event_type') or not row.get('from_status'): errors.append('event relationship required')
        if row.get('time')!=row['updated_at'] or row['revision']<1: errors.append('invalid event time/revision')
    return row, errors


def transition_errors(header, previous, event):
    errors=[]
    for k in ('preset_id','preset_version','character','realm','created_at','record_schema_version','addon_schema_version'):
        if header.get(k)!=event.get(k): errors.append(f'changed immutable field {k}')
    event_type=event['event_type']
    if event['revision']!=previous['revision']+1: errors.append('missing or repeated revision')
    if event['time']<previous['updated_at']: errors.append('event time moved backwards')
    if event['revision']==1:
        if event_type!='prepared' or event['from_status']!='idle' or event['status']!='prepared': errors.append('first event must prepare')
    elif event['from_status']!=previous['status'] or TRANSITIONS.get(previous['status'],{}).get(event_type)!=event['status']:
        errors.append('invalid lifecycle transition')
    allowed = {'record_id','revision','updated_at','status'}
    allowed |= {'started': {'started_at','started_manually','session_id','start_zone','start_instance_name','difficulty_id',
                           'start_gold_copper','local_day','day_offset_minutes','run_number_local_day'},
                'finish_requested': {'finished_at','finished_manually','end_zone','end_instance_name','end_gold_copper','raw_gold_delta_copper','duration_seconds'},
                'completed': {'completed_at','reset_confirmed'},
                'note_added': {'note'}, 'abandoned': {'interruption_reason'}, 'interrupted': {'interruption_reason'}}.get(event_type,set())
    for k in set(BASE_FIELDS)-allowed:
        if previous.get(k)!=event.get(k): errors.append(f'{event_type} changed unrelated field {k}')
    if event_type=='started' and event.get('started_at')!=event['time']: errors.append('start timestamp differs from transition')
    if event_type=='finish_requested' and event.get('finished_at')!=event['time']: errors.append('finish timestamp differs from transition')
    if event_type=='completed' and event.get('completed_at')!=event['time']: errors.append('completion timestamp differs from transition')
    if event_type=='note_added' and (not event.get('note') or not event['note'].startswith(previous.get('note') or '')): errors.append('notes must append')
    return errors


def current_runs(conn):
    """Derive summaries without rewriting source rows or historical events."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='farm_runs'").fetchone(): return []
    headers={r['record_id']:dict(r) for r in conn.execute('SELECT * FROM farm_runs')}
    for event in conn.execute('SELECT * FROM farm_run_events ORDER BY farm_run_id,revision'):
        row=dict(event); row['record_id']=row['farm_run_id']; headers[row['farm_run_id']]=row
    return list(headers.values())


def summarize(rows, start, end, character=None, realm=None):
    scoped=[r for r in rows if start <= (r.get('started_at') if r.get('started_at') is not None else r['created_at']) < end
            and (not character or r['character']==character) and (not realm or r['realm']==realm)]
    completed=[r for r in scoped if r['status']=='completed']
    observed=[r['raw_gold_delta_copper'] for r in completed if r['raw_gold_delta_copper'] is not None]
    return dict(rows=scoped, completed=len(completed), incomplete=sum(r['status']=='incomplete' for r in scoped),
                abandoned=sum(r['status']=='abandoned' for r in scoped),
                average_duration=sum(r['duration_seconds'] for r in completed)/len(completed) if completed else None,
                fastest=min((r['duration_seconds'] for r in completed),default=None),
                raw_total=sum(observed) if observed else None, raw_count=len(observed))


def render(summary, money, timestamp):
    lines=['## Farm Runs','', '- Scope: runs started in the requested window; unstarted runs use preparation time.',
           f"- Completed: {summary['completed']}; incomplete: {summary['incomplete']}; abandoned: {summary['abandoned']}",
           f"- Average completed duration: {summary['average_duration'] if summary['average_duration'] is not None else 'unavailable'} seconds",
           f"- Fastest completed duration: {summary['fastest'] if summary['fastest'] is not None else 'unavailable'} seconds",
           f"- Total raw gold change: {money(summary['raw_total']) if summary['raw_total'] is not None else 'unobserved'} ({summary['raw_count']} completed runs with both observations)",
           '- Raw gold change is observed character balance movement, not classified revenue. No ledger entries are generated.','']
    for r in sorted(summary['rows'],key=lambda r:(r.get('started_at') or r['created_at'],r['record_id'])):
        lines.append(f"- #{r.get('run_number_local_day') or '--'} {r['preset_id']} / {r['status']} / {timestamp(r.get('started_at') or r['created_at'])} / duration {r.get('duration_seconds')} s / Raw gold change: {money(r['raw_gold_delta_copper']) if r.get('raw_gold_delta_copper') is not None else 'unobserved'} / note: {'yes' if r.get('note') else 'no'}")
    return lines+['']
