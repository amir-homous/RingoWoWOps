# Data schema

## Source SavedVariables

Schema v3 root:

```text
version = "0.3.0"
schema_version = 3
sessions
snapshots
notes
activities
events
settings
```

Existing source fields remain compatible with v0.1/v0.2 data. New child records have `id` and optional `session_id`. Settings include default activity, ID sequence, primary realm when configured, and active-session recovery metadata.

Money values captured from WoW are copper.

## Normalized exports

The parser produces:

- `sessions.csv`
- `snapshots.csv`
- `notes.csv`
- `activities.csv`
- `events.csv`
- `validation_errors.csv`
- `source_manifest.json`

Every importable record has:

- `record_id`
- source schema version
- source file SHA-256
- source dataset/index
- validation status

Legacy records without IDs receive deterministic content-based compatibility IDs. Duplicate identical source rows remain separate through a deterministic duplicate ordinal. Original activity text is retained in `activity_original`; recognized aliases are stored canonically in `activity`.

Invalid record types are retained in validation output as raw representations. Missing/incomplete fields generate inspectable warnings rather than silent deletion.

## SQLite schema v3

Core tables:

- `schema_metadata`
- `migration_history`
- `import_batches`
- `source_identities`
- `sessions`
- `snapshots`
- `notes`
- `activities`
- `events`
- `validation_errors`

Core records use typed columns and `record_id` primary keys. Source identities preserve exact character and realm strings and are never automatically merged. Child tables may reference a source session. Scope/time indexes support report queries.

Imports are transactional and use stable keys with `INSERT OR IGNORE`, making a repeated source import idempotent. Import batches are keyed by source hash and schema version. Validation errors also have deterministic unique keys.

Before a database with an older `user_version` is migrated, the importer copies it to a timestamped `*.pre_migration_vN_*.sqlite` backup. Legacy pre-v2 tables are retained as `legacy_*_pre_v2` evidence. Failed transactions roll back; the backup remains available.

No gold-ledger table exists in Phase 1.

## Report semantics

- Exact: captured point-in-time values.
- Derived: calculations such as session duration and raw balance change.
- Manual: player-entered notes/events.
- Estimated: none in Phase 1.
- Missing: classified income/expenses/transfers, inventory valuation, and profit/hour.

Raw balance change must never be interpreted as profit.
