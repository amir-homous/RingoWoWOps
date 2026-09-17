-- Single registry consumed by the addon and the local Python pipeline (via Lupa).
-- No unverified instance/map identifiers. Matching names is only a suggestion.
RingoWoWOpsFarmPresets = {
  {id="STRATHOLME_PALADIN", display_name="Stratholme / Paladin", mode="solo_farm",
   class_hint="PALADIN", instance_name="Stratholme", enabled=true, version=1},
  {id="BOTANICA_TANK_HR", display_name="Botanica / Tank HR", mode="tank_hr",
   class_hint="TANK", instance_name="The Botanica", enabled=false, version=1},
  {id="SHADOW_LAB_MAGE_BOOST", display_name="Shadow Lab / Mage Boost", mode="boost",
   class_hint="MAGE", instance_name="Shadow Labyrinth", enabled=false, version=1}
}
