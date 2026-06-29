# Data Schema

## SavedVariables Root

The addon stores all persistent data inside a single SavedVariables
table.

Example structure:

    RingoWoWOpsDB = {
      version = "0.1.0",
      sessions = {},
      snapshots = {},
      notes = {},
      activities = {},
      settings = {}
    }

------------------------------------------------------------------------

## Sessions

A session starts with `/rwo start` and ends with `/rwo stop`.

  Field              Type             Description
  ------------------ ---------------- ---------------------------
  id                 string           Unique session identifier
  started_at         unix timestamp   Session start
  ended_at           unix timestamp   Session end
  duration_seconds   integer          Total duration
  character          string           Character name
  realm              string           Realm
  faction            string           Horde / Alliance
  class              string           WoW class token
  level_start        integer          Starting level
  level_end          integer          Ending level
  zone_start         string           Starting zone
  zone_end           string           Ending zone
  xp_start           integer          XP at session start
  xp_end             integer          XP at session end
  gold_start         integer          Copper at start
  gold_end           integer          Copper at end
  activity_start     string           Initial activity
  activity_end       string           Final activity

------------------------------------------------------------------------

## Snapshots

Snapshots are lightweight point-in-time captures.

Fields:

  Field       Type
  ----------- ------------------
  time        unix timestamp
  reason      string
  character   string
  realm       string
  faction     string
  class       string
  level       integer
  zone        string
  subzone     string
  xp          integer
  gold        integer (copper)
  bags_free   integer
  activity    string

------------------------------------------------------------------------

## Notes

Created with:

    /rwo note <text>

Typical usage:

-   Auction House observations
-   LFG observations
-   Raid notes
-   Team notes
-   Farming ideas
-   Route problems

------------------------------------------------------------------------

## Activities

Created with:

    /rwo activity <type>

Supported activity types:

-   leveling
-   questing
-   grinding
-   mining
-   herbalism
-   dungeon
-   travel
-   training
-   auction
-   banking
-   team
-   raid
-   idle
-   other

------------------------------------------------------------------------

## Money

All money is stored as copper.

Examples:

-   10000 = 1 gold
-   100 = 1 silver
-   1 = 1 copper

------------------------------------------------------------------------

## MVP Analytics

The first analytics engine should calculate:

-   Session duration
-   XP gained
-   Gold gained
-   XP/hour
-   Gold/hour
-   Zone history
-   Activity timeline
-   Notes timeline

------------------------------------------------------------------------

## Future Tables

Planned future datasets:

-   Loot
-   Materials
-   Auction observations
-   Profession progress
-   Dungeon runs
-   Raid logs
-   Team roster
-   Market indicators
-   LFG demand signals

------------------------------------------------------------------------

## Design Goal

The schema is intentionally simple.

Raw gameplay data should remain unchanged.

All calculations (XP/hour, Gold/hour, recommendations, AI summaries)
should happen **outside the game** using Python and SQLite, keeping the
addon lightweight and safe.
