# Phase 3A: Farm Run Core and in-game dashboard

Implemented in source, awaiting WoW runtime validation. This extends the existing
project on `feature/farm-dashboard-phase3a`; it does not replace the ledger or
session system. Addon version is **0.5.0**, SavedVariables schema **5**, SQLite
schema **5**, and farm record schema **1**. These versions are separate.

## Use the dashboard

Open `/rwo ui` or `/rwo farm`. The native WoW window has three tabs:

- **Live Run:** identity, selected preset, state, timer, start timestamp, current
  zone/instance, start/current gold, Raw gold change, session status, warnings,
  and today's completed-run summaries.
- **History:** ten runs per page, newer/older controls, status, preset, local run
  number, start time, duration, Raw gold change, observed instance and note marker.
  Click a row to inspect its identity and note. There is no deletion action.
- **Settings:** default preset, auto-open and instance suggestions, scale,
  lock/unlock position, reset position, and day-boundary UTC offset.

The window uses a dark background and restrained gold accents. Drag it while
unlocked. Scale is bounded and fitted to the screen; the window is clamped rather
than freely resizable. Escape closes it through `UISpecialFrames`. Note inputs
do not take focus automatically; Enter/Escape releases focus. Only visible timer
updates occur once a second; they create no persistent records. History/summary
data is cached between transitions. Settings and position are character-specific.

The original panel remains at `/rwo mini` and through the Settings button. All
existing session, note, activity, event and ledger commands continue to work.

## Presets

`addon/RingoWoWOps/FarmPresets.lua` is the single registry. Lua loads it through the
TOC, and Python reads the same local data through the existing Lupa dependency.
Definitions carry ID, display name, mode, class hint, instance name, enabled flag
and version. Presets are not database enums: adding a future supported preset does
not itself require a database migration. Changes to preset semantics must retain
support for historical preset versions in the validator.

| ID | Phase 3A status |
|---|---|
| STRATHOLME_PALADIN | Enabled |
| BOTANICA_TANK_HR | Disabled, Coming next |
| SHADOW_LAB_MAGE_BOOST | Disabled, Coming next |

Class hints are advisory. Manual selection is authoritative. No unverified map
or instance IDs are included; `instance_id` stays missing. An observed instance
name and difficulty may be recorded when the APIs provide them.

## Lifecycle and evidence

```text
idle -> Prepare -> prepared -> Start Run -> running
running -> Finish Run -> review -> Confirm Reset & Complete -> completed
prepared/running/review -> confirmed Abandon -> abandoned
uncertain recovery -> incomplete
```

Only one prepared/running/review run may be active per character/realm. Prepare
allocates a stable run ID and immutable prepared header. Start captures time,
identity, current session, zone/instance, available gold and local-day run number.
Finish captures the end observations and duration and freezes the timer in review.
Complete records the reset attestation and completion time. It never resets an
instance. After completion, the dashboard offers Prepare or Start Next Run; the
latter performs the same validated prepare/start operations.

Abandon requires an explicit second click, or `farm abandon confirm`. It records
an audit event rather than deleting a run. Notes can be appended in prepared,
running and review states. Terminal completed/abandoned/incomplete runs cannot be
edited or annotated. Corrections to terminal runs are deferred; do not alter
historical records. Invalid actions do not append partial records.

`farm_runs` contains immutable prepared headers. `farm_run_events` contains full
immutable snapshots after each transition, ordered by per-run `revision`.
**The latest validated event is the current summary, not an update to the header.**
This allows importing a running run and later completion without overwriting an ID
or treating a legitimate transition as an ID conflict. Python's
`farm.current_runs(connection)` derives the summaries used by reports. The SQLite
connection needs `sqlite3.Row`. No mutable materialized summary is stored.

Events implemented in 3A: prepared, started, finish_requested, completed,
abandoned, interrupted, note_added. Completion includes `reset_confirmed=true` in
the same atomic event. Instance events update UI context only; they neither mutate
run evidence nor start/complete a run. Historical event records never change.

