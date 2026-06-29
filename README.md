# RingoWoWOps

**RingoWoWOps** is an AI-assisted analytics and operations toolkit for World of Warcraft Classic / TBC Anniversary gameplay.

The project starts as a lightweight personal addon and data logger for tracking leveling, gold flow, materials, activities, dungeon demand signals, and raid/community operations. Over time, it can grow into a full analytics dashboard for MMO economy planning, raid organization, and decision support.

This project is designed for **analysis, tracking, planning, and manual decision support only**.
It does **not** automate gameplay, combat, movement, trading, auction actions, invitations, whispers, or any other protected/player actions.

---

## Project Vision

The long-term goal is to build a practical decision engine for a serious WoW Classic player / raid organizer.

Instead of guessing what to do each day, the system should help answer questions like:

* Should I focus on leveling, gearing, farming, dungeons, or professions today?
* Which activity gave me the best gold per hour?
* Which zone gave me the best XP per hour?
* Which materials should I keep, sell, or watch?
* Is Mining / Herbalism slowing down leveling too much, or is it worth it?
* Which dungeon or role has the strongest demand signal?
* Which raids, teams, and schedules create the best long-term value?
* What should I prepare before the next phase or raid tier?

The project combines:

* WoW addon data logging
* SavedVariables export
* Python parsing
* CSV / SQLite storage
* manual market notes
* Auction House / TSM / Blizzard API data where available
* AI-assisted planning and summarization

---

## Current Target

The first target is a **Blood Elf Horde Paladin** leveling journey in **TBC Anniversary**, with the intention of becoming a **Protection Paladin / operations lead** for dungeon, heroic, raid, and economy management.

Early gameplay focus:

* Level efficiently from 1 to 70
* Track XP, gold, activities, and gathering value
* Use Mining + Herbalism early for startup capital
* Build reliable data before making economic decisions
* Prepare for future Prot Paladin tanking, heroic runs, raid organization, and profession planning

---

## Design Principles

### 1. Safe and ToS-conscious

The addon should only:

* read game state
* store data
* show UI
* create notes
* generate reports
* help the player make manual decisions

The addon must not:

* move the character
* cast spells
* automate combat
* automate auction buying/selling
* auto-invite players
* auto-whisper or spam
* make decisions on behalf of the player
* interact with protected functions in unsafe ways
* behave like a bot

### 2. Data first, AI second

AI is useful only when the data is clear.

The project should first collect reliable personal data:

* session time
* XP gained
* gold gained/spent
* activity type
* zone
* loot/materials
* dungeon runs
* notes
* market observations

Only after that should AI generate recommendations.

### 3. Small MVP before dashboard

The project should not start as a large web app.

The preferred path:

1. WoW addon with slash commands
2. SavedVariables export
3. Python parser
4. CSV / SQLite storage
5. Simple reports
6. Later: web dashboard, Discord bot, market intelligence

### 4. Personal utility first

The first version should solve one player’s real problem:

> “What did I do today, what did it produce, and what should I do next?”

If it becomes useful enough, it can later become a portfolio project or public tool.

---

## Planned Architecture

```text
WoW Addon
  ↓
SavedVariables.lua
  ↓
Python Parser
  ↓
CSV / SQLite
  ↓
Analysis Scripts
  ↓
Daily AI Summary / Manual Report
  ↓
Future Dashboard / Discord Bot
```

---

## Repository Structure

Planned structure:

```text
RingoWoWOps/
  README.md
  addon/
    RingoWoWOps/
      RingoWoWOps.toc
      Core.lua
      Commands.lua
      Events.lua
      Storage.lua
      UI.lua
  tools/
    parse_savedvariables.py
    export_csv.py
    analyze_sessions.py
  data/
    raw/
    processed/
    examples/
  docs/
    product-plan.md
    data-schema.md
    addon-design.md
    roadmap.md
  dashboard/
    README.md
```

For the first MVP, the addon may be simplified to:

```text
addon/
  RingoWoWOps/
    RingoWoWOps.toc
    RingoWoWOps.lua
```

---

## MVP v0.1 — Session & Snapshot Logger

The first version should support slash commands:

```text
/rwo start
/rwo snap
/rwo stop
/rwo status
/rwo note <text>
/rwo activity <type>
```

### `/rwo start`

Starts a gameplay session and stores:

* timestamp
* character name
* realm
* faction
* class
* level
* zone
* subzone
* current XP
* current gold
* current bags free slots
* current activity type

### `/rwo snap`

Creates a snapshot during the current session.

Useful when:

* entering a new zone
* finishing a quest chain
* before/after a dungeon
* before/after farming
* before/after selling items
* before logging out

### `/rwo stop`

Ends the current session and stores:

* end timestamp
* ending level
* ending XP
* ending gold
* ending zone
* session duration
* current activity type

