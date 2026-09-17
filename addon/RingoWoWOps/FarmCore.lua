-- Immutable run headers + full, immutable transition snapshots. Active control is
-- a recoverable pointer, never the evidence exported to SQLite.
RingoWoWOpsFarm = {}
local F = RingoWoWOpsFarm
F.generation=0
local api, latest, headers, loaded = nil, {}, {}, false
local historyCache, historyGeneration, historyIdentity
function F.Session() return api and api.session() end
local terminal = {completed=true, abandoned=true, incomplete=true}
local transitions = {
  prepared={start="running", abandon="abandoned", interrupt="incomplete", note="prepared"},
  running={finish="review", abandon="abandoned", interrupt="incomplete", note="running"},
  review={complete="completed", abandon="abandoned", interrupt="incomplete", note="review"}
}
F.transitions = transitions

local function copy(row)
  local result = {}
  for k,v in pairs(row or {}) do result[k]=v end
  return result
end
local function key() return api.character() .. "\031" .. api.realm() end
local function db() return RingoWoWOpsDB end
local function say(text) api.message("Farm: " .. text) end

function F.Preset(id)
  for _, preset in ipairs(RingoWoWOpsFarmPresets) do if preset.id==id then return preset end end
end

function F.Initialize(dependencies)
  api = dependencies
  for _, name in ipairs({"farm_runs", "farm_run_events", "farm_settings", "active_farm_run"}) do
    if type(db()[name]) ~= "table" then db()[name] = {} end
  end
  if not loaded then
    for _, row in ipairs(db().farm_runs) do headers[row.record_id]=row; latest[row.record_id]=row end
    for _, event in ipairs(db().farm_run_events) do
      local old = latest[event.farm_run_id]
      if old and (event.revision or 0) > (old.revision or 0) then latest[event.farm_run_id]=event end
    end
    loaded = true
  end
end

function F.Settings()
  local all = db().farm_settings
  if type(all[key()]) ~= "table" then all[key()] = {} end
  local s=all[key()]
  if not s.default_preset then s.default_preset="STRATHOLME_PALADIN" end
  if s.auto_open==nil then s.auto_open=false end
  if s.suggestions==nil then s.suggestions=true end
  if not s.scale then s.scale=1 end
  -- WoW cannot read Python's config or IANA zone database. Explicit fixed UTC
  -- offset defaults to Tehran (+03:30); shown and editable in Settings.
  if s.day_offset_minutes==nil then s.day_offset_minutes=210 end
  return s
end

function F.Day(timestamp, offset)
  return date("!%Y-%m-%d", timestamp + (offset or F.Settings().day_offset_minutes)*60)
end

function F.Context()
  local name, kind, difficulty
  if GetInstanceInfo then name,kind,difficulty=GetInstanceInfo() end
  local inside = false
  if IsInInstance then inside = IsInInstance() == true end
  return {zone=GetZoneText and GetZoneText() or "", instance_name=inside and name or nil,
          difficulty_id=inside and type(difficulty)=="number" and difficulty or nil, inside=inside, kind=kind}
end

function F.Current()
  local control=db().active_farm_run[key()]
  return control and latest[control.run_id] or nil
end

function F.History()
  if historyCache and historyGeneration==F.generation and historyIdentity==key() then return historyCache end
  local result={}
  for id, row in pairs(latest) do
    if row.character==api.character() and row.realm==api.realm() then
      local item=copy(row); item.farm_run_id=id; table.insert(result,item)
    end
  end
  table.sort(result,function(a,b)
    if a.created_at==b.created_at then return a.farm_run_id>b.farm_run_id end
    return a.created_at>b.created_at
  end)
  historyCache=result; historyGeneration=F.generation; historyIdentity=key()
  return result
end

function F.Summary()
  local summary={completed=0, duration=0, raw=0, raw_count=0, incomplete=0, abandoned=0}
  local today=F.Day(api.now())
  for _,r in ipairs(F.History()) do
    if F.Day(r.started_at or r.created_at)==today then
      if r.status=="completed" then
        summary.completed=summary.completed+1
        summary.duration=summary.duration+r.duration_seconds
        summary.fastest=math.min(summary.fastest or r.duration_seconds,r.duration_seconds)
        if r.raw_gold_delta_copper~=nil then summary.raw=summary.raw+r.raw_gold_delta_copper; summary.raw_count=summary.raw_count+1 end
      elseif r.status=="incomplete" or r.status=="abandoned" then summary[r.status]=summary[r.status]+1 end
    end
  end
  return summary
end

local function append(runID, row, eventType, from)
  local event=copy(row)
  event.record_id=api.id("farm-event")
  event.farm_run_id=runID
  event.event_type=eventType
  event.from_status=from
  event.time=api.now()
  event.updated_at=event.time
  event.revision=(latest[runID].revision or 0)+1
  table.insert(db().farm_run_events,event)
  latest[runID]=event
  F.generation=F.generation+1
  if terminal[event.status] then db().active_farm_run[key()]=nil end
  return event
end

