RingoWoWOpsDB = {
  version = "0.3.0",
  schema_version = 3,
  sessions = {
    { id = "session-current-1", status = "completed", started_at = 1780261200,
      ended_at = 1780264800, duration_seconds = 3600, character = "Testpal",
      realm = "Testrealm", gold_start = 10000, gold_end = 12500,
      activity_start = "questing", activity_end = "questing" }
  },
  snapshots = {
    { id = "snapshot-current-1", session_id = "session-current-1", time = 1780263000,
      character = "Testpal", realm = "Testrealm", level = 70, zone = "Test Zone",
      gold = 12500, activity = "dungeon" },
    "malformed snapshot retained in validation output"
  },
  notes = {
    { id = "note-current-1", session_id = "session-current-1", time = 1780263100,
      character = "Testpal", realm = "Testrealm", text = "Current sanitized note" }
  },
  activities = {
    { id = "activity-current-1", session_id = "session-current-1", time = 1780263200,
      character = "Testpal", realm = "Testrealm", activity = "dungeon", source = "manual" }
  },
  events = {
    { id = "event-current-1", session_id = "session-current-1", time = 1780263300,
      character = "Testpal", realm = "Testrealm", type = "market", text = "sanitized" }
  },
  settings = { default_activity = "questing" }
}
