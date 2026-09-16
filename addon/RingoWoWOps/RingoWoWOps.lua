local ADDON_NAME = "RingoWoWOps"
local ADDON_VERSION = "0.3.0"
local SCHEMA_VERSION = 3

RingoWoWOpsDB = RingoWoWOpsDB

local function EnsureTable(name)
  if type(RingoWoWOpsDB[name]) ~= "table" then
    RingoWoWOpsDB[name] = {}
  end

  return RingoWoWOpsDB[name]
end

local currentSession = nil
local currentActivity = "questing"
local lastZone = nil

local function initializeDatabase()
  RingoWoWOpsDB = type(RingoWoWOpsDB) == "table" and RingoWoWOpsDB or {}

  local migrations = {
    function()
      EnsureTable("sessions")
      EnsureTable("snapshots")
      EnsureTable("notes")
      EnsureTable("activities")
      EnsureTable("events")
      EnsureTable("settings")
    end,
    function()
      local settings = EnsureTable("settings")
      settings.default_activity = settings.default_activity or "questing"
      settings.next_record_sequence = tonumber(settings.next_record_sequence) or 1
    end,
    function()
      local settings = EnsureTable("settings")
      if settings.active_session_id == "" then
        settings.active_session_id = nil
      end
    end
  }

  local currentSchema = tonumber(RingoWoWOpsDB.schema_version) or 0
  for version = currentSchema + 1, SCHEMA_VERSION do
    migrations[version]()
    RingoWoWOpsDB.schema_version = version
  end

  -- Always validate containers without replacing existing tables or records.
  EnsureTable("sessions")
  EnsureTable("snapshots")
  EnsureTable("notes")
  EnsureTable("activities")
  EnsureTable("events")
  EnsureTable("settings")
  RingoWoWOpsDB.version = ADDON_VERSION
  currentActivity = RingoWoWOpsDB.settings.default_activity or "questing"
end

local function now()
  return time()
end

local function getGold()
  return GetMoney() or 0
end

local function getXP()
  return UnitXP("player") or 0
end

local function getXPMax()
  return UnitXPMax("player") or 0
end

local function getRestedXP()
  if GetXPExhaustion then
    return GetXPExhaustion() or 0
  end

  return 0
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

local function newRecordID(kind)
  local settings = EnsureTable("settings")
  local sequence = tonumber(settings.next_record_sequence) or 1
  settings.next_record_sequence = sequence + 1
  return table.concat({ kind, tostring(now()), getCharacter(), getRealm(), tostring(sequence) }, "-")
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
    if C_Container and C_Container.GetContainerNumFreeSlots then
      free = free + (C_Container.GetContainerNumFreeSlots(bag) or 0)
    elseif GetContainerNumFreeSlots then
      free = free + (GetContainerNumFreeSlots(bag) or 0)
    end
  end
  return free
end

local function printMsg(msg)
  print("|cff00ff99RingoWoWOps:|r " .. msg)
end

local function isPrimaryRealm()
  local primary = RingoWoWOpsDB.settings.primary_realm
  if not primary or primary == "" then
    return true
  end
  return getRealm() == primary
end

local function snapshot(reason)
  local snap = {
    id = newRecordID("snapshot"),
    session_id = currentSession and currentSession.id or nil,
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
    xp_max = getXPMax(),
    rested_xp = getRestedXP(),
    gold = getGold(),
    bags_free = getBagsFree(),
    activity = currentActivity,
    primary_realm = isPrimaryRealm()
  }

  table.insert(EnsureTable("snapshots"), snap)
  return snap
end

local function addActivityRecord(activity, source)
  table.insert(EnsureTable("activities"), {
    id = newRecordID("activity"),
    session_id = currentSession and currentSession.id or nil,
    time = now(),
    character = getCharacter(),
    realm = getRealm(),
    level = getLevel(),
    zone = getZone(),
    activity = activity,
    source = source or "manual",
    primary_realm = isPrimaryRealm()
  })
end

local function addStructuredEvent(eventType, text, details)
  table.insert(EnsureTable("events"), {
    id = newRecordID("event"),
    session_id = currentSession and currentSession.id or nil,
    time = now(),
    character = getCharacter(),
    realm = getRealm(),
    level = getLevel(),
    zone = getZone(),
    type = eventType,
    text = text or "",
    details = details or "",
    gold = getGold(),
    activity = currentActivity,
    primary_realm = isPrimaryRealm()
  })

  printMsg("Event saved: " .. eventType)
end

