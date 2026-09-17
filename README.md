# RingoWoWOps

RingoWoWOps is an offline-first data logger and analytics foundation for World of Warcraft Classic/TBC. The addon passively records permitted game state; Python normalizes and validates SavedVariables; SQLite retains append-only history; and a scoped Markdown report summarizes one calendar day.

The project does not automate movement, combat, protected actions, auctions, invitations, whispers, or gameplay decisions.

## Product vision and history

The project began as a leveling and gathering tracker for a new Blood Elf Paladin. Its long-term purpose is broader: a private operations system for character progression, farming efficiency, professions, dungeon and raid activity, preparation, and eventually guild operations. The addon remains a lightweight sensor while analysis stays in Python, SQLite, reports, and a future local dashboard.

The system is intended to answer practical questions such as:

- What did I do during a selected day or session?
- How did my character and resources change?
- Which time and money changes are explained, estimated, or still unknown?
- Which farms, dungeons, professions, or preparation tasks are worth doing?
- What should I prepare before a raid or content phase?

Historical leveling use cases remain supported, but recommendations must eventually use actual character, expansion, phase, goals, and observed data rather than fixed leveling-zone advice.

## Design principles

1. **Tracking and decision support only.** No gameplay automation or attempts to bypass Blizzard rules.
2. **Data first, AI second.** Recommendations are useful only when inputs, scope, provenance, and uncertainty are explicit.
3. **Offline and personal first.** Raw history stays locally controlled; external integrations are optional future work.
4. **Preserve history.** Raw inputs remain evidence, imports are idempotent, and schema changes use explicit migrations.
5. **Keep the addon lightweight.** Normalization, valuation, analytics, and reporting belong outside WoW.
6. **Explain estimates.** Raw balance movement is not profit; external or estimated valuations must be labeled.

## Current status

Phases 1 and 2A are runtime-verified. Phase 3A Farm Run Core and native dashboard are implemented in source, awaiting WoW validation:

- addon schema v5 / addon v0.5.0; SQLite schema v5 / ledger and farm record schemas v1
- preset-ready Stratholme farm lifecycle, immutable transition evidence, Live Run / History / Settings dashboard
- manual cash entries, append-only voids, strict copper syntax and conservative reconciliation
- sessions, snapshots, notes, activities, and structured events
- deterministic compatibility IDs for legacy records
- validation output and source provenance
- versioned SQLite migrations and import batches
- idempotent append-only imports
- calendar-day reports with timezone, character, and realm scope
- standard-library `unittest` coverage plus an end-to-end fixture

See [the Farm Dashboard guide](docs/farm-dashboard.md) for Phase 3A deployment and runtime checks. The original panel remains at `/rwo mini`. See [the Gold Ledger guide](docs/gold-ledger.md) for commands, deployment and the manual runtime checklist. Advanced profitability, dashboard, raid operations, guild systems, and AI recommendations remain deferred.

## Data flow

```text
WoW addon
  -> trusted local SavedVariables
  -> tools/parse_savedvariables.py
  -> normalized CSV + validation manifest
  -> tools/import_to_sqlite.py
  -> versioned SQLite database
  -> tools/generate_daily_report.py
  -> scoped Markdown report
```

## Setup

1. Copy `addon/RingoWoWOps` into the correct WoW Classic `Interface/AddOns` directory.
2. Copy `config.example.json` to `config.json` and set your local paths/account folder.
3. Keep `config.json` private. It can contain an account-folder identifier.
4. Run:

```powershell
python tools\rwo.py doctor
python tools\rwo.py update
```

The CLI resolves project files from its own repository location, so it can also be launched outside the repository:

```powershell
python C:\path\to\RingoWoWOps\tools\rwo.py doctor
```

Commands:

- `update`: copy the configured trusted SavedVariables file, normalize it, import it idempotently, and generate the configured calendar-day report.
- `doctor`: validate paths, configuration, and database migration status.
- `upload`: run an update and create a ZIP with a manifest. It prints a privacy warning because raw history and notes are included.

See [docs/cli.md](docs/cli.md) for configuration and report-scope details.

## Addon commands

```text
/rwo income <amount> <category> [note]
/rwo expense <amount> <category> [note]
/rwo transfer <in|out> <amount> <counterparty> [note]
/rwo giftin <amount> <counterparty> [note]
/rwo giftout <amount> <counterparty> [note]
/rwo ledger help
/rwo ledger recent
/rwo ledger undo <short-id>
/rwo farm
/rwo farm status
/rwo mini
/rwo status
/rwo start
/rwo snap
/rwo stop
/rwo activity <type>
/rwo note <text>
/rwo ui
/rwo gift <amount> <source>
/rwo train <text>
/rwo ahscan <items_count>
/rwo market <text>
/rwo default <activity>
/rwo realm [name]
```

Structured commands only record observations. Gift amounts and raw balance movement are not treated as profit.

## Trust and privacy

`parse_savedvariables.py` uses Lupa to execute Lua. Common file/process-loading globals are removed, but this is still a trust boundary: parse only the local file written by WoW or a source you trust.

Raw files, notes, upload packages, databases, and local configuration can contain private character history. They are ignored by the repository patterns, but `config.json` was historically tracked; ignoring a tracked file does not remove it from Git history.

## Testing

```powershell
python -m unittest discover -s tests -v
```

Tests use sanitized fictional identities and notes.

## Reports

The current report is a calendar-day report, not a server-reset or weekly-reset report. Its timezone is configured with `report_timezone` and defaults in `config.example.json` to `Asia/Tehran`. Optional `report_character` and `report_realm` filters prevent unrelated identities from being combined. If an unfiltered day contains multiple characters or realms, report generation stops with an actionable error.

Raw balance change is a derived reconciliation signal, not profit. Phase 2A shows classified cash totals and observation-based reconciliation; comprehensive profit and profit/hour remain unavailable.

## Planned domains

The approved roadmap extends the current foundation incrementally:

- advanced ledger review and transfer linking (Phase 2B)
- structured farms, dungeon runs, and activities
- profession services, crafts, fees, tips, and material ownership
- dungeon and raid operations, attendance, assignments, and preparation
- character progression, reputations, professions, gear, and lockouts
- a read-only local dashboard after the underlying metrics are trustworthy
- guild/roster operations as a logically separate domain
- explainable AI-assisted recommendations only after the data model is mature

These are planned capabilities, not current implementation. Detailed sequencing and status are maintained in [docs/roadmap.md](docs/roadmap.md).

## Historical context retained in documentation

The original MVP tracked session time, XP, money, zones, activities, snapshots, and free-text notes. Earlier planning also considered loot/material records, manual market observations, LFG demand signals, Auctionator/TSM or Blizzard data where permitted, Discord-based organization, and raid/team analysis. Those ideas remain product context, but they are deliberately not described as implemented features.

The original MVP success questions remain useful regression goals:

1. How long did I play in the selected scope?
2. How much XP and raw money movement was observed?
3. What was the main activity and zone?
4. What notes and structured events were recorded?
5. Which conclusions are exact, derived, estimated, manual, or currently missing?

## Documentation

- [Addon design](docs/addon-design.md)
- [Data schema](docs/data-schema.md)
- [CLI and reporting](docs/cli.md)
- [Roadmap](docs/roadmap.md)