## Recovery and durability

`active_farm_run` is a character/realm-keyed control map, separate from immutable
evidence. It holds the active run ID and a clean-logout marker. Startup rebuilds
current summaries from saved run/event records. The global Phase 1 ID sequence is
reused for both run and event IDs; existing ledger/session IDs are unchanged.

- `/reload`: `PLAYER_LOGOUT` saves the clean marker; the first
  `PLAYER_ENTERING_WORLD` with `isReloadingUi=true` preserves the run. The elapsed
  running timer includes reload time. Reloading appends no farm evidence.
- Normal logout/character switch while running: the next login marks the old run
  incomplete with reason `logout_or_character_switch`. It cannot include offline
  time in a completed duration. Finish before logging out if the run is done.
- Prepared or review state after clean logout: restored. Review already has a
  real observed finish, so its known duration remains intact.
- Unclean restart or missing reload evidence: append interrupted/incomplete.
  Never invent a finish time, completion time, end balance or duration. An already
  observed review finish may remain; it was not inferred from the interruption.
- Character switching uses separate active pointers and never attaches another
  character's run. A bad/unresolved pointer blocks starting a replacement until
  the source data is reviewed; history is retained.

WoW writes SavedVariables on reload/logout. A process or machine crash can lose
unsaved changes; this addon cannot make WoW's disk writes crash-proof. Recovery is
deterministic for whatever data WoW actually persisted. Finish/complete normally
and flush with a normal reload/logout before importing important work.

## Raw gold change and time scope

```text
Raw gold change = observed end character gold - observed start character gold
```

Missing observations remain missing, never zero. Negative raw change is valid.
This is not loot gold, vendor revenue, DE value, classified farming income, profit
or a performance rate. Farm actions never create Gold Ledger entries. Existing
voids still exclude ledger records from active economy totals. Material costs,
gifts and transfers keep their Phase 2A behavior.

Today's in-game summaries include completed count, average/fastest observed
duration, total Raw gold change with observation count, and incomplete/abandoned
counts. A run belongs to its start day; a never-started preparation uses its
creation day. The original captured local-day number stays on each run.

WoW cannot read `config.json` or Python's IANA timezone rules. Dashboard Settings
uses an explicit fixed UTC offset in minutes, default **210** (+03:30). Set it to
match your reporting timezone. Changes are blocked while a run is active; a new
start counts previous starts on the selected offset's calendar day. Fixed offsets
do not follow DST. Python's scoped report always uses the configured timezone and
`[start, end)` boundaries and may group runs differently if settings differ.
All stored timestamps remain raw Unix seconds. No Gold/hour or Profit/hour is
calculated. Report summaries clearly separate completed and interrupted runs.

## Instance awareness and API verification