function F.Prepare(presetID)
  if db().active_farm_run[key()] then say("Resolve the active run first."); return false end
  local preset=F.Preset(presetID or F.Settings().default_preset)
  if not preset or not preset.enabled then say("Preset unavailable; select Stratholme."); return false end
  local stamp=api.now()
  local row={record_id=api.id("farm"),record_schema_version=1,preset_id=preset.id,preset_version=preset.version,
    status="prepared",character=api.character(),realm=api.realm(),session_id=api.session(),
    created_at=stamp,updated_at=stamp,addon_schema_version=5,revision=0,
    started_manually=false,finished_manually=false,reset_confirmed=false,note=""}
  table.insert(db().farm_runs,row)
  headers[row.record_id]=row; latest[row.record_id]=row
  db().active_farm_run[key()]={run_id=row.record_id}
  append(row.record_id,row,"prepared","idle")
  say("Prepared " .. preset.display_name)
  return true
end

function F.Action(action, text)
  local current=F.Current()
  local target=current and transitions[current.status] and transitions[current.status][action]
  if not target then say("Invalid action for current state."); return false end
  if action=="abandon" and text~="confirm" then say("Confirm Abandon in the dashboard or use /rwo farm abandon confirm."); return false end
  if action=="note" and (not text or not text:match("%S") or #text>1000) then say("Note must contain 1-1000 bytes of text."); return false end
  local stamp=api.now()
  if stamp < current.updated_at and action~="interrupt" then say("Clock moved backwards; resolve clock before recording transition."); return false end
  local row=copy(current)
  local context=F.Context()
  row.status=target
  local eventType=({start="started",finish="finish_requested",complete="completed",abandon="abandoned",interrupt="interrupted",note="note_added"})[action]
  if action=="start" then
    local preset=F.Preset(row.preset_id)
    if not preset or not preset.enabled then say("Preset unavailable."); return false end
    row.started_at=stamp; row.started_manually=true; row.session_id=api.session()
    row.start_zone=context.zone; row.start_instance_name=context.instance_name; row.difficulty_id=context.difficulty_id
    row.start_gold_copper=GetMoney and GetMoney() or nil
    row.local_day=F.Day(stamp); row.day_offset_minutes=F.Settings().day_offset_minutes
    local number=0
    for _,old in ipairs(F.History()) do
      if old.started_at and F.Day(old.started_at,row.day_offset_minutes)==row.local_day then number=number+1 end
    end
    row.run_number_local_day=number+1
  elseif action=="finish" then
    row.finished_at=stamp; row.duration_seconds=stamp-row.started_at; row.finished_manually=true
    row.end_zone=context.zone; row.end_instance_name=context.instance_name
    row.end_gold_copper=GetMoney and GetMoney() or nil
    if row.start_gold_copper~=nil and row.end_gold_copper~=nil then row.raw_gold_delta_copper=row.end_gold_copper-row.start_gold_copper end
  elseif action=="complete" then row.completed_at=stamp; row.reset_confirmed=true
  elseif action=="interrupt" then row.interruption_reason=text or "unclean_restart"
  elseif action=="abandon" then row.interruption_reason="manual_abandon"
  elseif action=="note" then row.note=(row.note~="" and row.note .. "\n" or "") .. text end
  append(current.farm_run_id or current.record_id,row,eventType,current.status)
  say(target .. (action=="complete" and "; reset confirmation recorded only." or ""))
  return true
end

function F.Recover(isReload)
  local control=db().active_farm_run[key()]
  if not control then return end
  local row=latest[control.run_id]
  if not row or row.character~=api.character() or row.realm~=api.realm() then
    say("Unresolved active pointer; history retained. Review SavedVariables before starting another run.")
    F.warning="Invalid active pointer; manual data review required."
    return
  end
  if terminal[row.status] then db().active_farm_run[key()]=nil; return end
  if isReload==true and control.clean_logout then
    F.warning="Run preserved across reload; elapsed time includes reload."
  elseif control.clean_logout and row.status~="running" then
    F.warning="Prepared/review run restored after logout."
  else
    F.Action("interrupt",control.clean_logout and "logout_or_character_switch" or "unclean_restart")
    F.warning="Prior run marked incomplete. No end time or duration was invented."
  end
  if db().active_farm_run[key()] then db().active_farm_run[key()].clean_logout=nil end
end

function F.Logout()
  local control=db().active_farm_run[key()]
  if control then control.clean_logout=true end
end

function F.Command(rest)
  local action,arg=(rest or ""):match("^(%S*)%s*(.-)$")
  if action=="" then if RingoWoWOpsFarmDashboard then RingoWoWOpsFarmDashboard.Toggle() end
  elseif action=="prepare" then F.Prepare(arg~="" and arg or nil)
  elseif action=="status" then local r=F.Current(); say(r and (r.preset_id .. " / " .. r.status) or "idle")
  elseif action=="start" or action=="finish" or action=="complete" or action=="abandon" or action=="note" then F.Action(action,arg)
  else say("prepare [preset], start, finish, complete, abandon confirm, note <text>, status. /rwo farm opens dashboard.") end
  if RingoWoWOpsFarmDashboard then RingoWoWOpsFarmDashboard.Refresh() end
end

local entered=false
function F.ObserveContext()
  local context=F.Context()
  if context.inside and not entered then
    for _,p in ipairs(RingoWoWOpsFarmPresets) do
      if p.enabled and p.instance_name==context.instance_name then
        local combat=InCombatLockdown and InCombatLockdown()
        if not combat then
          if F.Settings().suggestions then say("Instance appears to match " .. p.display_name .. "; prepare manually.") end
          if F.Settings().auto_open and RingoWoWOpsFarmDashboard then RingoWoWOpsFarmDashboard.Show() end
        end
      end
    end
  end
  entered=context.inside
end
