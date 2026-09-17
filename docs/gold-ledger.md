# Phase 2A manual gold ledger

Implemented and user-validated in WoW at v0.4.0. SavedVariables
is authoritative. SQLite is its local imported projection. There is no manual CLI
entry writer, network transmission, transaction inference, or gameplay automation.

## Quick workflow

After gold actually changes, record the payment once. A confirmation prints the
direction, normalized money, category, character@realm, short ID and quality.
A balance snapshot follows the entry. Recording an entry never changes game gold.

```text
/rwo income 25g service enchanting tip
/rwo income 250g craft crafted legs
/rwo expense 80g materials cloth for crafted legs
/rwo expense 12g50s repair
/rwo transfer out 100g Bankalt
/rwo transfer in 100g Mainchar
/rwo giftin 50g Friend
/rwo giftout 5g Friend birthday
/rwo transfer out 100g "Guild bank" retained personal ownership
/rwo ledger help
/rwo ledger recent
/rwo ledger undo <short-id>
```

Counterparties containing spaces must be quoted. Recent displays the last ten
entries for the current character/realm, including void markers. Undo accepts a
full ID or unique suffix; ambiguous, missing, foreign-character and already voided
targets are rejected. It appends a void record, preserving the original entry.
Re-enter the corrected transaction normally. Backdating is deferred: a replacement
has the current timestamp and can therefore require boundary review.

Voids apply retrospectively to active totals, including older report dates. The
source transaction remains visible in SQLite, CSV and the report's void list.

## Money and categories

Use `250g`, `12g50s`, `75s`, `10000c`, `1g2s3c`, or `~12g` for an estimate.
Units are case-insensitive, occur at most once, and follow g/s/c order. Components
may exceed 99 (`150s` is valid). No bare values, signs, decimals, commas, exponents,
embedded spaces, repeated units or reversed units. Leading zeros are permitted.
Amounts are integer copper: 1g = 10000c, 1s = 100c.

The shared Lua/Python upper bound is **2,147,483,647 copper per amount**. This
deliberately conservative limit is safely below Lua's exact-integer ceiling.
Cash must be positive. Material cost alone may be zero. `~` marks estimated input;
exact means user-declared exact, not independently verified.

| Direction | Categories | Treatment |
|---|---|---|
| Income | service, craft, sale, activity, refund, other | Add to cash result |
| Expense | repair, training, supplies, materials, purchase, fees, other | Subtract from cash result |
| Either | transfer, gift | Balance movement only; excluded from cash result |
| Reserved | adjustment | No Phase 2A command or accepted import |

`service` covers tips and fees. `craft` covers craft receipts. `sale` covers vendor,
AH and permitted item sales. `activity` covers dungeon, raid, fishing, farm,
disenchant proceeds and gold splits; use activity detail or a note. Unsold items
and material splits are not cash. Use `refund` for returned deposits/cost recovery.
Record net AH money actually collected; do not deduct withheld fees again.
Repairs, training, supplies, materials, purchases and fees stay economically
separate without adding dozens of categories. `other` is not repeatable income
by default. Phase 2A produces no repeatable-performance or profit/hour metric.

Transfers are valid on one side and always reported as one-sided/unmatched.
Nothing pairs them or invents a counterpart. A guild-bank movement belongs here
only when personal economic ownership remains unchanged; this is not guild
accounting. Gifts change ownership without consideration and remain separate.

## Optional receipt annotations

```text
/rwo income 250g craft --cost ~80g --materials mixed -- crafted legs
/rwo income 25g service --cost 0c --materials customer -- enchanting tip
/rwo income 50g activity --activity fishing -- catch sales
```