The implementation reads guarded `GetInstanceInfo`, `IsInInstance`, `GetZoneText`
and `InCombatLockdown` calls. The Blizzard-generated
[Classic instance API definitions](https://github.com/Gethe/wow-ui-source/blob/classic/Interface/AddOns/Blizzard_APIDocumentationGenerated/InstanceDocumentation.lua)
were inspected for the name/type/difficulty return order and instance predicate.
That branch is API evidence, not proof of this installation's exact TBC behavior.

On `PLAYER_ENTERING_WORLD` and `ZONE_CHANGED_NEW_AREA`, a change to inside-instance
context can suggest an enabled preset by exact instance name. Non-English names
may not match. Auto-open is opt-in and never occurs while in combat. There is no
deferred combat-time opening. Leaving the instance never completes the run.
If these context APIs are missing, or the name does not match, manually select the
preset and use the same workflow. Validate reload event flags and localized
Stratholme naming on the actual client before relying on automatic suggestions.

## Data and privacy

SavedVariables adds `farm_runs`, `farm_run_events`, `farm_settings`, and
`active_farm_run`; existing valid containers and records remain untouched.

Run/event fields include record ID/schema, preset ID/version, character/realm,
optional session, status, start/finish/completion timestamps, observed duration,
start/end zones and instance names, optional instance/difficulty IDs, start-day
number/date/offset, start/end gold and raw delta, manual/confirmation flags,
interruption reason, note, created/updated timestamps and source addon schema.
Events also carry farm_run_id, revision, event type, prior state and event time.
Unused observations are nullable. Headers are prepared revision zero; the first
event is prepared revision one.

SQLite migration v5 adds only `farm_runs` and `farm_run_events`, with typed fields,
constraints, event-to-run/identity/batch foreign keys, unique run/revision pairs,
and indexes for identity/time, preset, status, session and captured local day.
Session IDs remain soft references because a source session can be missing; a
resolved session of a different identity is rejected. `character_id` references
the existing source identity table. Original raw payload, file hash, dataset/index,
logical payload and import batch accompany each record.

Migration uses the existing SQLite backup API and collision-safe filename scheme,
then transactional DDL/version history. Existing Phase 1/2 rows and ledger tables
are not rebuilt. Newer database versions are rejected. Migration and import are
separate transactions: failed imports roll back the batch, not an already committed
migration. Repeated imports skip identical IDs; differing payloads produce validation
findings and never overwrite the original. Invalid lifecycle/timestamp/duration/
balance data is quarantined with its original values, never silently repaired.
CSV order does not define transition order; per-run revision does.

Generated `farm_runs.csv` and `farm_run_events.csv` are explicitly marked
`private_farm_history` in local ZIP manifests. Notes, identity, context and financial
observations are private. `upload` only creates a local archive; no networking is
introduced. Keep config, raw data, databases, exports, reports and backups ignored.

## Fallback commands

```text
/rwo farm
/rwo farm status
/rwo farm prepare [STRATHOLME_PALADIN]
/rwo farm start
/rwo farm finish
/rwo farm complete
/rwo farm abandon confirm
/rwo farm note <text>
/rwo mini
```

The dashboard is primary. Fallback commands call the same state machine and do not
bypass validation. `/rwo farm complete` is an explicit reset attestation, not a
reset action. `/rwo` provides grouped help and `/rwo ledger help` remains available.

## Manual deployment

Deployment has not been performed by the implementation. Exit WoW fully. From
`C:\RingoWoWOps`, run the following PowerShell. It backs up the installed addon
and SavedVariables under an ignored directory and copies only source addon files.
Do not replace SavedVariables with addon code; they share a basename.

```powershell
$ErrorActionPreference = 'Stop'
$rwoRoot = (Get-Location).Path
$rwoConfig = Get-Content -Raw -LiteralPath "$rwoRoot\config.json" | ConvertFrom-Json
$rwoFlavor = $rwoConfig.wow_flavor
if (!$rwoFlavor) { $rwoFlavor = '_anniversary_' }
$rwoClient = Join-Path $rwoConfig.wow_path $rwoFlavor
if (!(Test-Path -LiteralPath $rwoClient)) { throw 'Configured WoW client missing' }
$rwoTarget = Join-Path $rwoClient 'Interface\AddOns\RingoWoWOps'
$rwoSavedName = $rwoConfig.savedvariables_file
if (!$rwoSavedName) { $rwoSavedName = 'RingoWoWOps.lua' }
$rwoSaved = Join-Path $rwoClient "WTF\Account\$($rwoConfig.account)\SavedVariables\$rwoSavedName"
$rwoBackup = Join-Path $rwoRoot ('data\addon_backup_phase3a_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $rwoBackup | Out-Null
if (Test-Path -LiteralPath $rwoTarget) {
    Copy-Item -LiteralPath $rwoTarget -Destination (Join-Path $rwoBackup 'installed-addon') -Recurse
}
if (Test-Path -LiteralPath $rwoSaved) {
    Copy-Item -LiteralPath $rwoSaved -Destination (Join-Path $rwoBackup 'SavedVariables.lua')
}
New-Item -ItemType Directory -Path $rwoTarget -Force | Out-Null
foreach ($rwoFile in @('FarmPresets.lua','FarmCore.lua','FarmDashboard.lua','RingoWoWOps.lua','RingoWoWOps.toc')) {
    Copy-Item -LiteralPath (Join-Path "$rwoRoot\addon\RingoWoWOps" $rwoFile) -Destination $rwoTarget
}
```

After testing and normal logout/reload:

```powershell
python tools\rwo.py doctor
python tools\rwo.py update
python tools\rwo.py update
python tools\rwo.py doctor
```

Doctor is read-only. First import backs up and migrates the live v4 database to v5.
Second import should insert zero rows in all unchanged datasets. Keep the backup.

## Focused WoW runtime checklist

Automated tests use mocked APIs; no real 0.5.0 runtime success is claimed.

1. Verify Loaded v0.5.0, no Lua errors, source schema 5, and old sessions/ledger
   records/voids unchanged. Confirm the mini panel at `/rwo mini` still works.
2. Open `/rwo ui`. Test Live Run/History/Settings, dragging, lock, reset position,
   scale 0.7-1.3 and screen clamping at your common UI scales. Escape closes it;
   typing a note and clearing focus must not trap gameplay keys. Validate long
   row readability on your screen. Only Stratholme is selectable; the other two
   presets are disabled and labeled Coming next.
3. Set day offset to match the Python report timezone. Prepare, Start Run and
   watch the timer. Verify identity, instance context, start/current gold, raw
   delta and session state. Start/Prepare again must not create another run.
4. Add a Unicode note. Finish, verify review freezes duration/end gold, then
   manually perform the appropriate in-game reset yourself. Click Confirm Reset
   & Complete. The addon must not perform a reset or any group/chat action.
5. Check History details and Start Next Run. Number increments on the start day;
   completed run evidence does not change. Review today's count/durations and
   Raw gold change labels; no economic rate or classified revenue is implied.
6. Start another run, record run/event counts and IDs, then `/reload`. Confirm the
   run remains running with the same start time/ID and no extra farm records.
   If this client does not supply the reload flag, stop and report that limitation.
7. Test normal logout while running: on login it becomes incomplete with no
   invented finish/duration. Separately test logout in prepared and review states:
   clean login should restore them. Switch characters and verify separate control
   and history. Unclean recovery is covered by mocks; test actual crashes only on
   disposable copied data, not by risking valuable unsaved history.
8. Try Abandon, cancel, then confirm. Only confirmation adds an abandoned event.
   Terminal records remain visible and cannot be edited/deleted. Invalid fallback
   actions must not change run/event counts.
9. Enter/leave Stratholme: verify the observed localized name and difficulty.
   Suggestions may appear but must not start/finish a run. Enable auto-open, then
   verify it stays closed during combat. Manual selection must work regardless
   of detection. Leaving an instance must not complete a run.
10. Flush SavedVariables, run update twice, inspect v5 backup and inserted counts.
    Check foreign keys, selected character/realm/date scope, completed/incomplete
    counts, duration and Raw gold change. Confirm Phase 2A voided entries remain
    excluded from economy totals. Synthetic testing can move no gold at all;
    recording farm actions does not cause financial transactions.

## Explicitly deferred

No automatic reset, chat/Yell/LFG, invites, recruitment, buyers, boost payments,
runs purchased/remaining, waiting list, replacement alerts, loot classification,
vendor attribution, blue-item tracking, disenchant detection or valuation, AH/TSM,
run-linked ledger classification, Gold/hour, profit, web dashboard, Discord, AI,
specialized Botanica/Shadow Lab workflows, or gameplay automation. These require
separate Phase 3B-or-later approval. Phase 2B ledger maintenance remains deferred.