### `/rwo activity <type>`

Marks what the player is currently doing.

Initial activity types:

```text
leveling
questing
grinding
mining
herbalism
dungeon
travel
training
auction
banking
team
raid
idle
other
```

### `/rwo note <text>`

Stores manual notes.

Examples:

```text
/rwo note LFG had 4 groups looking for tank in Shattered Halls
/rwo note Fel Iron Ore was around 2g each
/rwo note Team needs Prot Paladin for Kara
/rwo note Mining slowed route but generated good startup gold
```

---

## Data We Want to Track

### Session Data

```text
session_id
character
realm
faction
class
level_start
level_end
zone_start
zone_end
gold_start
gold_end
xp_start
xp_end
started_at
ended_at
duration_seconds
notes
```

### Snapshot Data

```text
snapshot_id
session_id
timestamp
character
realm
level
zone
subzone
activity
gold
xp
bags_free
durability
notes
```

### Activity Data

```text
activity_id
session_id
timestamp
activity_type
zone
level
gold
xp
note
```

### Loot / Material Data

Possible later fields:

```text
loot_id
session_id
timestamp
item_id
item_name
quantity
quality
zone
source
estimated_value
```

### Market Observation Data

Manual or imported later:

```text
observation_id
timestamp
realm
item_name
item_id
min_price
market_price
quantity
source
note
```

### LFG / Demand Signal Data

Manual at first:

```text
signal_id
timestamp
realm
channel
dungeon
role_needed
message_count
note
```

Example:

```text
2026-06-29, Gehennas, LFG, Shattered Halls, Tank, 5, "multiple groups looking for tank within 10 minutes"
```

---

## SavedVariables

The addon should store data in:

```lua
RingoWoWOpsDB = {
  version = "0.1.0",
  sessions = {},
  snapshots = {},
  activities = {},
  notes = {},
  loot = {},
  settings = {}
}
```

The SavedVariables file will be written by WoW after logout, exit, or `/reload`.

Expected location:

```text
World of Warcraft/_classic_/WTF/Account/<ACCOUNT>/SavedVariables/RingoWoWOps.lua
```

---

## External Data Sources

Possible future data sources:

### 1. Player-owned addon data

Most reliable for personal decision-making.

Examples:

* leveling speed
* gold gained
* materials collected
* dungeon value
* time spent
* activity efficiency

### 2. Auction House data

Possible sources:

* Auctionator export
* TSM data
* Blizzard API where available
* manual price notes

### 3. Market indicators

Public gold-market pages can be used only as external economic indicators.

They should not be used for automation or rule-breaking.

Possible tracked signals:

* general realm demand
* relative price movement
* liquidity
* seller count
* delivery pressure
* market trend

### 4. Community and raid data

Manual or Discord-based later:

* raid signups
* role shortages
* attendance
* invite performance
* buyer/recruitment notes
* raid duration
* loot distribution notes
* guild bank movements

---

## Analysis Goals

### Leveling Analysis

Questions:

* Which zones gave the best XP/hour?
* Did gathering slow down leveling too much?
* Which travel routes wasted time?
* When should the player train?
* Which dungeons were worth it?
* Which levels had the biggest slowdown?

### Gold Analysis

Questions:

* What was the actual gold/hour?
* What activities produced the most gold?
* What materials were worth gathering?
* What costs reduced profit?
* When did training, mount, repairs, or auction fees affect capital?

### Activity Analysis

Questions:

* Questing vs dungeon vs gathering: which is best today?
* Should the player keep leveling or pause for gold?
* When is it worth switching from Ret to Prot?
* When should the player start tanking dungeons seriously?

### Market Analysis

Questions:

* Which materials should be watched?
* Which materials are likely worth holding?
* Which materials should be sold early for mount/training capital?
* Which items matter before raid phase changes?

### Raid / Team Analysis

Questions:

* Which raid format creates the best return?
* Which roles are bottlenecks?
* Which team members are reliable?
* Which schedule works best?
* Which activities prepare the player for higher-value operations?

---

## Future Modules

### Addon

* slash commands
* basic UI panel
* minimap button
* session timer
* snapshot button
* activity selector
* note input
* loot tracker
* dungeon tracker
* export report text

### Python Tools

* parse SavedVariables
* export CSV
* import to SQLite
* calculate XP/hour
* calculate gold/hour
* calculate material value
* generate daily report
* generate weekly report

### Dashboard

* personal character overview
* session history
* XP/hour chart
* gold/hour chart
* best zones
* best activities
* material tracker
* dungeon tracker
* notes timeline
* recommendation page

### Discord Bot

Potential future usage:

* weekly raid schedule
* role signup
* team notes
* attendance tracking
* raid report summary
* market watch summary
* daily plan message

