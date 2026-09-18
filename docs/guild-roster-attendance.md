# Guild roster and WCL attendance

This local-only foundation distinguishes a guild **member** (a real person) from
their **characters**. Discord identity and notes belong to the member. A member
may own multiple characters, while each character uses the existing WCL key:

```text
<game-version>/<region>/<normalized-realm>/<normalized-character-name>
```

Game version is part of both guild and character identity. TBC Anniversary and
Classic Forever characters therefore remain separate even when their displayed
names and guild names match. Realm is also part of identity.

## Private roster CSV

Copy `examples/guild_roster.example.csv` to
`data/private/guild_roster.csv`. The `data/private/` directory is ignored by
Git and is never considered by the upload-package command. The schema-v7 format
has these columns:

```text
member_id,member_display_name,discord_user_id,game_version,region,realm,character_name,class,primary_role,main_alt,member_status,character_status,notes
```

Member ID, display name, game version, region, realm, and character name are
required. Discord ID, class, role, and notes may be blank. `main_alt` is `main`,
`alt`, or `unspecified`. Use stable, non-secret member IDs. The importer creates
the Butter & Jam guild context per namespace, updates safe mutable fields, and
never silently transfers a character to another member. Rejected rows remain in
`roster_import_rejections` for local review.

```powershell
python tools\rwo.py roster-import --input data\private\guild_roster.csv
```

Normal output contains counts only. It never prints Discord IDs or member notes.
SQLite databases, private roster files, and migration backups are private and
ignored. Attendance reports expose member display names but not IDs or notes.

## Manual raid events and WCL links

Raid-Helper is currently only an event-source label; no API request is made.
Store event metadata, then link one or more already imported WCL reports:

```powershell
python tools\rwo.py raid-event-upsert --source raid-helper --external-id 1546729699479257104 --title "Butter & Jam Hyjal" --instance Hyjal --game-version tbc-anniversary --region eu --realm spineshatter
python tools\rwo.py raid-event-link-report --event-key raid-helper/1546729699479257104 --report-code RxkpqFn98jt1BYMr
python tools\rwo.py attendance-report --event-key raid-helper/1546729699479257104
```

Event upsert and report linking are idempotent. Both referenced records must
exist. Linking never changes archived WCL JSON or WCL domain rows.

The report separates matched roster characters from unmatched WCL participants
or PUGs, with fight counts and percentages per report. An unmatched participant
is never classified as a guild member. A missing roster character is not called
absent. Event existence is neither signup evidence nor attendance; actual
attendance is only imported WCL fight evidence.

Deferred work includes Raid-Helper and Notion APIs, signup notes, gear/item level,
WCL rankings/parses, Classic Forever APIs, Discord bots, automated roster
selection, and Addon integration.
