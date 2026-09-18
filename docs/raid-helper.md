# Public Raid-Helper signup import

The optional importer reads one public endpoint only:

```text
https://raid-helper.xyz/api/v4/events/<event-id>
```

It does not need or accept a Discord bot token. Create the local raid event first
so its game version, region, and realm are explicit, then import and reconcile:

```powershell
python tools\rwo.py raid-helper-import --event-id 1546729699479257104
python tools\rwo.py raid-helper-import --event-id 1546729699479257104 --offline-json tests\fixtures\raid_helper_event.json
python tools\rwo.py raid-reconcile --event-key raid-helper/1546729699479257104
```

The response is archived atomically at
`data/raw/raid-helper/<event-id>/event.json`. This archive is sanitized: Discord
user IDs, notes/comments, server/channel/leader IDs, creator/co-leader data, and
announcements are removed. The raw directory is ignored by Git. Private signup
fields are retained only in the ignored local SQLite database and never printed
by normal CLI output or included in upload ZIP candidates.

Repeated identical imports are idempotent. Source status, class, role, spec,
display name, timestamp, position, optional Discord ID, and optional notes are
preserved. Resolution never uses fuzzy matching. It tries exact Discord ID,
exact character key, then exact normalized character name within the event's
game-version/region/realm namespace. A name such as `Eggslayer/Mosesa` remains
one unresolved signup unless the API supplies an explicit character field.

Reconciliation calculates, rather than stores, signed-up-and-attended,
signed-up-without-WCL-attendance, bench-attended, tentative-attended,
no-signup-but-attended, unmatched-signup, and unmatched-WCL/PUG counts. An
unresolved signup is not called a no-show. Raid-Helper signup and WCL attendance
remain separate evidence.

Private/authenticated events, signup editing, Discord bot integration, Notion
synchronization, fuzzy identity matching, and automated roster decisions remain
out of scope.
