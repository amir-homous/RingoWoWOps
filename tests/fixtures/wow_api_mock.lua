-- Sanitized UI/API test double, not an in-game runtime.
frames={}; messages={}; SlashCmdList={}; UISpecialFrames={}; BackdropTemplateMixin={}
clock=1780261200; gold=100000; character="Testpal"; realm="Testrealm"
zone="Test Zone"; instanceName="Stratholme"; inside=false; combat=false
function time() return clock end
function print(value) table.insert(messages,value) end
function GetMoney() return gold end
function UnitName() return character end
function GetRealmName() return realm end
function UnitClass() return "Paladin","PALADIN" end
function UnitFactionGroup() return "Horde" end
function UnitLevel() return 70 end
function UnitXP() return 0 end
function UnitXPMax() return 100 end
function GetXPExhaustion() return 0 end
function GetZoneText() return zone end
function GetSubZoneText() return "" end
function GetInstanceInfo() return instanceName,"party",1,"Normal",5,nil,nil,999 end
function IsInInstance() return inside,"party" end
function InCombatLockdown() return combat end
local methods={}
function methods:SetScript(name,fn) self.scripts[name]=fn end
function methods:RegisterEvent(name) self.events[name]=true end
function methods:SetSize(w,h) self.width=w; self.height=h end
function methods:SetWidth(w) self.width=w end
function methods:SetHeight(h) self.height=h end
function methods:GetWidth() return self.width or 100 end
function methods:GetHeight() return self.height or 24 end
function methods:GetStringHeight() return 80 end
function methods:SetScrollChild(child) self.scrollChild=child end
function methods:SetText(s) self.text=s end
function methods:GetText() return self.text or "" end
function methods:SetPoint(...) self.point={...} end
function methods:ClearAllPoints() self.point=nil end
function methods:GetCenter() return 400,300 end
function methods:SetScale(scale) self.scale=scale end
function methods:GetScale() return self.scale or 1 end
function methods:Show() self.shown=true end
function methods:Hide() self.shown=false; if self.scripts.OnHide then self.scripts.OnHide(self) end end
function methods:SetShown(value) if value then self:Show() else self:Hide() end end
function methods:IsShown() return self.shown end
function methods:Disable() self.disabled=true end
function methods:Enable() self.disabled=false end
function methods:ClearFocus() self.focus=false end
function methods:HasFocus() return self.focus==true end
function methods:Click() if not self.disabled and self.shown and self.scripts.OnClick then self.scripts.OnClick(self) end end
for _,name in ipairs({"SetJustifyH","SetJustifyV","SetFrameStrata","SetClampedToScreen","SetMovable",
 "EnableMouse","RegisterForDrag","SetBackdrop","SetBackdropColor","SetBackdropBorderColor",
 "SetAutoFocus","SetMaxLetters","StartMoving","StopMovingOrSizing"}) do methods[name]=function() end end
function CreateFrame(kind,name,parent,template)
  local f=setmetatable({kind=kind,name=name,parent=parent,template=template,scripts={},events={},shown=true},{__index=methods})
  table.insert(frames,f); if name then _G[name]=f end; return f
end
function methods:CreateFontString(name,layer,font) return CreateFrame("FontString",name,self,font) end
UIParent=CreateFrame("Frame","UIParent"); UIParent:SetSize(1920,1080)
function fire(event,...)
  for _,frame in ipairs(frames) do if frame.events[event] and frame.scripts.OnEvent then frame.scripts.OnEvent(frame,event,...) end end
end
function clickText(title)
  for _,frame in ipairs(frames) do if frame.kind=="Button" and frame.text==title and frame.shown then frame:Click(); return true end end
  return false
end
