# Data schema

## Source SavedVariables

Schema v5 root:

```text
version = "0.5.0"
schema_version = 5
sessions
snapshots
notes
activities
events
ledger_entries
ledger_voids
farm_runs
farm_run_events
farm_settings
active_farm_run
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

## SQLite schema v8

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
- `wcl_import_batches`
- `wcl_reports`
- `wcl_fights`
- `wcl_characters`
- `wcl_report_participants`
- `wcl_fight_attendance`
- `guilds`
- `guild_members`
- `guild_characters`
- `roster_import_rejections`
- `raid_events`
- `raid_event_reports`
- `raid_helper_import_batches`
- `raid_helper_signups`

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

## Phase 3A append-only farm data

Two additional domain tables: `farm_runs` and `farm_run_events`. Generated exports
have the same names with `.csv`. Registry definitions live only in the shared
FarmPresets.lua source, not database enums or guessed map IDs.

The immutable `farm_runs` row is a prepared revision-zero header. Every event
contains a complete typed post-transition snapshot; `farm_run_id` references the
header and `(farm_run_id, revision)` is unique. Latest validated event supplies the
current summary. Started/finished/completed timestamps and observed money remain
nullable until actually observed. Interrupted runs never acquire fabricated end
fields. The schema is [farm_schema.sql](../tools/farm_schema.sql); detailed fields
and evidence semantics are in [farm-dashboard.md](farm-dashboard.md).

Farm record schema is 1, source addon schema is 5. Existing ledger records retain
their v4 ledger producer contract and schema 1 without rewriting/rebuilding the
ledger tables; file provenance records the actual addon file version. Migration
v5 uses a pre-migration SQLite backup and one transaction. Imports skip identical
IDs, quarantine conflicting/malformed records and validate revision chains. Batch
failure rolls back all inserted farm evidence. Phase 1/2 data remains intact.

## Warcraft Logs V1 attendance foundation

Schema v6 adds report, fight, external character, report-participation, and
per-fight attendance tables. Report codes, `(report_code, fight_id)`, external
character keys, report/character pairs, and report/fight/character triples are
unique. Foreign keys require attendance to refer to an imported fight and report
participant. Import batches are unique by report code and public-response SHA-256.

External keys are `<game-version>/<region>/<normalized-realm>/<normalized-name>`.
Display names and realms remain separately available. Guild membership is true
only for keys explicitly listed in local configuration; unknown/PUG characters
remain first-class participants. Attendance comes from WCL fight actor lists, not
Raid-Helper signups.

## Guild roster and event attendance

Schema v7 separates a real guild member from their characters. Guild identity
includes game version, region, and normalized realm, so a future Classic Forever
Butter & Jam context cannot collide with TBC Anniversary. `guild_characters`
uses the same external key as `wcl_characters`; the shared key permits a clean
join while allowing manually entered characters that have not appeared in a log.

Raid events are manual metadata keyed by `<source>/<external-event-id>`.
`raid_event_reports` is a many-to-many link with a composite primary key and
foreign keys to both the event and WCL report. Roster rejections retain review
evidence locally. Member Discord IDs and notes stay in SQLite/private CSV and are
excluded from attendance output and upload ZIP candidates.

## Raid-Helper public signup evidence

Schema v8 adds content-addressed public-event import batches and one current
source row per event/signup identity. Schema v10 tightens the private identity
boundary: signup rows retain exact source status, class, role, spec, name,
timestamps, optional notes, and a sanitized raw record, but never a raw Discord
ID. If a private runtime HMAC key is configured, `discord_user_hash` contains
only the keyed SHA-256 digest. The raw ID is used transiently during import.
Migration v10 clears historical signup Discord IDs and removes private identity
fields from historical signup raw records.

Resolution references existing member/character rows and uses exact transient
Discord ID, then an explicit external character key, then exact normalized
character name in the event namespace, then an explicit private alias. Fuzzy
and partial matching are not allowed. Conflicting ownership and unresolved
source rows remain unresolved. Reconciliation is calculated from signup,
roster, event-report, and WCL attendance evidence; it is not stored as mutable
truth.
