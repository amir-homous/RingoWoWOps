from contextlib import closing
import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_model import DATASETS, PHASE1_DATASETS, INTEGER_FIELDS, compatibility_id, normalize_record
from ledger import LEDGER_DATASETS, ENTRY_FIELDS, VOID_FIELDS, normalize_ledger, payload
import farm


SCHEMA_VERSION = 6

TABLE_COLUMNS = {
    "sessions": (
        "record_id", "original_id", "character_id", "character", "realm", "faction", "class",
        "started_at", "ended_at", "duration_seconds", "status", "level_start", "level_end",
        "zone_start", "zone_end", "xp_start", "xp_end", "gold_start", "gold_end",
        "activity_start", "activity_end", "start_source", "stop_source", "primary_realm",
        "source_file_sha256", "source_schema_version", "source_record_index", "validation_status",
        "import_batch_id",
    ),
    "snapshots": (
        "record_id", "session_id", "character_id", "character", "realm", "faction", "class",
        "time", "reason", "level", "zone", "subzone", "xp", "xp_max", "rested_xp", "gold",
        "bags_free", "activity", "activity_original", "primary_realm", "source_file_sha256",
        "source_schema_version", "source_record_index", "validation_status", "import_batch_id",
    ),
    "notes": (
        "record_id", "session_id", "character_id", "character", "realm", "time", "level", "zone",
        "activity", "activity_original", "category", "text", "primary_realm", "source_file_sha256",
        "source_schema_version", "source_record_index", "validation_status", "import_batch_id",
    ),
    "activities": (
        "record_id", "session_id", "character_id", "character", "realm", "time", "level", "zone",
        "activity", "activity_original", "source", "primary_realm", "source_file_sha256",
        "source_schema_version", "source_record_index", "validation_status", "import_batch_id",
    ),
    "events": (
        "record_id", "session_id", "character_id", "character", "realm", "time", "level", "zone",
        "type", "text", "details", "gold", "activity", "activity_original", "primary_realm",
        "source_file_sha256", "source_schema_version", "source_record_index", "validation_status",
        "import_batch_id",
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def database_needs_migration(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION
    finally:
        conn.close()


def backup_database(path: Path) -> Path | None:
    if not database_needs_migration(path):
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.stem}.pre_migration_v{SCHEMA_VERSION}_{stamp}{path.suffix}")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.stem}.pre_migration_v{SCHEMA_VERSION}_{stamp}_{counter}{path.suffix}")
        counter += 1
    with closing(sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
    return backup


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _execute_script_without_implicit_commit(conn: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            if statement.strip():
                conn.execute(statement)
            statement = ""
    if statement.strip():
        conn.execute(statement)


def apply_migrations(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(f"Database schema {current} is newer than supported schema {SCHEMA_VERSION}")
    if current == SCHEMA_VERSION:
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("""CREATE TABLE IF NOT EXISTS migration_history (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
        )""")

        for table in PHASE1_DATASETS:
            if _table_exists(conn, table) and "record_id" not in _table_columns(conn, table):
                legacy = f"legacy_{table}_pre_v2"
                if not _table_exists(conn, legacy):
                    conn.execute(f'ALTER TABLE "{table}" RENAME TO "{legacy}"')

        _execute_script_without_implicit_commit(conn, """
        CREATE TABLE IF NOT EXISTS import_batches (
            id TEXT PRIMARY KEY,
            source_file_sha256 TEXT NOT NULL,
            source_schema_version TEXT NOT NULL,
            source_path TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            status TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            UNIQUE(source_file_sha256, source_schema_version)
        );
        CREATE TABLE IF NOT EXISTS source_identities (
            id INTEGER PRIMARY KEY,
            character TEXT NOT NULL,
            realm TEXT NOT NULL,
            first_seen_at INTEGER,
            last_seen_at INTEGER,
            UNIQUE(character, realm)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            record_id TEXT PRIMARY KEY, original_id TEXT, character_id INTEGER,
            character TEXT NOT NULL, realm TEXT NOT NULL, faction TEXT, class TEXT,
            started_at INTEGER, ended_at INTEGER, duration_seconds INTEGER, status TEXT NOT NULL,
            level_start INTEGER, level_end INTEGER, zone_start TEXT, zone_end TEXT,
            xp_start INTEGER, xp_end INTEGER, gold_start INTEGER, gold_end INTEGER,
            activity_start TEXT, activity_end TEXT, start_source TEXT, stop_source TEXT,
            primary_realm INTEGER, source_file_sha256 TEXT NOT NULL, source_schema_version TEXT NOT NULL,
            source_record_index INTEGER, validation_status TEXT NOT NULL, import_batch_id TEXT NOT NULL,
            FOREIGN KEY(character_id) REFERENCES source_identities(id),
            FOREIGN KEY(import_batch_id) REFERENCES import_batches(id)
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            record_id TEXT PRIMARY KEY, session_id TEXT, character_id INTEGER,
            character TEXT NOT NULL, realm TEXT NOT NULL, faction TEXT, class TEXT,
            time INTEGER, reason TEXT, level INTEGER, zone TEXT, subzone TEXT, xp INTEGER,
            xp_max INTEGER, rested_xp INTEGER, gold INTEGER, bags_free INTEGER,
            activity TEXT, activity_original TEXT, primary_realm INTEGER,
            source_file_sha256 TEXT NOT NULL, source_schema_version TEXT NOT NULL,
            source_record_index INTEGER, validation_status TEXT NOT NULL, import_batch_id TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(record_id),
            FOREIGN KEY(character_id) REFERENCES source_identities(id),
            FOREIGN KEY(import_batch_id) REFERENCES import_batches(id)
        );
        CREATE TABLE IF NOT EXISTS notes (
            record_id TEXT PRIMARY KEY, session_id TEXT, character_id INTEGER,
            character TEXT NOT NULL, realm TEXT NOT NULL, time INTEGER, level INTEGER, zone TEXT,
            activity TEXT, activity_original TEXT, category TEXT, text TEXT, primary_realm INTEGER,
            source_file_sha256 TEXT NOT NULL, source_schema_version TEXT NOT NULL,
            source_record_index INTEGER, validation_status TEXT NOT NULL, import_batch_id TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(record_id),
            FOREIGN KEY(character_id) REFERENCES source_identities(id),
            FOREIGN KEY(import_batch_id) REFERENCES import_batches(id)
        );
        CREATE TABLE IF NOT EXISTS activities (
            record_id TEXT PRIMARY KEY, session_id TEXT, character_id INTEGER,
            character TEXT NOT NULL, realm TEXT NOT NULL, time INTEGER, level INTEGER, zone TEXT,
            activity TEXT, activity_original TEXT, source TEXT, primary_realm INTEGER,
            source_file_sha256 TEXT NOT NULL, source_schema_version TEXT NOT NULL,
            source_record_index INTEGER, validation_status TEXT NOT NULL, import_batch_id TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(record_id),
            FOREIGN KEY(character_id) REFERENCES source_identities(id),
            FOREIGN KEY(import_batch_id) REFERENCES import_batches(id)
        );
        CREATE TABLE IF NOT EXISTS events (
            record_id TEXT PRIMARY KEY, session_id TEXT, character_id INTEGER,
            character TEXT NOT NULL, realm TEXT NOT NULL, time INTEGER, level INTEGER, zone TEXT,
            type TEXT, text TEXT, details TEXT, gold INTEGER, activity TEXT, activity_original TEXT,
            primary_realm INTEGER, source_file_sha256 TEXT NOT NULL, source_schema_version TEXT NOT NULL,
            source_record_index INTEGER, validation_status TEXT NOT NULL, import_batch_id TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(record_id),
            FOREIGN KEY(character_id) REFERENCES source_identities(id),
            FOREIGN KEY(import_batch_id) REFERENCES import_batches(id)
        );
        CREATE TABLE IF NOT EXISTS validation_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, error_key TEXT UNIQUE, import_batch_id TEXT NOT NULL,
            dataset TEXT, source_record_index INTEGER, record_id TEXT, severity TEXT NOT NULL,
            code TEXT NOT NULL, field TEXT, message TEXT NOT NULL, raw_record TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(import_batch_id) REFERENCES import_batches(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_scope_time ON sessions(character, realm, started_at);
        CREATE INDEX IF NOT EXISTS idx_snapshots_scope_time ON snapshots(character, realm, time);
        CREATE INDEX IF NOT EXISTS idx_notes_scope_time ON notes(character, realm, time);
        CREATE INDEX IF NOT EXISTS idx_activities_scope_time ON activities(character, realm, time);
        CREATE INDEX IF NOT EXISTS idx_events_scope_time ON events(character, realm, time);
        CREATE INDEX IF NOT EXISTS idx_validation_batch ON validation_errors(import_batch_id, severity);
        """)
        if current < 4:
            _execute_script_without_implicit_commit(conn, Path(__file__).with_name("ledger_schema.sql").read_text(encoding="utf-8"))
            conn.execute("INSERT INTO migration_history(version,name,applied_at) VALUES(4,'manual_cash_ledger',?)", (utc_now(),))
        if current < 5:
            _execute_script_without_implicit_commit(conn, Path(__file__).with_name("farm_schema.sql").read_text(encoding="utf-8"))
            conn.execute("INSERT INTO migration_history(version,name,applied_at) VALUES(5,'farm_run_core',?)", (utc_now(),))
        if current < 6:
            _execute_script_without_implicit_commit(conn, Path(__file__).with_name("wcl_schema.sql").read_text(encoding="utf-8"))
            conn.execute("INSERT INTO migration_history(version,name,applied_at) VALUES(6,'warcraft_logs_v1',?)", (utc_now(),))
        if "error_key" not in _table_columns(conn, "validation_errors"):
            conn.execute("ALTER TABLE validation_errors ADD COLUMN error_key TEXT")
        for row in conn.execute("SELECT id,import_batch_id,dataset,source_record_index,code,field,message FROM validation_errors WHERE error_key IS NULL"):
            key = hashlib.sha256("\n".join(str(value or "") for value in row[1:]).encode("utf-8")).hexdigest()
            conn.execute("UPDATE validation_errors SET error_key=? WHERE id=?", (key, row[0]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_validation_error_key ON validation_errors(error_key)")
        if current < 2:
            conn.execute("INSERT OR IGNORE INTO migration_history(version,name,applied_at) VALUES(2,'typed_append_only_foundation',?)", (utc_now(),))
        if current < 3:
            conn.execute("INSERT OR IGNORE INTO migration_history(version,name,applied_at) VALUES(3,'idempotent_validation_errors',?)", (utc_now(),))
        conn.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _batch_id(source_hash: str, schema_version: str) -> str:
    return "batch-" + hashlib.sha256(f"{source_hash}\n{schema_version}".encode()).hexdigest()[:32]


def _manifest(csv_dir: Path) -> dict[str, Any]:
    path = csv_dir / "source_manifest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    digest = hashlib.sha256()
    for dataset in DATASETS:
        file = csv_dir / f"{dataset}.csv"
        if file.exists():
            digest.update(file.read_bytes())
    return {
        "source_file_sha256": digest.hexdigest(),
        "source_schema_version": "legacy-csv",
        "source_file": str(csv_dir),
    }


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _bool_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return 1 if str(value).lower() in {"true", "1", "yes"} else 0


def _identity_id(conn: sqlite3.Connection, row: dict[str, Any]) -> int | None:
    character, realm = str(row.get("character") or ""), str(row.get("realm") or "")
    if not character or not realm:
        return None
    timestamp = _int_or_none(row.get("time") or row.get("started_at"))
    conn.execute("""INSERT INTO source_identities(character,realm,first_seen_at,last_seen_at)
        VALUES(?,?,?,?) ON CONFLICT(character,realm) DO UPDATE SET
        first_seen_at=CASE WHEN excluded.first_seen_at IS NULL THEN first_seen_at
          WHEN first_seen_at IS NULL OR excluded.first_seen_at < first_seen_at THEN excluded.first_seen_at ELSE first_seen_at END,
        last_seen_at=CASE WHEN excluded.last_seen_at IS NULL THEN last_seen_at
          WHEN last_seen_at IS NULL OR excluded.last_seen_at > last_seen_at THEN excluded.last_seen_at ELSE last_seen_at END
    """, (character, realm, timestamp, timestamp))
    return conn.execute("SELECT id FROM source_identities WHERE character=? AND realm=?", (character, realm)).fetchone()[0]


def _prepare_row(dataset: str, row: dict[str, Any], manifest: dict, index: int) -> dict[str, Any]:
    source_hash = str(row.get("source_file_sha256") or manifest["source_file_sha256"])
    schema_version = str(row.get("source_schema_version") or manifest.get("source_schema_version") or "unknown")
    if not row.get("record_id"):
        row, _ = normalize_record(
            dataset, row, source_file_sha256=source_hash,
            source_schema_version=schema_version, source_record_index=index,
        )
    prepared = dict(row)
    prepared["source_file_sha256"] = source_hash
    prepared["source_schema_version"] = schema_version
    prepared["source_record_index"] = _int_or_none(prepared.get("source_record_index")) or index
    prepared["validation_status"] = prepared.get("validation_status") or "valid"
    prepared["primary_realm"] = _bool_int(prepared.get("primary_realm"))
    for field in INTEGER_FIELDS:
        if field in prepared:
            prepared[field] = _int_or_none(prepared[field])
    if dataset == "sessions":
        prepared["original_id"] = prepared.get("id") or prepared.get("original_id")
    return prepared


def _ledger_finding(conn, dataset, row, batch_id, index, code, message):
    raw = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
    key = hashlib.sha256(f"{batch_id}:{dataset}:{index}:{code}:{raw}".encode()).hexdigest()
    conn.execute("""INSERT OR IGNORE INTO validation_errors
        (error_key,import_batch_id,dataset,source_record_index,record_id,severity,code,field,message,raw_record,created_at)
        VALUES(?,?,?,?,?,'error',?,'',?,?,?)""",
        (key,batch_id,dataset,index,row.get('record_id') or row.get('id'),code,message,raw,utc_now()))


def _import_ledger(conn, dataset, source, manifest, index, batch_id):
    row, errors = normalize_ledger(dataset, source)
    if source.get('validation_status') == 'error':
        errors.append('Source parser rejected the original record; CSV text cannot repair it')
    if errors:
        _ledger_finding(conn,dataset,row,batch_id,index,'invalid_ledger_record','; '.join(errors))
        return 0
    logical = payload(dataset,row)
    previous = conn.execute(f'SELECT logical_payload FROM {dataset} WHERE record_id=?', (row['record_id'],)).fetchone()
    if previous:
        if previous[0] != logical:
            _ledger_finding(conn,dataset,row,batch_id,index,'ledger_id_conflict','Existing ID has a different payload; original retained')
        return 0
    if dataset == 'ledger_voids':
        target = conn.execute('SELECT character,realm FROM ledger_entries WHERE record_id=?',(row['entry_id'],)).fetchone()
        already = conn.execute('SELECT 1 FROM ledger_voids WHERE entry_id=?',(row['entry_id'],)).fetchone()
        if not target or tuple(target) != (row['character'],row['realm']) or already:
            _ledger_finding(conn,dataset,row,batch_id,index,'invalid_void_target','Missing, foreign, or already voided entry')
            return 0
    elif row.get('session_id'):
        session = conn.execute('SELECT character,realm FROM sessions WHERE record_id=?',(row['session_id'],)).fetchone()
        if session and tuple(session) != (row['character'],row['realm']):
            _ledger_finding(conn,dataset,row,batch_id,index,'invalid_session_identity','Session belongs to another identity')
            return 0
        # Keep an unresolved source session ID as a soft reference; never invent a session.
    fields = ENTRY_FIELDS if dataset == 'ledger_entries' else VOID_FIELDS
    values = {key: (row.get(key) if row.get(key) != '' else None) for key in fields}
    values.update(character_id=_identity_id(conn,row), source_file_sha256=manifest['source_file_sha256'],
        source_schema_version=str(manifest.get('source_schema_version','unknown')),
        source_record_index=index,source_dataset=dataset,import_batch_id=batch_id,
        logical_payload=logical,raw_record=source.get('raw_record') or json.dumps(source,sort_keys=True))
    conn.execute(f'INSERT INTO {dataset} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})',list(values.values()))
    return 1


def _import_farm(conn, dataset, source, manifest, index, batch_id):
    row, errors = farm.normalize(dataset, source)
    if source.get('validation_status') == 'error':
        errors.append('Parser rejected original farm record')
    if errors:
        _ledger_finding(conn,dataset,row,batch_id,index,'invalid_farm_record','; '.join(errors))
        return 0
    logical = farm.payload(dataset,row)
    old = conn.execute(f'SELECT logical_payload FROM {dataset} WHERE record_id=?',(row['record_id'],)).fetchone()
    if old:
        if old[0] != logical:
            _ledger_finding(conn,dataset,row,batch_id,index,'farm_id_conflict','Existing ID has different payload; retained original')
        return 0
    if dataset == 'farm_run_events':
        header = conn.execute('SELECT logical_payload FROM farm_runs WHERE record_id=?',(row['farm_run_id'],)).fetchone()
        previous = conn.execute('SELECT logical_payload FROM farm_run_events WHERE farm_run_id=? ORDER BY revision DESC LIMIT 1',(row['farm_run_id'],)).fetchone()
        if not header:
            errors = ['missing farm run header']
        else:
            header = json.loads(header[0])
            errors = farm.transition_errors(header,json.loads(previous[0]) if previous else header,row)
        if errors:
            _ledger_finding(conn,dataset,row,batch_id,index,'invalid_farm_transition','; '.join(errors))
            return 0
    if row.get('session_id'):
        identity = conn.execute('SELECT character,realm FROM sessions WHERE record_id=?',(row['session_id'],)).fetchone()
        if identity and tuple(identity)!=(row['character'],row['realm']):
            _ledger_finding(conn,dataset,row,batch_id,index,'invalid_farm_identity','Session belongs to another identity')
            return 0
    fields = farm.BASE_FIELDS if dataset == 'farm_runs' else farm.EVENT_FIELDS
    values = {k: row.get(k) for k in fields}
    values.update(character_id=_identity_id(conn,row),source_file_sha256=manifest['source_file_sha256'],
                  source_schema_version=str(manifest.get('source_schema_version','unknown')),
                  source_record_index=index,source_dataset=dataset,import_batch_id=batch_id,
                  logical_payload=logical,raw_record=source.get('raw_record') or json.dumps(source,sort_keys=True))
    conn.execute(f'INSERT INTO {dataset} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})',list(values.values()))
    return 1


def import_directory(csv_dir: Path, db_path: Path, *, make_backup: bool = True) -> dict[str, Any]:
    csv_dir, db_path = csv_dir.resolve(), db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_database(db_path) if make_backup else None
    manifest = _manifest(csv_dir)
    source_hash = str(manifest["source_file_sha256"])
    schema_version = str(manifest.get("source_schema_version") or "unknown")
    batch_id = _batch_id(source_hash, schema_version)
    counts = {dataset: 0 for dataset in DATASETS}

    conn = sqlite3.connect(db_path, timeout=1.0)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        apply_migrations(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""INSERT OR IGNORE INTO import_batches
            (id,source_file_sha256,source_schema_version,source_path,imported_at,status,manifest_json)
            VALUES(?,?,?,?,?,'running',?)""",
            (batch_id, source_hash, schema_version, str(csv_dir), utc_now(), json.dumps(manifest, sort_keys=True)))

        for dataset in DATASETS:
            source_rows = list(enumerate(read_csv(csv_dir / f"{dataset}.csv"), start=1))
            if dataset == 'farm_run_events':
                source_rows.sort(key=lambda item: (str(item[1].get('farm_run_id')), _int_or_none(item[1].get('revision')) or -1))
            for index, source_row in source_rows:
                if dataset in farm.FARM_DATASETS:
                    counts[dataset] += _import_farm(conn,dataset,source_row,manifest,index,batch_id)
                    continue
                if dataset in LEDGER_DATASETS:
                    counts[dataset] += _import_ledger(conn, dataset, source_row, manifest, index, batch_id)
                    continue
                row = _prepare_row(dataset, source_row, manifest, index)
                row["character_id"] = _identity_id(conn, row)
                row["import_batch_id"] = batch_id
                columns = TABLE_COLUMNS[dataset]
                placeholders = ",".join("?" for _ in columns)
                before = conn.total_changes
                conn.execute(
                    f'INSERT OR IGNORE INTO "{dataset}" ({",".join(columns)}) VALUES ({placeholders})',
                    [row.get(column) for column in columns],
                )
                counts[dataset] += conn.total_changes - before

        for warning in read_csv(csv_dir / "validation_errors.csv"):
            error_values = (
                batch_id, warning.get("dataset"), _int_or_none(warning.get("source_record_index")),
                warning.get("code") or "unspecified", warning.get("field"), warning.get("message") or "No message",
            )
            error_key = hashlib.sha256("\n".join(str(value or "") for value in error_values).encode("utf-8")).hexdigest()
            conn.execute("""INSERT OR IGNORE INTO validation_errors
                (error_key,import_batch_id,dataset,source_record_index,record_id,severity,code,field,message,raw_record,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
                error_key, batch_id, warning.get("dataset"), _int_or_none(warning.get("source_record_index")),
                warning.get("record_id"), warning.get("severity") or "warning",
                warning.get("code") or "unspecified", warning.get("field"),
                warning.get("message") or "No message", warning.get("raw_record"), utc_now(),
            ))
        conn.execute("UPDATE import_batches SET status='complete' WHERE id=?", (batch_id,))
        conn.commit()
        return {"batch_id": batch_id, "inserted": counts, "backup": str(backup) if backup else None}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Idempotently import normalized RingoWoWOps CSV files.")
    parser.add_argument("csv_dir", help="Directory containing normalized CSV exports")
    parser.add_argument("--db", default="data/ringo_ops.sqlite", help="SQLite database path")
    args = parser.parse_args()
    result = import_directory(Path(args.csv_dir), Path(args.db))
    if result["backup"]:
        print(f"Pre-migration backup: {result['backup']}")
    for table, count in result["inserted"].items():
        print(f"Inserted {count} new rows into {table}")
    print(f"Import batch: {result['batch_id']}")
    print(f"SQLite database ready: {Path(args.db).resolve()}")


if __name__ == "__main__":
    main()
