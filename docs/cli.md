# CLI and report configuration

## Commands

```powershell
python tools\rwo.py doctor
python tools\rwo.py update
python tools\rwo.py upload
```

Relative project paths are resolved from the repository, not the caller's current directory. `--config` may select another JSON configuration.

## Configuration

Start with `config.example.json`. Required keys are `wow_path` and `account`. Report keys are:

```json
{
  "report_timezone": "Asia/Tehran",
  "report_character": null,
  "report_realm": null,
  "report_date": null
}
```

If `report_date` is absent, the current date in `report_timezone` is used. This is a calendar-day boundary. Server/raid-reset and weekly-reset windows are intentionally separate future report modes.

The standard-library timezone loader is used. On Windows installations without timezone data, `UTC` and post-2023 `Asia/Tehran` have built-in fallbacks; other unavailable zones produce an actionable error.

An unfiltered day containing multiple characters or realms is rejected rather than silently aggregated. Add the appropriate character/realm filter and rerun.

## Validation

`update` prints the parser validation summary. Detailed findings are written to `validation_errors.csv` and imported into SQLite. `doctor` reports path checks and database schema/migration state.

## Upload privacy

`upload` includes the raw SavedVariables file, normalized exports, validation output, report, source manifest, and an upload manifest. Raw history and notes may be private. Previous ZIP files are never deleted automatically.

## Trust boundary

The parser uses Lupa. Parse only trusted local SavedVariables. Common Lua file/process/loading globals are removed, but the input is still executed in a Lua runtime.

## Phase 2A

The CLI imports and reports addon data only. There is no ledger add, backdating,
transfer matching or candidate review. `doctor` reports schema version, migration
need and ledger/void counts without modifying the database. `update` prints all
source record counts. v3 databases migrate to v4 on import with a collision-safe
SQLite backup. Newer database schemas are rejected.

The financial CSVs are included in local ZIPs as `private_financial_history`.
No network operation occurs. See [gold-ledger.md](gold-ledger.md) for privacy and
in-game entry/undo instructions.

For an exclusive date-range endpoint, set optional `report_end_date` or use:

```powershell
python tools\generate_daily_report.py --date 2026-09-17 --end-date 2026-09-19 --timezone Asia/Tehran --character Testpal --realm Testrealm
```

Stored Unix timestamps remain unchanged. Requested-window totals and actual
observed-interval reconciliation are separate. Boundary ties require review;
insufficient or partial observations do not become fictional balances.

## Phase 3A farm imports and reports

`update` also exports/imports `farm_runs.csv` and `farm_run_events.csv`; no farm CLI
writer is added. `doctor` reports farm run/event counts and the v5 migration target.
First v4-to-v5 import creates a unique pre-migration backup. Current run summaries
are projections of immutable headers/events, not overwritten source records.

The Farm Runs report section uses configured timezone/date/character/realm scope.
Completed duration summaries and Raw gold change use only completed runs; missing
balances are reported as unobserved. Incomplete and abandoned counts are separate.
No rate or automatic ledger classification is generated. The in-game fixed-offset
day setting must be aligned manually with the report timezone; config.json is not
read by WoW or modified by the addon.

Local ZIP manifests label both farm CSVs `private_farm_history`. Upload remains
local-only. See [farm-dashboard.md](farm-dashboard.md) for deployment and recovery.
