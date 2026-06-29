`RingoWoWOps Addon Design

MVP v0.1 commands:

/rwo status
/rwo start
/rwo activity <type>
/rwo snap
/rwo note <text>
/rwo stop

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
Run /rwo stop.
Run /reload.
Copy SavedVariables file to data/raw/RingoWoWOps.lua.
Parse with Python.

Safety:
The addon only reads state and saves notes/snapshots. It does not automate gameplay.