-- Native, non-secure WoW controls. No gameplay actions or external UI dependencies.
RingoWoWOpsFarmDashboard = {}
local D, F = RingoWoWOpsFarmDashboard, RingoWoWOpsFarm
local window, panels, navigation, live, history, settings = nil, {}, {}, {}, {}, {}
local selectedTab, selectedRun, page = "Live Run", nil, 1
local lastGeneration, lastDay, cachedSummary = nil, nil, nil
local colors = {running="|cff79d6a0", review="|cffe7bf6b", prepared="|cffb4c7dd",
  completed="|cff79d6a0", incomplete="|cfff08c78", abandoned="|cfff08c78", idle="|cffaaaaaa"}

local function text(parent, value, x, y, width, height, font)
  local label=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlightSmall")
  label:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y)
  label:SetSize(width or 720,height or 22); label:SetJustifyH("LEFT"); label:SetJustifyV("TOP")
  label:SetText(value)
  return label
end
local function button(parent, title, x, y, width, action)
  local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate")
  b:SetSize(width or 160,28); b:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y); b:SetText(title)
  b:SetScript("OnClick",function() action(); D.Refresh() end)
  return b
end
local function input(parent,x,y,width)
  local box=CreateFrame("EditBox",nil,parent,"InputBoxTemplate")
  box:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y); box:SetSize(width,24); box:SetAutoFocus(false)
  box:SetMaxLetters(1000)
  box:SetScript("OnEscapePressed",function(self) self:ClearFocus() end)
  box:SetScript("OnEnterPressed",function(self) self:ClearFocus() end)
  return box
end
local function money(value)
  if value==nil then return "unobserved" end
  local prefix=value<0 and "-" or ""; value=math.abs(value)
  return prefix .. string.format("%dg %ds %dc",math.floor(value/10000),math.floor(value/100)%100,value%100)
end
local function duration(value)
  if value==nil then return "--" end
  return string.format("%02d:%02d:%02d",math.floor(value/3600),math.floor(value/60)%60,value%60)
end
local function timestamp(value)
  return value and date("!%Y-%m-%d %H:%M:%S",value+F.Settings().day_offset_minutes*60) or "--"
end
local function applyPosition()
  local s=F.Settings()
  local width=UIParent:GetWidth(); local height=UIParent:GetHeight()
  window:SetScale(math.min(s.scale or 1, width/840, height/610))
  window:ClearAllPoints()
  window:SetPoint("CENTER",UIParent,"CENTER",s.x or 0,s.y or 0)
end
function D.Tab(name)
  selectedTab=name
  for tab,panel in pairs(panels) do
    panel:SetShown(tab==name)
    navigation[tab]:SetText((tab==name and "|cffe7bf6b" or "") .. tab .. "|r")
  end
  D.Refresh()
end

