# Addon design

The addon is a lightweight passive sensor. Expensive normalization and analytics remain outside WoW.

## Version and initialization

- Addon version: `0.3.0`
- SavedVariables schema: `3`
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

Only the source behavior has been inspected here. These lifecycle paths have not yet been runtime-verified inside WoW.

## Mini UI

`/rwo ui` toggles the current lightweight panel. It exposes status, snapshots, common activities, quick notes, and market notes. The panel remains deliberately small; dashboard functionality belongs outside the game.

## Safety

The addon reads permitted state and records observations. It does not move, fight, cast, trade, automate auctions, invite, whisper, or call protected gameplay actions.