Options precede `--`, which starts free text. Duplicate/unknown options fail
validation. Without options, all text after required arguments is the note.
Provision is customer/player/mixed/unknown. Annotations apply only to income
receipts, excluding refunds. Do not assign a monetary value to customer materials.
`customer` rejects nonzero player material costs. Missing cost is NULL, not zero;
explicit zero confirms no player-owned material cost. Mixed provision values only
the player's contribution. Exact/estimated cost quality is independent of receipt
quality. Crafting for personal use creates no income: record only actual cash
payments, such as a materials purchase. Existing-stock consumption is not a second
cash payment.

When a receipt and cost exist, the report may show **Declared material margin** =
receipt - annotated player material cost, estimated if either component is
estimated. It is not comprehensive profit. Costs are never subtracted again from
cash result or reconciliation. No inventory or customer-material value is stored.

## Reconciliation

Reports scope one character/realm and a timezone-defined `[start, end)` window.
Filters may resolve automatically only when exactly one identity is present;
multiple characters or realms require explicit filters. Unix timestamps are never
shifted in storage. `--end-date` selects an exclusive end date for a range.

Full requested-window totals and observed-interval totals are separate. Only
the observed-interval view is used for reconciliation. These overlapping views
must not be added together. Only
actual snapshots inside the requested window (including its closing boundary)
provide balance evidence; no carry-forward, interpolation, session-sum substitute
or invented midnight balance. Fewer than two distinct observation timestamps
means insufficient observations.

```text
raw change = closing observed balance - opening observed balance
classified movement = income - expenses + transfer in - transfer out + gift in - gift out
exact-only difference = raw change - exact classified movement
provisional difference = raw change - exact movement - estimated movement
```

Reconciliation includes entries in `[opening observation time, closing observation
time)`. An entry at either boundary or conflicting balances in the same boundary
second makes the result `review_required`: source timestamps cannot prove order.
This deliberately conservative rule also applies to post-entry snapshots. Take a
later `/rwo snap` to provide a closing observation after the transaction second.
No snapshot-schema sequencing redesign is included.

Coverage is `complete`, `partial_coverage`, or `insufficient_observations`. The
reconciliation status is review_required for boundary/import conflicts, otherwise
provisional_estimates when cash estimates participate, otherwise partial_coverage
for incomplete window evidence, otherwise unexplained or reconciled_exact.
Insufficient observations cannot reconcile. Nonzero residuals remain visible even
when another status has priority. Tolerance is **zero copper**. Exact arithmetic
agreement does not prove correct classification or completeness. Cash result is
income minus expenses, excluding transfers and gifts; raw growth is not profit.

## Legacy, persistence and privacy

`/rwo gift` still writes only the original legacy event and now explains that fact.
Its captured `gold` is a balance, never a transaction amount. Training text and
notes are not converted. There are no candidate or pairing tables.

IDs use the existing persisted sequence. Migration initializes new containers
without rewriting old rows. `/reload` preserves saved records and voids; normal
logout/session and interrupted-session recovery remain intact. A crash may lose
changes WoW has not saved; the addon cannot promise crash-proof disk persistence.

New CSVs are `ledger_entries.csv` and `ledger_voids.csv`. Originals and malformed
records remain in raw-record/provenance fields or validation findings. Reimports
skip equal logical payloads, retain original conflicting IDs, and report conflicts.
Invalid records are quarantined as findings; database failures roll back the batch.
Review unresolved conflicts in `validation_errors.csv`; no Phase 2B repair UI exists.

The local `upload` command includes both CSVs, labeled `private_financial_history`.
Raw SavedVariables, notes, counterparties, CSVs, reports and ZIPs may be private.
The command creates a local ZIP only; nothing uploads or sends data automatically.

## Deployment (manual, not performed by the implementation)

Exit WoW completely first. Run this from the repository in PowerShell. It uses
your private config locally without printing its account identifier, backs up
both the installed addon and SavedVariables, and copies only the two addon files.
It does not overwrite SavedVariables or config. Do not copy the source addon Lua
over the SavedVariables Lua: they have the same basename but different purposes.