### AI Assistant

Possible future AI outputs:

* daily gameplay plan
* weekly performance review
* leveling route suggestions
* sell/hold/watch recommendations
* raid preparation checklist
* economy notes
* risk warnings
* next best action

---

## Compliance and Safety

This project is not intended to automate gameplay.

Allowed project behavior:

* passive data logging
* manual notes
* manual snapshots
* manual reports
* analysis outside the game
* dashboard visualization
* AI-assisted planning

Disallowed project behavior:

* automated gameplay
* botting
* automatic combat
* automatic movement
* automatic auction actions
* automatic social spam
* automatic group formation
* protected in-game actions without player input
* tools designed for rule-breaking

---

## Development Roadmap

### Phase 0 — Planning

* Define data schema
* Define addon commands
* Define SavedVariables format
* Define first CSV output
* Define MVP success criteria

### Phase 1 — Addon MVP

Goal: collect useful session data.

Features:

* `/rwo start`
* `/rwo snap`
* `/rwo stop`
* `/rwo status`
* `/rwo note`
* `/rwo activity`

Output:

* SavedVariables with sessions, snapshots, notes, and activity markers

### Phase 2 — Parser

Goal: convert SavedVariables into usable local data.

Features:

* parse Lua SavedVariables
* export sessions.csv
* export snapshots.csv
* export notes.csv
* export activities.csv

### Phase 3 — First Analysis

Goal: answer simple performance questions.

Metrics:

* XP/hour
* gold/hour
* session duration
* gold gained
* zones visited
* activities performed
* notes by category

### Phase 4 — Personal Decision Reports

Goal: create daily planning summaries.

Example output:

```text
Yesterday:
- 4.2 hours played
- +3 levels
- +42g net
- Best zone: Ghostlands
- Best activity: questing + gathering
- Main friction: bag space and travel

Today:
- Continue Ghostlands until level 21
- Train in Silvermoon
- Upgrade bags if under 8 slots
- Do not dungeon unless group is ready
```

### Phase 5 — Market Tracking

Goal: start connecting player activity with market observations.

Features:

* manual market notes
* Auctionator/TSM import
* item watchlist
* price trend notes

### Phase 6 — Raid Operations

Goal: support community and raid planning.

Features:

* raid event logs
* team notes
* attendance
* role shortage notes
* raid duration
* performance notes
* payout/accounting notes where appropriate and compliant

### Phase 7 — Dashboard

Goal: create a full local/private analytics dashboard.

Possible stack:

* Python
* Flask or Django
* SQLite
* simple charts
* local-first design

---

## MVP Success Criteria

The first version is successful if it can answer:

1. How long did I play today?
2. How much XP did I gain?
3. How much gold did I gain or lose?
4. What was my main activity?
5. Which zone was I in?
6. What notes did I record?
7. What should I do next based on the data?

---

## License

To be decided.

Recommended for a private/personal project:

```text
All rights reserved initially.
```

Recommended if open-sourced later:

```text
MIT License
```

---

## Project Status

Current status:

```text
Planning / MVP design
```

Next step:

```text
Build addon v0.1 with slash commands and SavedVariables logging.
```

---

## Local Development Quick Start

### 1. Install the addon

Copy the addon folder:

```text
addon/RingoWoWOps

into your WoW Classic AddOns folder.

Example Windows path:

C:\Program Files (x86)\World of Warcraft\_classic_\Interface\AddOns\RingoWoWOps

If your client uses a different folder for Anniversary/TBC Classic, place it under that client’s Interface/AddOns folder.

2. Enable addon in-game

On the character selection screen:

Click AddOns
Enable RingoWoWOps
Enable Load out of date AddOns if needed
3. Test commands in game
/rwo status
/rwo start
/rwo activity questing
/rwo snap
/rwo note first test note
/rwo stop

After testing, run:

/reload

or log out to force SavedVariables to be written.

4. Find SavedVariables

Expected file path:

World of Warcraft\_classic_\WTF\Account\<ACCOUNT_NAME>\SavedVariables\RingoWoWOps.lua

Copy that file into:

data/raw/RingoWoWOps.lua
5. Parse SavedVariables to CSV

Install parser dependency:

pip install lupa

Run:

python tools/parse_savedvariables.py data/raw/RingoWoWOps.lua --out data/processed

Expected outputs:

data/processed/sessions.csv
data/processed/snapshots.csv
data/processed/notes.csv
data/processed/activities.csv
Current MVP Test Checklist
 Addon appears in WoW AddOns list
 /rwo status works
 /rwo start starts a session
 /rwo activity questing saves activity
 /rwo snap saves a snapshot
 /rwo note test saves a note
 /rwo stop ends the session
 SavedVariables file is created after /reload or logout
 Python parser creates CSV files