local function create()
  if window then return end
  local template=BackdropTemplateMixin and "BackdropTemplate" or nil
  window=CreateFrame("Frame","RingoWoWOpsFarmWindow",UIParent,template)
  window:SetSize(820,590); window:SetFrameStrata("DIALOG")
  window:SetClampedToScreen(true); window:SetMovable(true); window:EnableMouse(true)
  window:RegisterForDrag("LeftButton")
  window:SetScript("OnDragStart",function(self) if not F.Settings().locked then self:StartMoving() end end)
  window:SetScript("OnDragStop",function(self)
    self:StopMovingOrSizing()
    local x,y=self:GetCenter(); local px,py=UIParent:GetCenter()
    local scale=self:GetScale(); F.Settings().x=x-px/scale; F.Settings().y=y-py/scale
    self:ClearAllPoints(); self:SetPoint("CENTER",UIParent,"CENTER",F.Settings().x,F.Settings().y)
  end)
  if window.SetBackdrop then
    window:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=false,edgeSize=16,insets={left=4,right=4,top=4,bottom=4}})
    window:SetBackdropColor(0.045,0.052,0.065,0.97); window:SetBackdropBorderColor(0.55,0.43,0.23,1)
  end
  text(window,"|cffe7bf6bRINGO  /  FARM OPERATIONS|r",20,-18,720,25,"GameFontNormalLarge")
  text(window,"Manual run tracking  /  raw observations only",20,-47)
  local close=CreateFrame("Button",nil,window,"UIPanelCloseButton"); close:SetPoint("TOPRIGHT",window,"TOPRIGHT",-5,-5)
  close:SetScript("OnClick",function() window:Hide() end)
  UISpecialFrames=UISpecialFrames or {}; table.insert(UISpecialFrames,"RingoWoWOpsFarmWindow")
  for i,name in ipairs({"Live Run","History","Settings"}) do
    local tab=name
    navigation[tab]=button(window,tab,20+(i-1)*140,-76,132,function() D.Tab(tab) end)
    local panel=CreateFrame("Frame",nil,window); panel:SetPoint("TOPLEFT",window,"TOPLEFT",20,-115); panel:SetSize(780,445)
    panels[tab]=panel
  end
  local p=panels["Live Run"]
  live.identity=text(p,"",0,0)
  live.preset=text(p,"",0,-27,760,25,"GameFontNormal")
  live.state=text(p,"",0,-59,330,30,"GameFontNormalLarge")
  live.timer=text(p,"",410,-59,350,30,"GameFontNormalLarge")
  live.context=text(p,"",0,-102,760,42)
  live.balance=text(p,"",0,-148,760,45)
  live.summary=text(p,"",0,-203,760,45)
  live.warning=text(p,"",0,-260,760,40)
  live.actions={}
  live.actions.prepare=button(p,"Prepare",0,-305,180,function() F.Prepare() end)
  live.actions.start=button(p,"Start Run",0,-305,180,function() F.Action("start") end)
  live.actions.finish=button(p,"Finish Run",0,-305,180,function() F.Action("finish") end)
  live.actions.complete=button(p,"Confirm Reset & Complete",0,-305,235,function() F.Action("complete") end)
  live.actions.next=button(p,"Start Next Run",250,-305,170,function() if F.Prepare() then F.Action("start") end end)
  live.actions.abandon=button(p,"Abandon...",600,-305,160,function() live.confirm:Show(); live.cancel:Show() end)
  live.confirm=button(p,"Confirm Abandon",400,-340,180,function() F.Action("abandon","confirm"); live.confirm:Hide(); live.cancel:Hide() end)
  live.cancel=button(p,"Cancel",600,-340,160,function() live.confirm:Hide(); live.cancel:Hide() end)
  live.confirm:Hide(); live.cancel:Hide()
  live.note=input(p,5,-390,555)
  live.noteButton=button(p,"Add Note",600,-388,160,function()
    if F.Action("note",live.note:GetText()) then live.note:SetText(""); live.note:ClearFocus() end
  end)
  live.resetHint=text(p,"Complete records your confirmation. It never resets the instance.",0,-425,760,20)

  p=panels.History
  text(p,"LATEST RUNS  /  click a row for details",0,0,730,22,"GameFontNormal")
  history.rows={}
  for i=1,10 do
    local index=i
    history.rows[i]=button(p,"",0,-25-(i-1)*27,760,function()
      local rows=F.History(); local row=rows[(page-1)*10+index]
      selectedRun=row and row.farm_run_id or nil
    end)
  end
  button(p,"Newer",0,-303,90,function() page=math.max(1,page-1) end)
  button(p,"Older",100,-303,90,function() if #F.History()>page*10 then page=page+1 end end)
  local scroll=CreateFrame("ScrollFrame",nil,p,"UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT",p,"TOPLEFT",0,-340); scroll:SetSize(735,98)
  local detailBody=CreateFrame("Frame",nil,scroll); detailBody:SetSize(715,98); scroll:SetScrollChild(detailBody)
  history.detailBody=detailBody
  history.details=text(detailBody,"Select a run. No records can be deleted here.",0,0,710,98)

  p=panels.Settings
  text(p,"DEFAULT PRESET",0,0,720,22,"GameFontNormal")
  for i,preset in ipairs(RingoWoWOpsFarmPresets) do
    local choice=preset
    local b=button(p,preset.display_name .. (preset.enabled and "" or "  /  Coming next"),0,-28-(i-1)*34,400,function()
      if not F.Current() then F.Settings().default_preset=choice.id else F.warning="Resolve the active run before changing preset." end
    end)
    if not preset.enabled then b:Disable() end
  end
  settings.default=text(p,"",420,-30,340,90)
  settings.auto=button(p,"",0,-145,370,function() F.Settings().auto_open=not F.Settings().auto_open end)
  settings.suggest=button(p,"",390,-145,370,function() F.Settings().suggestions=not F.Settings().suggestions end)
  settings.lock=button(p,"",0,-189,370,function() F.Settings().locked=not F.Settings().locked end)
  button(p,"Reset position",390,-189,370,function() F.Settings().x=0; F.Settings().y=0; applyPosition() end)
  button(p,"Scale -",0,-235,120,function() F.Settings().scale=math.max(0.7,F.Settings().scale-0.1); applyPosition() end)
  button(p,"Scale +",130,-235,120,function() F.Settings().scale=math.min(1.3,F.Settings().scale+0.1); applyPosition() end)
  settings.scale=text(p,"",275,-239,460,25)
  text(p,"Day boundary: fixed UTC offset in minutes (Tehran: 210). Match your report timezone manually.",0,-287,760,40)
  settings.offset=input(p,5,-332,120)
  button(p,"Save day offset",145,-330,180,function()
    local value=tonumber(settings.offset:GetText())
    if F.Current() then F.warning="Resolve the active run before changing day boundaries."
    elseif value and value==math.floor(value) and value>=-720 and value<=840 then
      F.Settings().day_offset_minutes=value; settings.offset:ClearFocus(); lastDay=nil
    else F.warning="UTC offset must be an integer from -720 to 840." end
  end)
  button(p,"Open classic mini panel",390,-330,370,function() SlashCmdList.RINGOWOWOPS("mini") end)
  settings.warning=text(p,"",0,-385,760,48)
  window:SetScript("OnHide",function() live.note:ClearFocus(); settings.offset:ClearFocus(); live.confirm:Hide(); live.cancel:Hide() end)
  local elapsedTotal=0
  window:SetScript("OnUpdate",function(_,elapsed)
    elapsedTotal=elapsedTotal+elapsed
    if elapsedTotal>=1 then elapsedTotal=0; D.Refresh() end
  end)
  window:Hide(); applyPosition(); D.Tab("Live Run")
end

function D.Refresh()
  if not window then return end
  local row=F.Current(); local state=row and row.status or "idle"; local s=F.Settings()
  if selectedTab=="Live Run" then
    local context=F.Context(); local gold=GetMoney and GetMoney() or nil
    live.identity:SetText(UnitName("player") .. "  /  " .. GetRealmName() .. "    Session: " .. (F.Session() and "active" or "not active"))
    live.preset:SetText("Preset: " .. (F.Preset(row and row.preset_id or s.default_preset).display_name) .. "    [select in Settings]")
    live.state:SetText((colors[state] or "") .. state:upper() .. "|r    Run #" .. (row and row.run_number_local_day or "--"))
    local seconds=row and (row.duration_seconds or (row.status=="running" and math.max(0,time()-row.started_at))) or nil
    live.timer:SetText(duration(seconds))
    live.context:SetText("Started: " .. timestamp(row and row.started_at) .. "\nZone: " .. context.zone .. "   Instance: " .. (context.instance_name or "outside / unknown"))
    local delta=row and row.raw_gold_delta_copper
    if row and row.status=="running" and row.start_gold_copper~=nil and gold~=nil then delta=gold-row.start_gold_copper end
    live.balance:SetText("Start gold: " .. money(row and row.start_gold_copper) .. "   Current gold: " .. money(gold) .. "\nRaw gold change: " .. money(delta))
    local day=F.Day(time())
    if lastGeneration~=F.generation or lastDay~=day or not cachedSummary then
      cachedSummary=F.Summary(); lastGeneration=F.generation; lastDay=day
    end
    local sum=cachedSummary
    live.summary:SetText("Today: " .. sum.completed .. " completed   Average: " .. duration(sum.completed>0 and math.floor(sum.duration/sum.completed) or nil) .. "   Fastest: " .. duration(sum.fastest) ..
      "\nTotal raw gold change: " .. money(sum.raw_count>0 and sum.raw or nil) .. " (" .. sum.raw_count .. " observed)   Incomplete/abandoned: " .. (sum.incomplete+sum.abandoned))
    live.warning:SetText("|cffe7bf6b" .. (F.warning or "Manual selection is authoritative. Instance detection is a suggestion only.") .. "|r")
    live.actions.prepare:SetShown(state=="idle")
    live.actions.start:SetShown(state=="prepared")
    live.actions.finish:SetShown(state=="running")
    live.actions.complete:SetShown(state=="review")
    live.actions.next:SetShown(state=="idle" and F.generation>0)
    live.actions.abandon:SetShown(state~="idle")
    live.note:SetShown(state~="idle"); live.noteButton:SetShown(state~="idle")
    if state=="idle" then live.confirm:Hide(); live.cancel:Hide() end
  elseif selectedTab=="History" then
    local rows=F.History()
    for i,b in ipairs(history.rows) do
      local r=rows[(page-1)*10+i]; b:SetShown(r~=nil)
      if r then b:SetText("#" .. (r.run_number_local_day or "--") .. "  " .. F.Preset(r.preset_id).display_name .. "  " .. r.status .. "  " .. timestamp(r.started_at or r.created_at):sub(6,16) .. "  " .. duration(r.duration_seconds) .. "  Raw gold change " .. money(r.raw_gold_delta_copper) .. "  " .. (r.start_instance_name or "--") .. (r.note~="" and "  [note]" or "")) end
    end
    for _,r in ipairs(rows) do
      if r.farm_run_id==selectedRun then
        history.details:SetText("ID: " .. r.farm_run_id .. "\nStarted: " .. timestamp(r.started_at) .. " / Finished: " .. timestamp(r.finished_at) ..
          "\nInstance: " .. (r.start_instance_name or "unobserved / manual") .. " -> " .. (r.end_instance_name or "unobserved") ..
          "\n" .. (r.interruption_reason or "") .. "  " .. (r.note or ""))
        local height=math.max(98,history.details:GetStringHeight()+12)
        history.details:SetHeight(height); history.detailBody:SetHeight(height)
      end
    end
  else
    settings.default:SetText("Selected: " .. s.default_preset .. "\nOnly Stratholme is enabled.")
    settings.auto:SetText("Auto-open on instance entry: " .. (s.auto_open and "ON" or "OFF"))
    settings.suggest:SetText("Instance suggestions: " .. (s.suggestions and "ON" or "OFF"))
    settings.lock:SetText("Window position: " .. (s.locked and "LOCKED" or "UNLOCKED"))
    settings.scale:SetText(string.format("Requested scale %.1f / fitted to screen",s.scale))
    if not settings.offset:HasFocus() then settings.offset:SetText(tostring(s.day_offset_minutes)) end
    settings.warning:SetText(F.warning or "Fixed offset does not follow daylight-saving changes. Python reports use their configured timezone.")
  end
end

function D.Show() create(); window:Show(); D.Refresh() end
function D.Toggle() create(); if window:IsShown() then window:Hide() else D.Show() end end