```powershell
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
$rwoBackup = Join-Path $rwoRoot ("data\addon_backup_phase2a_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $rwoBackup | Out-Null
if (Test-Path -LiteralPath $rwoTarget) {
    Copy-Item -LiteralPath $rwoTarget -Destination (Join-Path $rwoBackup 'installed-addon') -Recurse
}
if (Test-Path -LiteralPath $rwoSaved) {
    Copy-Item -LiteralPath $rwoSaved -Destination (Join-Path $rwoBackup 'SavedVariables.lua')
}
New-Item -ItemType Directory -Path $rwoTarget -Force | Out-Null
Copy-Item -LiteralPath "$rwoRoot\addon\RingoWoWOps\RingoWoWOps.lua" -Destination $rwoTarget
Copy-Item -LiteralPath "$rwoRoot\addon\RingoWoWOps\RingoWoWOps.toc" -Destination $rwoTarget
```

## Manual WoW runtime checklist

Automated tests use mocked Lua APIs, not a running WoW client.
The user separately verified v0.4.0 loading without Lua errors, the existing mini
UI and auto-session behavior, ledger persistence across reload, append-only undo,
SQLite migration with backup, idempotent imports, and exclusion of voided entries
from active report totals. The checklist remains available for future regressions.

1. Log in and verify `Loaded v0.4.0`; verify old sessions/notes remain. Run
   `/run print(RingoWoWOpsDB.schema_version, #RingoWoWOpsDB.ledger_entries, #RingoWoWOpsDB.ledger_voids)`.
   Schema must be 4 and a fresh migrated ledger must be empty.
2. Run `/rwo ledger help` and `/rwo ui`; verify the old panel and notes work.
3. Run `/rwo snap`, wait at least one second, and record the six common examples
   above. If these are synthetic test entries, expect an unexplained difference:
   commands do not actually move gold. Verify one entry and one snapshot per save,
   positive amounts, correct direction/category/quality/identity and unique IDs.
4. Try `income 25 service`, `income -1g service`, `expense 1g craft`, and
   `income 1g craft --cost 1g --materials customer`. Each must show an explanation
   and example, without adding records/snapshots or clearing UI text.
5. Test both material examples, `~12g` cash, fishing activity detail, and a quoted
   counterparty. Verify exact/estimated confirmation and saved annotations.
6. Undo a unique displayed ID. Verify the entry remains, one void is added, and
   recent shows VOID. A second undo must fail. An ambiguous suffix must fail;
   use the full ID if needed. Re-entering creates a new record.
7. Run legacy `/rwo gift 250 Friend` and `/rwo train test`; event count increases,
   ledger count does not. Verify the legacy-gift explanation.
8. Record counts, `/reload`, and verify ledger IDs/counts/voids are unchanged.
   Normal session completion/new session creation remains expected. Log out/in
   and switch characters; verify isolation. Crash recovery is best checked on a
   disposable backup: do not deliberately terminate a live session with valuable
   unsaved history merely to test it.
9. Wait at least one second and `/rwo snap`; log out so SavedVariables flushes.
   Run `python tools\rwo.py doctor` then `python tools\rwo.py update`. First update
   migrates a v3 database with a backup. Doctor is read-only and does not migrate.
10. Run update again: inserted ledger/void counts must be zero. Inspect the
    character-scoped report: gifts/transfers excluded from cash result, one-sided
    transfers visible, voids excluded, material costs not subtracted twice, estimates
    separated, actual observation times/partial coverage shown, no profit/hour.
11. If testing with invented transactions, void every test entry afterward and
    repeat logout/import. Keep the audit trail. Do not delete existing history.

## Deferred to Phase 2B or later

Manual/backdated CLI entries, candidate review or legacy promotion, transfer
matching/linking, account-wide aggregation, inventory valuation, automatic AH/TSM,
transaction inference, farm-run/service-order/dungeon operational schemas, guild
accounting, ledger UI/dashboard, Discord, AI, profit/hour, and gameplay automation.
