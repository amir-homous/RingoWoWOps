local ADDON_NAME = "RingoWoWOps"

RingoWoWOpsDB = RingoWoWOpsDB or {
  version = "0.1.0",
  sessions = {},
  snapshots = {},
  notes = {},
  activities = {},
  settings = {}
}

local currentSession = nil
local currentActivity = "idle"

local function now()
  return time()
end

local function getGold()
  return GetMoney()
end

local function getXP()
  return UnitXP("player") or 0
end

local function getLevel()
  return UnitLevel("player") or 0
end

local function getZone()
  return GetZoneText() or ""
end

local function getSubZone()
  return GetSubZoneText() or ""
end

local function getCharacter()
  return UnitName("player") or "Unknown"
end

local function getRealm()
  return GetRealmName() or "Unknown"
end

local function getClass()
  local _, classFile = UnitClass("player")
  return classFile or "Unknown"
end

local function getFaction()
  return UnitFactionGroup("player") or "Unknown"
end

local function getBagsFree()
  local free = 0
  for bag = 0, 4 do
    free = free + (C_Container and C_Container.GetContainerNumFreeSlots(bag) or GetContainerNumFreeSlots(bag) or 0)
  end
  return free
end

local function snapshot(reason)
  local snap = {
    time = now(),
    reason = reason or "manual",
    character = getCharacter(),
    realm = getRealm(),
    faction = getFaction(),
    class = getClass(),
    level = getLevel(),
    zone = getZone(),
    subzone = getSubZone(),
    xp = getXP(),
    gold = getGold(),
    bags_free = getBagsFree(),
    activity = currentActivity
  }

  table.insert(RingoWoWOpsDB.snapshots, snap)
  return snap
end

local function printMsg(msg)
  print("|cff00ff99RingoWoWOps:|r " .. msg)
end

local function startSession()
  if currentSession then
    printMsg("Session already running.")
    return
  end

  local startSnap = snapshot("session_start")

  currentSession = {
    id = tostring(now()) .. "-" .. getCharacter(),
    started_at = now(),
    ended_at = nil,
    character = getCharacter(),
    realm = getRealm(),
    faction = getFaction(),
    class = getClass(),
    level_start = getLevel(),
    zone_start = getZone(),
    xp_start = getXP(),
    gold_start = getGold(),
    activity_start = currentActivity
  }

  table.insert(RingoWoWOpsDB.sessions, currentSession)
  printMsg("Session started.")
end

local function stopSession()
  if not currentSession then
    printMsg("No active session.")
    return
  end

  currentSession.ended_at = now()
  currentSession.duration_seconds = currentSession.ended_at - currentSession.started_at
  currentSession.level_end = getLevel()
  currentSession.zone_end = getZone()
  currentSession.xp_end = getXP()
  currentSession.gold_end = getGold()
  currentSession.activity_end = currentActivity

  snapshot("session_stop")

  printMsg("Session stopped. Use /reload or logout to save SavedVariables.")
  currentSession = nil
end

local function addNote(text)
  if not text or text == "" then
    printMsg("Usage: /rwo note <text>")
    return
  end

  table.insert(RingoWoWOpsDB.notes, {
    time = now(),
    character = getCharacter(),
    realm = getRealm(),
    level = getLevel(),
    zone = getZone(),
    activity = currentActivity,
    text = text
  })

  printMsg("Note saved.")
end

local function setActivity(activity)
  if not activity or activity == "" then
    printMsg("Usage: /rwo activity <type>")
    return
  end

  currentActivity = activity

  table.insert(RingoWoWOpsDB.activities, {
    time = now(),
    character = getCharacter(),
    realm = getRealm(),
    level = getLevel(),
    zone = getZone(),
    activity = activity
  })

  printMsg("Activity set to: " .. activity)
end

local function status()
  printMsg("Status")
  print("Character: " .. getCharacter() .. " - " .. getRealm())
  print("Level: " .. getLevel())
  print("Zone: " .. getZone())
  print("Gold copper: " .. getGold())
  print("XP: " .. getXP())
  print("Bags free: " .. getBagsFree())
  print("Activity: " .. currentActivity)
  print("Session running: " .. tostring(currentSession ~= nil))
end

SLASH_RINGOWOWOPS1 = "/rwo"
SlashCmdList["RINGOWOWOPS"] = function(msg)
  local command, rest = msg:match("^(%S*)%s*(.-)$")

  if command == "start" then
    startSession()
  elseif command == "snap" then
    snapshot("manual")
    printMsg("Snapshot saved.")
  elseif command == "stop" then
    stopSession()
  elseif command == "status" then
    status()
  elseif command == "note" then
    addNote(rest)
  elseif command == "activity" then
    setActivity(rest)
  else
    printMsg("Commands: start, snap, stop, status, note <text>, activity <type>")
  end
end

printMsg("Loaded. Use /rwo start")
