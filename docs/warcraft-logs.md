# Optional Warcraft Logs V1 importer

A Warcraft Logs report is the uploaded record of one logging session. Its report
code is the value after `/reports/` in a WCL URL. For example, the report code in
`https://fresh.warcraftlogs.com/reports/RxkpqFn98jt1BYMr` is
`RxkpqFn98jt1BYMr`.

This integration is Python/SQLite-only and independent of the WoW Addon. The
Classic Fresh V1 base defaults to `https://fresh.warcraftlogs.com/v1`. Put the V1
key in the environment named by `wcl.api_key_env` (normally `WCL_V1_KEY`); never
put the key in JSON, source, logs, or command arguments:

```powershell
$env:WCL_V1_KEY = "your-key-from-your-private-secret-store"
python tools\rwo.py wcl-import --report-code RxkpqFn98jt1BYMr
```

For deterministic reprocessing with no network request:

```powershell
python tools\rwo.py wcl-import --report-code RxkpqFn98jt1BYMr --offline-json tests\fixtures\wcl_report_fights.json
```

Validated public responses are atomically archived at
`data/raw/wcl/<report-code>/fights.json`. An invalid or incomplete download never
replaces a valid archive. Imports are transactional and repeat-safe.

Characters use deterministic external keys:

```text
<game-version>/<region>/<normalized-realm>/<normalized-character-name>
```

Name and realm matching is case-insensitive and removes punctuation/spacing; the
original display name and realm are retained. `guild_character_keys` is the only
source of guild classification. Characters absent from that explicit mapping are
preserved as external/PUG participants.

Raid-Helper signup and actual attendance are different facts. This phase stores
actual per-fight WCL participation only; it does not infer attendance from a
signup. Gear, item level, parses/rankings, Raid-Helper API integration, Notion
publishing, automated roster decisions, private reports, and V2 OAuth remain
deferred.
