# Addon design

The addon is a lightweight passive sensor. Expensive normalization and analytics remain outside WoW.

## Version and initialization

- Addon version: `0.5.0`
- SavedVariables schema: `5`
- Initialization runs after `ADDON_LOADED` for `RingoWoWOps`.
- Ordered migrations create missing containers/settings without replacing existing tables or records.
- Migrations are safe to repeat.
- New snapshots, notes, activities, and events receive stable source IDs and the current session ID where available.
- Legacy records are not rewritten merely to add IDs. The external normalizer generates deterministic compatibility IDs.

## Commands

```text
/rwo status
/rwo start
/rwo activity <type>
/rwo snap
/rwo note <text>
/rwo ui
/rwo stop
/rwo gift <amount> <source>
/rwo train <text>
/rwo ahscan <items_count>
/rwo market <text>
/rwo default <activity>
/rwo realm [name]
```

Validation is intentionally lightweight in game. The external parser performs canonicalization and records warnings. Activities remain extensible; recognized aliases are normalized externally while original text is preserved.

## Session lifecycle

- Normal login: starts an automatic session.
- Normal logout: `PLAYER_LOGOUT` completes the active session and clears persisted active-session metadata.
- `/reload`: expected to follow the logout/login path, completing the old session and starting another.
- Character switch: expected to close the old character session and start a new identity-specific session.
- Disconnect/crash: if the prior active-session ID survives, the next login marks that session `incomplete` with a recovery timestamp. It does not invent an end time or duration.
- Addon upgrade: ordered migrations preserve existing tables and records, then update schema/version metadata.

Phase 1 addon loading, migration and record creation were runtime-verified by the user. Phase 2A v0.4.0 was also user-validated in WoW: no Lua errors, existing UI/auto-sessions operational, entries and voids persisted across reload, and short-ID undo worked. Automated lifecycle tests additionally use mocked Lua APIs. The repeatable manual checklist remains in [gold-ledger.md](gold-ledger.md).

## Mini UI

`/rwo mini` toggles the retained lightweight panel. `/rwo ui` now opens the Phase 3A farm dashboard. It exposes status, snapshots, common activities, quick notes, and market notes. The panel remains deliberately small; dashboard functionality belongs outside the game.

## Safety

The addon reads permitted state and records observations. It does not move, fight, cast, trade, automate auctions, invite, whisper, or call protected gameplay actions.

## Phase 2A ledger

`income`, `expense`, `transfer`, `giftin`, `giftout` and `ledger help/recent/undo`
share strict validation before saving. The existing mini UI is unchanged. New
`ledger_entries` and `ledger_voids` containers are initialized by migration 4.
Stable IDs reuse the persisted sequence; voids never delete or rewrite entries.
Every successful financial entry captures a following balance snapshot. No money
movement is inferred. Legacy `gift` continues to create only an event.

See [gold-ledger.md](gold-ledger.md) for grammar, examples, limits and deployment.

## Phase 3A farm dashboard

The TOC loads FarmPresets.lua, FarmCore.lua and FarmDashboard.lua before the existing
entry point. The main addon supplies its ID/session/identity helpers to the core.
Migration 5 adds farm containers without rewriting prior records. The native
movable dashboard has Live Run, History and Settings; no web technology or external
addon is required. One-second visual refresh creates no persistent evidence.

Immutable prepared headers and full append-only transition snapshots separate
history from mutable active pointers/settings. Only explicit user actions start,
finish, complete, or abandon runs. Reload preserves a clean active run; a running
run found on normal login or unclean recovery becomes incomplete without invented
end observations. Existing Phase 1 session lifecycle remains unchanged.

See [farm-dashboard.md](farm-dashboard.md) for state transitions, API limitations,
privacy, deployment and the pending v0.5.0 runtime checklist.
