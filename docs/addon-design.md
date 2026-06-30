`RingoWoWOps Addon Design

MVP v0.1 commands:

/rwo status
/rwo start
/rwo activity <type>
/rwo snap
/rwo note <text>
/rwo stop

Structured data-quality commands:

/rwo gift <amount> <source>
/rwo train <text>
/rwo ahscan <items_count>
/rwo market <text>

Install path:
World of Warcraft/classic/Interface/AddOns/RingoWoWOps

SavedVariables path:
World of Warcraft/classic/WTF/Account/<ACCOUNT>/SavedVariables/RingoWoWOps.lua

Test flow:

Enable addon in character screen.
Login.
Run /rwo status.
Run /rwo start.
Run /rwo activity questing.
Run /rwo snap.
Run /rwo note first test.
Run /rwo gift 10000 friend-name.
Run /rwo train learned Journeyman Mining.
Run /rwo ahscan 42.
Run /rwo market copper ore rising in Silvermoon.
Run /rwo stop.
Run /reload.
Copy SavedVariables file to data/raw/RingoWoWOps.lua.
Parse with Python.

Safety:
The addon only reads state and saves notes/snapshots/events. It does not automate gameplay, combat, movement, auctions, whispers, invites, or protected actions.
