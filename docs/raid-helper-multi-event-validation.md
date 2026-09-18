# Raid-Helper multi-event validation

Validation date: 2026-09-18

This validation exercises a second real Butter & Jam raid through the existing
Raid-Helper, Warcraft Logs V1, roster-resolution, event-linking, and attendance
reconciliation boundaries. Results below are aggregate-only; no Discord IDs,
signup notes, credentials, authenticated URLs, or raw private fields are
included.

## Event and report

- Event key: `raid-helper/1545073223689969799`
- Public event title: `SSC TK Saturday 16:30`
- Scheduled time: `2026-09-05T15:30:00+00:00`
- Instance context: Serpentshrine Cavern / Tempest Keep
- Game context: TBC Anniversary, EU, Spineshatter
- Warcraft Logs report: `HdxqZAtvnzXhD1F3`

## Aggregate results

- Raid-Helper signups: 33
- Warcraft Logs participants: 32
- Warcraft Logs fights: 12
- Roster-resolved signups: 1
- Unresolved signups retained for exact mapping: 32
- Signed up and attended: 1
- Signed up without WCL attendance: 0
- Bench and attended: 0
- Tentative and attended: 0
- No signup but attended (rostered): 2
- Unmatched signups: 32
- Unmatched WCL participants/PUGs: 29

No guild membership was inferred from approximate name similarity. Resolution
used the existing exact Discord-ID or external-character-key boundaries only.

## Idempotency and integrity

The second Raid-Helper import inserted 0 rows, updated 0 rows, and reported all
33 signups unchanged. The second Warcraft Logs import inserted 0 rows and
reported all 374 report entities unchanged. The event/report link is unique and
present once. SQLite `PRAGMA foreign_key_check` returned zero violations.