local function addGiftEvent(rest)
  local amount, source = (rest or ""):match("^(%S+)%s+(.+)$")
  if not amount or not source or source == "" then
    printMsg("Usage: /rwo gift <amount> <source>")
    return
  end

  addStructuredEvent("gift", "gift " .. amount .. " " .. source, "amount=" .. amount .. "; source=" .. source)
end

local function addTrainingEvent(text)
  if not text or text == "" then
    printMsg("Usage: /rwo train <text>")
    return
  end

  addStructuredEvent("training", text, text)
end

local function addAHScanEvent(itemsCount)
  if not itemsCount or itemsCount == "" then
    printMsg("Usage: /rwo ahscan <items_count>")
    return
  end

  addStructuredEvent("ahscan", "ahscan " .. itemsCount, "items_count=" .. itemsCount)
end

local function addMarketEvent(text)
  if not text or text == "" then
    printMsg("Usage: /rwo market <text>")
    return
  end

  addStructuredEvent("market", text, text)
end

local function startSession(source)
  if currentSession then
    if source ~= "auto" then
      printMsg("Session already running.")
    end
    return
  end

  if not currentActivity or currentActivity == "idle" then
    currentActivity = RingoWoWOpsDB.settings.default_activity or "questing"
  end

  currentSession = {
    id = newRecordID("session"),
    status = "running",
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
    activity_start = currentActivity,
    start_source = source or "manual",
    primary_realm = isPrimaryRealm()
  }

  table.insert(EnsureTable("sessions"), currentSession)
  RingoWoWOpsDB.settings.active_session_id = currentSession.id
  snapshot(source == "auto" and "auto_session_start" or "session_start")
  addActivityRecord(currentActivity, source == "auto" and "auto_session_start" or "session_start")

  if source == "auto" then
    printMsg("Auto session started. Activity: " .. currentActivity)
  else
    printMsg("Session started. Activity: " .. currentActivity)
  end
end

local function stopSession(source)
  if not currentSession then
    if source ~= "auto" then
      printMsg("No active session.")
    end
    return
  end

  currentSession.ended_at = now()
  currentSession.duration_seconds = currentSession.ended_at - currentSession.started_at
  currentSession.level_end = getLevel()
  currentSession.zone_end = getZone()
  currentSession.xp_end = getXP()
  currentSession.gold_end = getGold()
  currentSession.activity_end = currentActivity
  currentSession.status = "completed"
  currentSession.stop_source = source or "manual"
  currentSession.primary_realm = isPrimaryRealm()

  snapshot(source == "auto" and "auto_session_stop" or "session_stop")

  local xpGained = (currentSession.xp_end or 0) - (currentSession.xp_start or 0)
  local goldGained = (currentSession.gold_end or 0) - (currentSession.gold_start or 0)

  if source ~= "auto" then
    printMsg("Session stopped. XP gained: " .. xpGained .. " | Copper gained: " .. goldGained)
    printMsg("Use /reload or logout to save SavedVariables.")
  end

  currentSession = nil
  RingoWoWOpsDB.settings.active_session_id = nil
end

local function detectNoteCategory(text)
  if not text then
    return "general"
  end

  local first = text:match("^(%S+)")
  if not first then
    return "general"
  end

  first = string.lower(first)

  if first == "ah" or first == "auction" then
    return "ah"
  elseif first == "lfg" then
    return "lfg"
  elseif first == "team" then
    return "team"
  elseif first == "route" then
    return "route"
  elseif first == "gift" then
    return "gift"
  elseif first == "gold" then
    return "gold"
  elseif first == "farm" then
    return "farm"
  end

  return "general"
end

local function addNote(text)
  if not text or text == "" then
    printMsg("Usage: /rwo note <text>")
    return
  end

  table.insert(EnsureTable("notes"), {
    id = newRecordID("note"),
    session_id = currentSession and currentSession.id or nil,
    time = now(),
    character = getCharacter(),
    realm = getRealm(),
    level = getLevel(),
    zone = getZone(),
    activity = currentActivity,
    category = detectNoteCategory(text),
    text = text,
    primary_realm = isPrimaryRealm()
  })

  printMsg("Note saved.")
end

local function setActivity(activity)
  if not activity or activity == "" then
    printMsg("Usage: /rwo activity <type>")
    return
  end

  currentActivity = string.lower(activity)
  addActivityRecord(currentActivity, "manual")

  printMsg("Activity set to: " .. currentActivity)
end

local function setDefaultActivity(activity)
  if not activity or activity == "" then
    printMsg("Usage: /rwo default <activity>")
    return
  end

  RingoWoWOpsDB.settings.default_activity = string.lower(activity)
  currentActivity = RingoWoWOpsDB.settings.default_activity
  printMsg("Default activity set to: " .. currentActivity)
