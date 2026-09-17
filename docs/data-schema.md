# Data schema

## Source SavedVariables

Schema v4 root:

```text
version = "0.4.0"
schema_version = 4
sessions
snapshots
notes
activities
events
ledger_entries
ledger_voids
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
- `ledger_entries.csv`
- `ledger_voids.csv`
- `validation_errors.csv`
- `source_manifest.json`

Every importable record has:

- `record_id`
- source schema version
- source file SHA-256
- source dataset/index
- validation status

Phase 1 legacy records without IDs receive deterministic content-based compatibility IDs. Duplicate identical source rows remain separate through a deterministic duplicate ordinal. Original activity text is retained in `activity_original`; recognized aliases are stored canonically in `activity`.

Invalid record types are retained in validation output as raw representations. Missing/incomplete fields generate inspectable warnings rather than silent deletion.

## SQLite schema v4

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
- `ledger_entries`
- `ledger_voids`

Core records use typed columns and `record_id` primary keys. Source identities preserve exact character and realm strings and are never automatically merged. Child tables may reference a source session. Scope/time indexes support report queries.

Imports are transactional and use stable keys with `INSERT OR IGNORE`, making a repeated source import idempotent. Import batches are keyed by source hash and schema version. Validation errors also have deterministic unique keys.

Before a database with an older `user_version` is migrated, the importer uses SQLite backup (including committed WAL state) to copy it to a timestamped `*.pre_migration_vN_*.sqlite` backup. Legacy pre-v2 tables are retained as `legacy_*_pre_v2` evidence. Failed transactions roll back; the backup remains available.

Phase 2A adds only ledger_entries and ledger_voids. The authoritative DDL is
[ledger_schema.sql](../tools/ledger_schema.sql). Entry required fields are record_id,
time, created_at, character/realm, direction, category, amount_copper, amount_quality,
input_source, schema_version=1 and addon_schema_version=4. Optional fields are
session_id, counterparty, note, activity, player_material_cost_copper,
material_cost_quality and material_provision. Gifts/transfers require counterparty.
Voids require entry_id, reason, ID, identity, timestamps and the same versions/source.

Both tables include character_id, source_file_sha256, source_schema_version,
source_record_index, source_dataset, import_batch_id, logical_payload and raw_record.
Character/batch references are foreign keys. Void targets are unique foreign keys.
Session IDs are soft references because their source session may be absent; a
resolved session belonging to another identity is rejected. Indexes cover identity,
time, session, batch and void scope. Original raw source values remain inspectable.

Ledger import validates strictly and quarantines malformed rows. Equal ID/payload
skips; conflicting ID/payload creates an error finding without overwrite. A later
source hash does not duplicate existing entries. Validation failures do not discard
other valid source records; database errors roll back the whole import transaction.
Migration is a separate transaction and may remain committed after an import fails.
Phase 1 tables and historical records are not rewritten by v4.

No candidates, pairing, CLI-authoritative records or adjustments are implemented.
Ledger IDs must be supplied, not generated from malformed or ambiguous records.

## Report semantics

- Exact: captured point-in-time values.
- Derived: calculations such as session duration and raw balance change.
- Manual: player-entered notes/events.
- Estimated: explicitly marked cash amounts and optional player material costs.
- Missing: inventory valuation and reliable activity profitability.
- Ledger semantics and conservative boundaries: [gold-ledger.md](gold-ledger.md).

Raw balance change must never be interpreted as profit.