end

local function setPrimaryRealm(realm)
  if not realm or realm == "" then
    RingoWoWOpsDB.settings.primary_realm = getRealm()
  else
    RingoWoWOpsDB.settings.primary_realm = realm
  end

  printMsg("Primary realm set to: " .. tostring(RingoWoWOpsDB.settings.primary_realm))
end

local function status()
  printMsg("Status")
  print("Character: " .. getCharacter() .. " - " .. getRealm())
  print("Primary realm: " .. tostring(RingoWoWOpsDB.settings.primary_realm or "not set"))
  print("Is primary realm: " .. tostring(isPrimaryRealm()))
  print("Level: " .. getLevel())
  print("Zone: " .. getZone())
  print("Gold copper: " .. getGold())
  print("XP: " .. getXP())
  print("Bags free: " .. getBagsFree())
  print("Activity: " .. currentActivity)
  print("Default activity: " .. tostring(RingoWoWOpsDB.settings.default_activity))
  print("Session running: " .. tostring(currentSession ~= nil))

  if currentSession then
    local duration = now() - (currentSession.started_at or now())
    local xpGained = getXP() - (currentSession.xp_start or getXP())
    local goldGained = getGold() - (currentSession.gold_start or getGold())

    print("Session duration seconds: " .. duration)
    print("Session XP gained: " .. xpGained)
    print("Session copper gained: " .. goldGained)
  end

  print("Sessions: " .. tostring(#EnsureTable("sessions")))
  print("Snapshots: " .. tostring(#EnsureTable("snapshots")))
  print("Notes: " .. tostring(#EnsureTable("notes")))
  print("Activities: " .. tostring(#EnsureTable("activities")))
  print("Events: " .. tostring(#EnsureTable("events")))
end

local uiFrame = nil

local function refreshUI()
  if not uiFrame then
    return
  end

  uiFrame.characterText:SetText("Character: " .. getCharacter())
  uiFrame.levelText:SetText("Level: " .. tostring(getLevel()))
  uiFrame.zoneText:SetText("Zone: " .. getZone())
  uiFrame.activityText:SetText("Activity: " .. tostring(currentActivity))
  uiFrame.sessionText:SetText("Session: " .. (currentSession and "running" or "not running"))
end

local function createLabel(parent, text, x, y)
  local label = parent:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  label:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
  label:SetText(text)
  label:SetJustifyH("LEFT")
  return label
end

local function createButton(parent, text, width, height, x, y, onClick)
  local button = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
  button:SetSize(width, height)
  button:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
  button:SetText(text)
  button:SetScript("OnClick", function()
    onClick()
    refreshUI()
  end)
  return button
end

local function createInput(parent, x, y, width)
  local input = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
  input:SetSize(width, 22)
  input:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
  input:SetAutoFocus(false)
  input:SetScript("OnEnterPressed", function(self)
    self:ClearFocus()
  end)
  input:SetScript("OnEscapePressed", function(self)
    self:ClearFocus()
  end)
  return input
end

local function createUI()
  if uiFrame then
    return uiFrame
  end

  local backdropTemplate = BackdropTemplateMixin and "BackdropTemplate" or nil
  local frame = CreateFrame("Frame", "RingoWoWOpsMiniPanel", UIParent, backdropTemplate)
  frame:SetSize(250, 275)
  frame:SetPoint("CENTER")
  frame:SetMovable(true)
  frame:EnableMouse(true)
  frame:RegisterForDrag("LeftButton")
  frame:SetClampedToScreen(true)
  frame:SetScript("OnDragStart", frame.StartMoving)
  frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
  if frame.SetBackdrop then
    frame:SetBackdrop({
      bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
      edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
      tile = true,
      tileSize = 32,
      edgeSize = 16,
      insets = { left = 4, right = 4, top = 4, bottom = 4 }
    })
  end
  frame:Hide()

  local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  title:SetPoint("TOPLEFT", frame, "TOPLEFT", 12, -10)
  title:SetText("RingoWoWOps")

  local closeButton = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
  closeButton:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -4, -4)

  frame.characterText = createLabel(frame, "Character:", 12, -34)
  frame.levelText = createLabel(frame, "Level:", 12, -50)
  frame.zoneText = createLabel(frame, "Zone:", 12, -66)
  frame.activityText = createLabel(frame, "Activity:", 12, -82)
  frame.sessionText = createLabel(frame, "Session:", 12, -98)

  createButton(frame, "Status", 70, 22, 12, -122, status)
  createButton(frame, "Snap", 70, 22, 88, -122, function()
    snapshot("ui")
    printMsg("Snapshot saved.")
  end)

  createButton(frame, "Questing", 70, 22, 12, -150, function() setActivity("questing") end)
  createButton(frame, "Training", 70, 22, 88, -150, function() setActivity("training") end)
  createButton(frame, "Auction", 70, 22, 164, -150, function() setActivity("auction") end)
  createButton(frame, "Gathering", 70, 22, 12, -178, function() setActivity("gathering") end)
  createButton(frame, "Dungeon", 70, 22, 88, -178, function() setActivity("dungeon") end)

  createLabel(frame, "Quick note", 12, -207)
  frame.noteInput = createInput(frame, 82, -202, 90)
  createButton(frame, "Save Note", 65, 22, 176, -202, function()
    local text = frame.noteInput:GetText()
    addNote(text)
    frame.noteInput:SetText("")
  end)

  createLabel(frame, "Market", 12, -235)
  frame.marketInput = createInput(frame, 82, -230, 90)
  createButton(frame, "Save Market", 65, 22, 176, -230, function()
    local text = frame.marketInput:GetText()
    addMarketEvent(text)
    frame.marketInput:SetText("")
  end)

  uiFrame = frame
  refreshUI()
  return uiFrame
end

local function toggleUI()
  local frame = createUI()
  if frame:IsShown() then
    frame:Hide()
  else
    refreshUI()
    frame:Show()
  end
end

SLASH_RINGOWOWOPS1 = "/rwo"
SlashCmdList["RINGOWOWOPS"] = function(msg)
  local command, rest = msg:match("^(%S*)%s*(.-)$")
  command = string.lower(command or "")

  if command == "start" then
    startSession("manual")
  elseif command == "snap" then
    snapshot("manual")
    printMsg("Snapshot saved.")
  elseif command == "stop" then
    stopSession("manual")
  elseif command == "status" then
    status()
  elseif command == "ui" then
    toggleUI()
  elseif command == "note" then
    addNote(rest)
  elseif command == "gift" then
    addGiftEvent(rest)
  elseif command == "train" then
    addTrainingEvent(rest)
  elseif command == "ahscan" then
    addAHScanEvent(rest)
  elseif command == "market" then
    addMarketEvent(rest)
  elseif command == "activity" then
    setActivity(rest)
  elseif command == "default" then
    setDefaultActivity(rest)
  elseif command == "realm" then
    setPrimaryRealm(rest)
  else
    printMsg("Commands: start, snap, stop, status, ui, note <text>, gift <amount> <source>, train <text>, ahscan <items_count>, market <text>, activity <type>, default <activity>, realm [name]")
  end
end

local eventFrame = CreateFrame("Frame")

eventFrame:RegisterEvent("ADDON_LOADED")
eventFrame:RegisterEvent("PLAYER_LOGIN")
eventFrame:RegisterEvent("PLAYER_LOGOUT")
eventFrame:RegisterEvent("PLAYER_LEVEL_UP")
eventFrame:RegisterEvent("ZONE_CHANGED_NEW_AREA")

eventFrame:SetScript("OnEvent", function(_, event, ...)
  if event == "ADDON_LOADED" then
    local loadedAddon = ...
    if loadedAddon ~= ADDON_NAME then
      return
    end
    initializeDatabase()

  elseif event == "PLAYER_LOGIN" then
    initializeDatabase()
    lastZone = getZone()
    currentActivity = RingoWoWOpsDB.settings.default_activity or "questing"

    -- A persisted active ID means WoW did not complete the prior logout path.
    -- Preserve that session as incomplete; never invent a crash end time.
    local interruptedID = RingoWoWOpsDB.settings.active_session_id
    if interruptedID then
      for _, session in ipairs(EnsureTable("sessions")) do
        if session.id == interruptedID and session.status == "running" then
          session.status = "incomplete"
          session.recovery_detected_at = now()
          session.recovery_reason = "login_after_unclean_shutdown"
          break
        end
      end
      RingoWoWOpsDB.settings.active_session_id = nil
    end
    startSession("auto")

  elseif event == "PLAYER_LOGOUT" then
    stopSession("auto")

  elseif event == "PLAYER_LEVEL_UP" then
    snapshot("auto_level_up")
    printMsg("Auto snapshot saved: level up.")

  elseif event == "ZONE_CHANGED_NEW_AREA" then
    local zone = getZone()
    if zone ~= "" and zone ~= lastZone then
      lastZone = zone
      snapshot("auto_zone_change")
      printMsg("Auto snapshot saved: zone change.")
    end
  end

  refreshUI()
end)

printMsg("Loaded v" .. ADDON_VERSION .. ". Auto session enabled.")
